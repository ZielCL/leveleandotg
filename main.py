import os
import logging
import random
import datetime
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import nest_asyncio
import motor.motor_asyncio
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from telegram.error import Forbidden

# ─── Keep-Alive Server ────────────────────────────────────────────
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    def do_HEAD(self):
        self.send_response(200); self.end_headers()

def run_keepalive_server():
    port = int(os.getenv("PORT", "3000"))
    HTTPServer(("0.0.0.0", port), KeepAliveHandler).serve_forever()

threading.Thread(target=run_keepalive_server, daemon=True).start()

# ─── Setup ────────────────────────────────────────────────────────
nest_asyncio.apply()
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
if not BOT_TOKEN or not MONGO_URI:
    print("❌ Faltan BOT_TOKEN o MONGO_URI en .env"); exit(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── MongoDB ──────────────────────────────────────────────────────
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = client.mi_base_de_datos
xp_collection     = db.xp_usuarios
config_collection = db.temas_configurados
alerts_collection = db.level_alerts

# ─── Helpers ──────────────────────────────────────────────────────
def xp_para_subir(nivel: int) -> int:
    # Nivel 1 → 100 XP; sube de 7 XP adicionales por nivel
    return 100 + 7 * (nivel - 1)

def make_key(chat_id: int, user_id: int) -> str:
    return f"{chat_id}_{user_id}"

async def send_top_page(bot, chat_id: int, page: int):
    prefix = f"{chat_id}_"
    total = await xp_collection.count_documents({
        "_id": {"$regex": f"^{prefix}"}
    })
    pages = max(1, (total + 9)//10)
    page = max(1, min(page, pages))
    cursor = xp_collection.find({
        "_id": {"$regex": f"^MONTH_{prefix}"}
    }).sort("xp_month",-1).skip((page-1)*10).limit(10)
    docs = await cursor.to_list(10)

    text = f"🏆 Ranking Mensual (página {page}/{pages}):\n"
    for i, doc in enumerate(docs, start=(page-1)*10+1):
        _, uid_str = doc["_id"].split("_",2)[1:]
        uid = int(uid_str)
        try:
            name = (await bot.get_chat_member(chat_id, uid)).user.full_name
        except:
            name = f"User {uid}"
        text += f"{i}. {name} — Nivel {doc['lvl_month']}, {doc['xp_month']} XP\n"

    btns = []
    if page>1:    btns.append(InlineKeyboardButton("◀️", callback_data=f"levtop_{page-1}"))
    if page<pages:btns.append(InlineKeyboardButton("▶️", callback_data=f"levtop_{page+1}"))
    kb = InlineKeyboardMarkup([btns]) if btns else None
    return text, kb

# ─── Startup ──────────────────────────────────────────────────────
async def on_startup(app):
    logger.info("✅ Bot operativo")
    await app.bot.delete_webhook(drop_pending_updates=True)
    await app.bot.set_my_commands([
        BotCommand("start",      "Cómo instalar y configurar el bot"),
        BotCommand("levsettema", "Configura hilo de alertas de nivel (admin)"),
        BotCommand("levalerta",  "Define premio por nivel (admin)"),
        BotCommand("levperfil",  "Muestra XP/nivel mensual y total"),
        BotCommand("levtop",     "Ranking mensual con paginado"),
        BotCommand("levcomandos","Lista de comandos disponibles"),
    ])
    async for cfg in config_collection.find({}):
        try:
            await app.bot.send_message(cfg["_id"], "🤖 LeveleandoTG activo.")
        except Forbidden:
            await config_collection.delete_one({"_id": cfg["_id"]})

# ─── /start ───────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 ¡Hola! Soy LeveleandoTG.\n"
        "1️⃣ Agrégame como admin en tu grupo.\n"
        "2️⃣ Usa /levsettema <thread_id> para definir dónde mando alertas.\n"
        "3️⃣ Usa /levalerta <nivel> <mensaje> para configurar premios.\n"
        "Cada mes tu XP mensual se reinicia, pero guardo tu total histórico.\n"
        "Escribe /levcomandos para ver los comandos."
    )

# ─── Handlers de configuración ────────────────────────────────────
async def levsettema(update, ctx):
    chat, user = update.effective_chat, update.effective_user
    if chat.type not in ("group","supergroup"): return
    mem = await ctx.bot.get_chat_member(chat.id, user.id)
    if mem.status not in ("administrator","creator"):
        return await update.message.reply_text("❌ Solo administradores.")
    if not ctx.args or not ctx.args[0].isdigit():
        return await update.message.reply_text(
            "❌ Uso: /levsettema <thread_id>\n"
            "– En Desktop/Web, copia enlace de un mensaje → el número antes del segundo / es el thread_id."
        )
    tid = int(ctx.args[0])
    await config_collection.update_one({"_id":chat.id},{"$set":{"thread_id":tid}}, upsert=True)
    await update.message.reply_text(f"✅ Hilo configurado: {tid}")

async def levalerta(update, ctx):
    chat, user = update.effective_chat, update.effective_user
    if chat.type not in ("group","supergroup"): return
    mem = await ctx.bot.get_chat_member(chat.id, user.id)
    if mem.status not in ("administrator","creator"):
        return await update.message.reply_text("❌ Solo administradores.")
    if len(ctx.args)<2 or not ctx.args[0].isdigit():
        return await update.message.reply_text("❌ Uso: /levalerta <nivel> <mensaje>")
    lvl = int(ctx.args[0]); msg = " ".join(ctx.args[1:])
    await alerts_collection.update_one(
        {"_id":f"{chat.id}_{lvl}"}, {"$set":{"message":msg}}, upsert=True
    )
    await update.message.reply_text(f"✅ Premio configurado para nivel {lvl}.")

# ─── /levperfil ───────────────────────────────────────────────────
async def levperfil(update, ctx):
    chat, user = update.effective_chat, update.effective_user
    key = make_key(chat.id, user.id)

    # mes actual
    ahora = datetime.datetime.utcnow()
    mes_tag = ahora.strftime("%Y-%m")
    rec = await xp_collection.find_one({"_id":key})
    # si cambió mes, reinicio mensual
    if not rec or rec.get("month")!=mes_tag:
        await xp_collection.update_one(
            {"_id":key},
            {"$set":{"xp_month":0,"lvl_month":0,"month":mes_tag},
             "$setOnInsert":{"xp_total":rec.get("xp_total",0),"lvl_total":rec.get("lvl_total",0)}},
            upsert=True
        )
        xp_m=0; lvl_m=0; xp_t=rec.get("xp_total",0) if rec else 0; lvl_t=rec.get("lvl_total",0) if rec else 0
    else:
        xp_m = rec["xp_month"]; lvl_m = rec["lvl_month"]
        xp_t = rec["xp_total"]; lvl_t = rec["lvl_total"]

    # posición mensual
    pref = f"MONTH_{chat.id}_"
    mayores = await xp_collection.count_documents({
        "_id": {"$regex":f"^{pref}"},
        "xp_month": {"$gt": xp_m}
    })
    pos, tot = mayores+1, await xp_collection.count_documents({"_id":{"$regex":f"^{pref}"}})

    falta = xp_para_subir(lvl_m) - xp_m if lvl_m<100 else 0

    await update.message.reply_text(
        f"{user.full_name}:\n"
        f"📊 Mensual: {xp_m}/{xp_para_subir(lvl_m)} XP, Nivel {lvl_m}, Pos {pos}/{tot}\n"
        f"🏅 Histórico: {xp_t} XP, Nivel {lvl_t}\n"
        f"🔜 XP para siguiente nivel: {falta}"
    )

# ─── /levtop ──────────────────────────────────────────────────────
async def levtop(update, ctx):
    chat=update.effective_chat
    cfg = await config_collection.find_one({"_id":chat.id})
    if not cfg: return await update.message.reply_text("❌ /levsettema primero.")
    txt, kb = await send_top_page(ctx.bot, chat.id, page=1)
    await update.message.reply_text(txt, reply_markup=kb, parse_mode="HTML")

async def levtop_cb(update, ctx):
    q=update.callback_query; await q.answer()
    chat=q.message.chat
    pg=int(q.data.split("_")[1])
    txt,kb=await send_top_page(ctx.bot, chat.id, pg)
    await q.edit_message_text(txt, reply_markup=kb, parse_mode="HTML")

# ─── Comandos y mensajes ───────────────────────────────────────────
async def levcomandos(update, ctx):
    cmds = (
        "📜 Comandos:\n"
        "/start, /levsettema, /levalerta\n"
        "/levperfil, /levtop, /levcomandos\n"
    )
    await update.message.reply_text(cmds)

async def handle_message(update, ctx):
    msg=update.message
    if not msg or msg.from_user.is_bot: return
    chat, user = msg.chat, msg.from_user
    cfg = await config_collection.find_one({"_id":chat.id})
    if not cfg: return
    key = make_key(chat.id, user.id)
    rec = await xp_collection.find_one({"_id":key})
    ahora = datetime.datetime.utcnow().strftime("%Y-%m")
    # reinicio mensual si aplica
    if not rec or rec.get("month")!=ahora:
        rec = {"xp_month":0,"lvl_month":0,"xp_total":rec.get("xp_total",0) if rec else 0,
               "lvl_total":rec.get("lvl_total",0) if rec else 0,"month":ahora}
    # ganancia
    gan = random.randint(30,50) if msg.photo else random.randint(7,10)
    xp_m = rec["xp_month"] + gan
    xp_t = rec["xp_total"] + gan
    lvl_m = rec["lvl_month"]
    lvl_t = rec["lvl_total"]
    # subir niveles
    while lvl_m<100 and xp_m>=xp_para_subir(lvl_m):
        xp_m -= xp_para_subir(lvl_m)
        lvl_m+=1
        lvl_t+=1
        # felicitación
        thread=cfg["thread_id"]
        mention=f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
        await ctx.bot.send_message(
            chat.id, text=f"🎉 {mention} subió al nivel {lvl_m}!", parse_mode="HTML",
            message_thread_id=thread
        )
        # premio
        alt=await alerts_collection.find_one({"_id":f"{chat.id}_{lvl_m}"})
        if alt:
            await ctx.bot.send_message(chat.id, alt["message"], message_thread_id=thread)
    # guardar
    await xp_collection.update_one(
        {"_id":key},
        {"$set":{"xp_month":xp_m,"lvl_month":lvl_m,
                 "xp_total":xp_t,"lvl_total":lvl_t,"month":ahora}},
        upsert=True
    )

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(on_startup).build()
    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("levsettema",  levsettema))
    app.add_handler(CommandHandler("levalerta",   levalerta))
    app.add_handler(CommandHandler("levperfil",   levperfil))
    app.add_handler(CommandHandler("levtop",      levtop))
    app.add_handler(CommandHandler("levcomandos", levcomandos))
    app.add_handler(CallbackQueryHandler(levtop_cb, pattern=r"^levtop_\d+$"))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
