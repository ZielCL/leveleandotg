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
from telegram.error import Forbidden, Conflict

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
    return 100 + 7 * (nivel - 1)

def make_key(chat_id: int, user_id: int) -> str:
    return f"{chat_id}_{user_id}"

async def send_top_page(bot, chat_id: int, page: int):
    prefix = f"{chat_id}_"
    total  = await xp_collection.count_documents({"_id": {"$regex": f"^{prefix}"}})
    pages  = max(1, (total+9)//10)
    page   = max(1, min(page, pages))
    docs   = await xp_collection.find({"_id": {"$regex": f"^{prefix}"}})\
                .sort("xp",-1).skip((page-1)*10).limit(10).to_list(10)

    text = f"🏆 XP Ranking (página {page}/{pages}):\n"
    for i, d in enumerate(docs, start=(page-1)*10+1):
        uid = int(d["_id"].split("_",1)[1])
        try:
            name = (await bot.get_chat_member(chat_id, uid)).user.full_name
        except:
            name = f"User {uid}"
        text += f"{i}. {name} — Nivel {d['nivel']}, {d['xp']} XP\n"

    btns=[]
    if page>1:    btns.append(InlineKeyboardButton("◀️", callback_data=f"levtop_{page-1}"))
    if page<pages:btns.append(InlineKeyboardButton("▶️", callback_data=f"levtop_{page+1}"))
    kb = InlineKeyboardMarkup([btns]) if btns else None
    return text, kb

# ─── on_startup ───────────────────────────────────────────────────
async def on_startup(app):
    logger.info("✅ Bot arrancado")
    # Borramos webhook y descartamos updates pendientes
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        logger.info("✅ Webhook borrado ✔ drop_pending_updates=True")
    except Exception as e:
        logger.warning(f"⚠️ Al borrar webhook: {e}")

    # Registramos comandos
    await app.bot.set_my_commands([
        BotCommand("start",      "Cómo instalar y configurar el bot"),
        BotCommand("levsettema", "Configura hilo de alertas (admin)"),
        BotCommand("levalerta",  "Define premio por nivel (admin)"),
        BotCommand("levperfil",  "Muestra XP/nivel y XP faltante"),
        BotCommand("levtop",     "Ranking XP con paginado"),
        BotCommand("levcomandos","Lista comandos"),
    ])

    # Notificar a cada grupo configurado
    async for cfg in config_collection.find({}):
        try:
            await app.bot.send_message(cfg["_id"], "🤖 LeveleandoTG activo.")
        except Forbidden:
            await config_collection.delete_one({"_id": cfg["_id"]})
            logger.warning(f"⚠️ Borrada config para {cfg['_id']} (bot expulsado)")

# ─── Handlers ─────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 ¡Hola! Soy LeveleandoTG.\n"
        "1️⃣ Agrégame como admin.\n"
        "2️⃣ /levsettema <thread_id> para definir hilo de alertas.\n"
        "3️⃣ /levalerta <nivel> <mensaje> para premios.\n"
        "Escribe /levcomandos para verlos todos."
    )

async def levsettema(update, ctx):
    chat, user = update.effective_chat, update.effective_user
    if chat.type not in ("group","supergroup"): return
    mem = await ctx.bot.get_chat_member(chat.id, user.id)
    if mem.status not in ("administrator","creator"):
        return await update.message.reply_text("❌ Solo admins.")
    if not ctx.args or not ctx.args[0].isdigit():
        return await update.message.reply_text(
            "❌ Uso: `/levsettema <thread_id>`\n"
            "– En Desktop/Web copia enlace de un mensaje → el número al final es thread_id."
        )
    await config_collection.update_one(
        {"_id": chat.id},
        {"$set": {"thread_id": int(ctx.args[0])}},
        upsert=True
    )
    await update.message.reply_text(f"✅ Hilo configurado: {ctx.args[0]}")

async def levalerta(update, ctx):
    chat, user = update.effective_chat, update.effective_user
    if chat.type not in ("group","supergroup"): return
    mem = await ctx.bot.get_chat_member(chat.id, user.id)
    if mem.status not in ("administrator","creator"):
        return await update.message.reply_text("❌ Solo admins.")
    if len(ctx.args)<2 or not ctx.args[0].isdigit():
        return await update.message.reply_text("❌ Uso: `/levalerta <nivel> <mensaje>`")
    lvl = int(ctx.args[0]); msg = " ".join(ctx.args[1:])
    await alerts_collection.update_one(
        {"_id":f"{chat.id}_{lvl}"},
        {"$set":{"message":msg}},
        upsert=True
    )
    await update.message.reply_text(f"✅ Premio guardado para nivel {lvl}.")

async def levperfil(update, ctx):
    chat, user = update.effective_chat, update.effective_user
    key = make_key(chat.id, user.id)
    rec = await xp_collection.find_one({"_id":key}) or {}
    xp, lvl = rec.get("xp",0), rec.get("nivel",0)
    falt = max(0, xp_para_subir(lvl) - xp)
    await update.message.reply_text(
        f"{user.full_name}:\n"
        f"• XP: {xp}\n"
        f"• Nivel: {lvl}\n"
        f"• Para siguiente nivel: {falt} XP"
    )

async def levtop(update, ctx):
    chat = update.effective_chat
    cfg = await config_collection.find_one({"_id":chat.id})
    if not cfg:
        return await update.message.reply_text("❌ /levsettema primero.")
    text, kb = await send_top_page(ctx.bot, chat.id, page=1)
    await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")

async def levtop_cb(update, ctx):
    q = update.callback_query; await q.answer()
    page = int(q.data.split("_",1)[1])
    text, kb = await send_top_page(ctx.bot, q.message.chat.id, page)
    await q.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

async def levcomandos(update, ctx):
    await update.message.reply_text(
        "📜 Comandos:\n"
        "/start, /levsettema, /levalerta,\n"
        "/levperfil, /levtop, /levcomandos"
    )

async def handle_message(update, ctx):
    msg = update.message
    if not msg or msg.from_user.is_bot: return
    chat, user = msg.chat, msg.from_user
    cfg = await config_collection.find_one({"_id":chat.id})
    if not cfg: return
    key = make_key(chat.id, user.id)
    rec = await xp_collection.find_one({"_id":key}) or {"xp":0,"nivel":0}
    xp, lvl = rec["xp"], rec["nivel"]
    gain = random.randint(20,30) if msg.photo else random.randint(7,10)
    xp += gain
    new_lvl = lvl
    while new_lvl<100 and xp>=xp_para_subir(new_lvl):
        xp -= xp_para_subir(new_lvl)
        new_lvl += 1
        # felicitación
        mention = f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
        await ctx.bot.send_message(
            chat.id,
            message_thread_id=cfg["thread_id"],
            text=f"🎉 {mention} subió al nivel {new_lvl}!",
            parse_mode="HTML"
        )
        # premio
        alt = await alerts_collection.find_one({"_id":f"{chat.id}_{new_lvl}"})
        if alt:
            await ctx.bot.send_message(
                chat.id,
                message_thread_id=cfg["thread_id"],
                text=alt["message"]
            )
    # guardamos
    await xp_collection.update_one(
        {"_id":key},
        {"$set":{"xp":xp,"nivel":new_lvl}},
        upsert=True
    )

# ─── Main ─────────────────────────────────────────────────────────
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

    # Ejecutamos polling y capturamos 409 para que no corte la app
    try:
        app.run_polling()
    except Conflict as e:
        logger.error("🔄 Conflict 409: otro getUpdates activo. Delete webhook y reinicia.")

if __name__ == "__main__":
    main()
