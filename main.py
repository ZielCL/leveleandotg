import os
import logging
import random
import math
import threading
from datetime import datetime
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
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

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
    print("❌ Faltan BOT_TOKEN o MONGO_URI en .env")
    exit(1)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── MongoDB ──────────────────────────────────────────────────────
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = client.mi_base_de_datos
xp_collection       = db.xp_usuarios       # total acumulado
db_monthly          = db.xp_mensual       # XP del mes actual
config_collection   = db.temas_configurados
alerts_collection   = db.level_alerts
stats_collection    = db.user_stats        # conteo top3 y meses

# ─── Helpers ──────────────────────────────────────────────────────
def xp_para_subir(nivel: int) -> int:
    return 100 + 7 * (nivel - 1)

def make_key(chat_id: int, user_id: int) -> str:
    return f"{chat_id}_{user_id}"

async def rollover_month(chat_id: int):
    # Registrar top3 del mes pasado
    cursor = db_monthly.find({"_id": {"$regex": f"^{chat_id}_"}})\
                     .sort("xp", -1).limit(3)
    top3 = await cursor.to_list(3)
    for doc in top3:
        uid = doc["_id"].split("_",1)[1]
        await stats_collection.update_one(
            {"_id": f"{chat_id}_{uid}"},
            {"$inc": {"top3_count": 1}}, upsert=True
        )
    # Incrementar meses pasados
    cfg = await config_collection.find_one({"_id": chat_id}) or {}
    meses = cfg.get("meses_pasados", 0) + 1
    await config_collection.update_one(
        {"_id": chat_id},
        {"$set": {"meses_pasados": meses, "last_month": datetime.utcnow().month}},
        upsert=True
    )
    # Reset mensual
    await db_monthly.delete_many({"_id": {"$regex": f"^{chat_id}_"}})

async def ensure_monthly_state(chat_id: int):
    now = datetime.utcnow()
    cfg = await config_collection.find_one({"_id": chat_id})
    if not cfg or cfg.get("last_month") != now.month:
        await rollover_month(chat_id)

async def send_top_page(bot, chat_id: int, page: int, collec):
    prefix = f"{chat_id}_"
    total  = await collec.count_documents({"_id": {"$regex": f"^{prefix}"}})
    pages  = max(1, math.ceil(total/10))
    page   = max(1, min(page, pages))
    cursor = collec.find({"_id": {"$regex": f"^{prefix}"}})\
                     .sort("xp", -1).skip((page-1)*10).limit(10)
    docs   = await cursor.to_list(10)

    text = f"🏆 XP Ranking (página {page}/{pages}):\n"
    for idx, doc in enumerate(docs, start=(page-1)*10+1):
        uid = int(doc["_id"].split("_",1)[1])
        try:
            name = (await bot.get_chat_member(chat_id, uid)).user.full_name
        except:
            name = f"User {uid}"
        text += f"{idx}. {name} — Nivel {doc['nivel']}, {doc['xp']} XP\n"

    btns = []
    if page > 1:
        btns.append(InlineKeyboardButton("◀️", callback_data=f"top_{page-1}_{collec.name}"))
    if page < pages:
        btns.append(InlineKeyboardButton("▶️", callback_data=f"top_{page+1}_{collec.name}"))
    kb = InlineKeyboardMarkup([btns]) if btns else None
    return text, kb

# ─── Startup ──────────────────────────────────────────────────────
async def on_startup(app):
    logger.info("✅ Bot arrancando")
    await client.admin.command("ping")
    await app.bot.delete_webhook(drop_pending_updates=True)
    await app.bot.set_my_commands([
        BotCommand("start","Configurar bot"),
        BotCommand("levsettema","Define hilo alertas"),
        BotCommand("levalerta","Define premio por nivel"),
        BotCommand("levalertalist","Lista alertas"),
        BotCommand("levperfil","Perfil interactivo"),
        BotCommand("levtop","Ranking mes"),
        BotCommand("levtopacumulado","Ranking total"),
        BotCommand("levcomandos","Lista comandos"),
    ])

# ─── Command Handlers ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 ¡Hola! Soy LeveleandoTG.\n"
        "1) Agrégame como admin.\n"
        "2) /levsettema <thread_id> para definir hilo.\n"
        "3) /levalerta <nivel> <mensaje> para premio.\n"
        "Escribe /levcomandos para ver comandos."
    )

async def levsettema(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat, user = update.effective_chat, update.effective_user
    if chat.type not in ("group","supergroup"): return
    m = await context.bot.get_chat_member(chat.id, user.id)
    if m.status not in ("administrator","creator"):
        return await update.message.reply_text("❌ Solo admins pueden.")
    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text("❌ Uso: /levsettema <thread_id>")
    thread_id = int(context.args[0])
    await config_collection.update_one({"_id": chat.id}, {"$set": {"thread_id": thread_id}}, upsert=True)
    await update.message.reply_text(f"✅ Hilo configurado: {thread_id}")

async def levalerta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat, user = update.effective_chat, update.effective_user
    m = await context.bot.get_chat_member(chat.id, user.id)
    if m.status not in ("administrator","creator"):
        return await update.message.reply_text("❌ Solo admins.")
    if len(context.args) < 2 or not context.args[0].isdigit():
        return await update.message.reply_text("❌ Uso: /levalerta <nivel> <mensaje>")
    nivel = int(context.args[0])
    mensaje = " ".join(context.args[1:])
    logger.info(f"🔔 Guardando alerta nivel={nivel}: {mensaje!r}")
    await alerts_collection.update_one(
        {"_id": f"{chat.id}_{nivel}"},
        {"$set": {"message": mensaje}}, upsert=True
    )
    await update.message.reply_text(f"✅ Premio guardado para nivel {nivel}.")

async def levalertalist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    m = await context.bot.get_chat_member(chat.id, update.effective_user.id)
    if m.status not in ("administrator","creator"):
        return await update.message.reply_text("❌ Solo admins pueden ver la lista de alertas.")
    docs = await alerts_collection.find({"_id": {"$regex": f"^{chat.id}_"}}).to_list(None)
    if not docs:
        return await update.message.reply_text("🚫 No hay alertas configuradas.")
    text = "📋 Alertas configuradas:\n"
    for doc in docs:
        _, lvl = doc["_id"].split("_",1)
        text += f"• Nivel {lvl}: {doc.get('message')}\n"
    await update.message.reply_text(text)

async def levperfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat, user = update.effective_chat, update.effective_user
    await ensure_monthly_state(chat.id)
    key = make_key(chat.id, user.id)
    rec = await db_monthly.find_one({"_id": key}) or {}
    xp_m, lvl_m = rec.get("xp", 0), rec.get("nivel", 1)
    pref = f"{chat.id}_"
    higher = await db_monthly.count_documents({"_id": {"$regex": pref}, "xp": {"$gt": xp_m}})
    pos_m = higher+1; total_m = await db_monthly.count_documents({"_id": {"$regex": pref}})
    falta = xp_para_subir(lvl_m) - xp_m
    text = (
        f"{user.full_name}:\n"
        f"• Nivel: {lvl_m} \n"
        f"• Posición: {pos_m}/{total_m}\n\n"
        f"• XP: {xp_m}\n"
        f"• XP para siguiente nivel: {falta}\n"
    )
    btn = InlineKeyboardButton("➡️ Acumulado", callback_data="perfil_acum")
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup([[btn]]), parse_mode="HTML")

async def perfil_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat, user = update.effective_chat, update.effective_user
    key = make_key(chat.id, user.id)
    rec2 = await xp_collection.find_one({"_id": key}) or {}
    xp_a, lvl_a = rec2.get("xp", 0), rec2.get("nivel", 1)
    pref = f"{chat.id}_"
    higher2 = await xp_collection.count_documents({"_id": {"$regex": pref}, "xp": {"$gt": xp_a}})
    pos_a = higher2+1; total_a = await xp_collection.count_documents({"_id": {"$regex": pref}})
    stats = await stats_collection.find_one({"_id": key}) or {}
    top3c = stats.get("top3_count", 0)
    cfg = await config_collection.find_one({"_id": chat.id}) or {}
    meses = cfg.get("meses_pasados", 0)
    text = (
        f"Nivel acumulado: {lvl_a}\n"
        f"Posición acumulada: {pos_a}/{total_a}\n"
        f"Veces en top 3: {top3c}/{meses}\n"
    )
    btn = InlineKeyboardButton("⬅️ Mes actual", callback_data="perfil_mes")
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[btn]]), parse_mode="HTML")

async def levtop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    await ensure_monthly_state(chat.id)
    text, kb = await send_top_page(context.bot, chat.id, 1, db_monthly)
    await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")

async def levtopacumulado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    await ensure_monthly_state(chat.id)
    text, kb = await send_top_page(context.bot, chat.id, 1, xp_collection)
    await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")

async def top_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, page, collec_name = update.callback_query.data.split("_")
    collec = xp_collection if collec_name == "xp_usuarios" else db_monthly
    text, kb = await send_top_page(context.bot, update.effective_chat.id, int(page), collec)
    await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

async def levcomandos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📜 Comandos:\n"
        "/start\n"
        "/levsettema\n"
        "/levalerta\n"
        "/levalertatalist\n"
        "/levperfil\n"
        "/levtop\n"
        "/levtopacumulado\n"
        "/levcomandos"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or msg.from_user.is_bot: return
    chat, user = msg.chat, msg.from_user
    cfg = await config_collection.find_one({"_id": chat.id})
    if not cfg: return
    key = make_key(chat.id, user.id)
    rec = await xp_collection.find_one({"_id": key}) or {}
    xp  = rec.get("xp", 0)
    lvl = rec.get("nivel", 0)
    gan = random.randint(20,30) if msg.photo else random.randint(7,10)
    xp_nivel = xp + gan
    req      = xp_para_subir(lvl)
    if xp_nivel >= req and lvl < 100:
        nuevo_lvl = lvl + 1
        xp_nivel  = 0
        falta     = xp_para_subir(nuevo_lvl)
        # actualizar mensual y total
        await xp_collection.update_one({"_id": key},{"$set": {"xp": xp_nivel,"nivel": nuevo_lvl}}, upsert=True)
        await db_monthly.update_one({"_id": key},{"$set": {"xp": xp_nivel,"nivel": nuevo_lvl}}, upsert=True)
        mention = f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
        await context.bot.send_message(chat_id=chat.id,message_thread_id=cfg["thread_id"],
            text=(f"🎉 <b>¡Felicidades!</b> {mention} alcanzó nivel <b>{nuevo_lvl}</b> 🚀\n"
                  f"Ahora necesitas <b>{falta} XP</b> para el siguiente."),parse_mode="HTML")
        alt = await alerts_collection.find_one({"_id": f"{chat.id}_{nuevo_lvl}"})
        if alt and alt.get("message"):
            await context.bot.send_message(chat_id=chat.id,message_thread_id=cfg["thread_id"],text=alt["message"] )
    else:
        await xp_collection.update_one({"_id": key},{"$set": {"xp": xp_nivel}}, upsert=True)
        await db_monthly.update_one({"_id": key},{"$set": {"xp": xp_nivel}}, upsert=True)

# ─── main ────────────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(on_startup).build()
    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("levsettema",  levsettema))
    app.add_handler(CommandHandler("levalerta",   levalerta))
    app.add_handler(CommandHandler("levalertalist", levalertalist))
    app.add_handler(CommandHandler("levperfil",   levperfil))
    app.add_handler(CallbackQueryHandler(perfil_callback, pattern=r"^perfil_"))
    app.add_handler(CommandHandler("levtop",      levtop))
    app.add_handler(CommandHandler("levtopacumulado", levtopacumulado))
    app.add_handler(CallbackQueryHandler(top_callback, pattern=r"^top_"))
    app.add_handler(CommandHandler("levcomandos", levcomandos))
    
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
