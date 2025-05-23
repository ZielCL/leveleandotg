import os
import logging
import random
import math
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

# ─── Keep-Alive Server ────────────────────────────────────────────
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        print(f"🔔 Ping GET recibido de {self.client_address}")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def do_HEAD(self):
        print(f"🔔 Ping HEAD recibido de {self.client_address}")
        self.send_response(200)
        self.end_headers()

def run_keepalive_server():
    port = int(os.getenv("PORT", "3000"))
    print(f"🌐 Keep-Alive listening on port {port}")
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
xp_collection     = db.xp_usuarios
config_collection = db.temas_configurados
alerts_collection = db.level_alerts      # colección para mensajes de premio

# ─── Helpers ──────────────────────────────────────────────────────
def xp_para_subir(nivel: int) -> int:
    """XP necesaria para pasar del nivel 'nivel' al siguiente."""
    return round(0.18 * nivel**2 + 5 * nivel)

def make_key(chat_id: int, user_id: int) -> str:
    return f"{chat_id}_{user_id}"

async def send_top_page(bot, chat_id: int, page: int):
    prefix = f"{chat_id}_"
    total = await xp_collection.count_documents({"_id": {"$regex": f"^{prefix}"}})
    pages = max(1, math.ceil(total/10))
    page = max(1, min(page, pages))
    cursor = xp_collection.find({"_id": {"$regex": f"^{prefix}"}}) \
                          .sort("xp", -1).skip((page-1)*10).limit(10)
    docs = await cursor.to_list(10)

    text = f"🏆 XP Ranking (página {page}/{pages}):\n"
    for idx, doc in enumerate(docs, start=(page-1)*10+1):
        _, uid_str = doc["_id"].split("_",1)
        uid = int(uid_str)
        try:
            member = await bot.get_chat_member(chat_id, uid)
            name = member.user.full_name
        except:
            name = f"User {uid}"
        text += f"{idx}. {name} — Nivel {doc['nivel']}, {doc['xp']} XP\n"

    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("◀️", callback_data=f"levtop_{page-1}"))
    if page < pages:
        buttons.append(InlineKeyboardButton("▶️", callback_data=f"levtop_{page+1}"))
    kb = InlineKeyboardMarkup([buttons]) if buttons else None
    return text, kb

# ─── Startup ──────────────────────────────────────────────────────
async def on_startup(app):
    logger.info("✅ Token cargado")
    await client.admin.command("ping")
    logger.info("✅ Conectado a MongoDB Atlas")
    logger.info("🤖 Bot operativo")

    await app.bot.set_my_commands([
        BotCommand("start",      "Cómo instalar y configurar el bot"),
        BotCommand("levsettema", "Configura hilo de alertas de nivel (admin)"),
        BotCommand("levalerta",  "Define premio por nivel (admin)"),
        BotCommand("levperfil",  "Muestra tu XP, nivel y posición"),
        BotCommand("levtop",     "Ranking XP con paginado"),
        BotCommand("levcomandos","Lista de comandos disponibles"),
    ])
    logger.info("✅ Comandos registrados")

    async for cfg in config_collection.find({}):
        chat_id, thread_id = cfg["_id"], cfg["thread_id"]
        await app.bot.send_message(chat_id, "🤖 LeveleandoTG activo.")
        await app.bot.send_message(
            chat_id,
            message_thread_id=thread_id,
            text="🎉 Alertas de nivel activas."
        )

# ─── /start ───────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 ¡Hola! Soy LeveleandoTG.\n"
        "1️⃣ Agrégame como admin.\n"
        "2️⃣ Usa /levsettema <thread_id> para elegir el hilo de alertas.\n"
        "   • En Desktop/Web copia enlace de un mensaje → el número final es el thread_id.\n"
        "3️⃣ Usa /levalerta <nivel> <mensaje> para definir premio al subir.\n\n"
        "Escribe /levcomandos para ver todos los comandos."
    )

# ─── /levsettema ──────────────────────────────────────────────────
async def levsettema(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat, user = update.effective_chat, update.effective_user
    if chat.type not in ("group","supergroup"):
        return
    member = await context.bot.get_chat_member(chat.id, user.id)
    if member.status not in ("administrator","creator"):
        return await update.message.reply_text("❌ Solo administradores pueden usarlo.")
    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text(
            "❌ Uso correcto: /levsettema <thread_id>\n\n"
            "🔍 Cómo obtener el thread_id:\n"
            "1. En Telegram Desktop/Web, abre el grupo y selecciona el tema deseado.\n"
            "2. Haz clic derecho en un mensaje → Copiar enlace.\n"
            "3. El enlace será algo como:\n"
            "   https://t.me/c/1234567890/90\n"
            "   ⇒ El número final (aquí “90”) es el thread_id.\n"
            "Ejemplo: /levsettema 90"
        )
    thread_id = int(context.args[0])
    await config_collection.update_one(
        {"_id": chat.id},
        {"$set": {"thread_id": thread_id}},
        upsert=True
    )
    await update.message.reply_text(f"✅ Hilo configurado: {thread_id}")

# ─── /levalerta ───────────────────────────────────────────────────
async def levalerta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat, user = update.effective_chat, update.effective_user
    if chat.type not in ("group","supergroup"):
        return
    member = await context.bot.get_chat_member(chat.id, user.id)
    if member.status not in ("administrator","creator"):
        return await update.message.reply_text("❌ Solo administradores pueden usarlo.")
    if len(context.args) < 2 or not context.args[0].isdigit():
        return await update.message.reply_text("❌ Uso: /levalerta <nivel> <mensaje>")
    nivel = int(context.args[0])
    mensaje = " ".join(context.args[1:])
    await alerts_collection.update_one(
        {"_id": f"{chat.id}_{nivel}"},
        {"$set": {"message": mensaje}},
        upsert=True
    )
    await update.message.reply_text(f"✅ Premio guardado para nivel {nivel}.")

# ─── /levperfil ───────────────────────────────────────────────────
async def levperfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat, user = update.effective_chat, update.effective_user
    key = make_key(chat.id, user.id)
    doc = await xp_collection.find_one({"_id": key})
    xp  = doc["xp"]    if doc else 0
    lvl = doc["nivel"] if doc else 0

    prefix = f"{chat.id}_"
    mayores = await xp_collection.count_documents({
        "_id": {"$regex": f"^{prefix}"},
        "xp":  {"$gt": xp}
    })
    posicion = mayores + 1
    total    = await xp_collection.count_documents({"_id": {"$regex": f"^{prefix}"}})

    await update.message.reply_text(
        f"{user.full_name}:\n"
        f"• XP: {xp}\n"
        f"• Nivel: {lvl}\n"
        f"• Posición: {posicion}/{total}"
    )

# ─── /levtop ──────────────────────────────────────────────────────
async def levtop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    cfg = await config_collection.find_one({"_id": chat.id})
    if not cfg:
        return await update.message.reply_text("❌ No hay hilo configurado (/levsettema).")
    text, kb = await send_top_page(context.bot, chat.id, page=1)
    await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")

# ─── Callback paginado ────────────────────────────────────────────
async def levtop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat = query.message.chat
    page = int(query.data.split("_",1)[1])
    text, kb = await send_top_page(context.bot, chat.id, page)
    await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

# ─── /levcomandos ─────────────────────────────────────────────────
async def levcomandos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmds = (
        "📜 Comandos disponibles:\n"
        "/start         — Cómo instalar y configurar el bot\n"
        "/levsettema    — Define hilo de alertas (admin)\n"
        "/levalerta     — Define premio por nivel (admin)\n"
        "/levperfil     — Muestra tu XP, nivel y posición\n"
        "/levtop        — Ranking XP con paginado\n"
        "/levcomandos   — Lista de comandos\n"
    )
    await update.message.reply_text(cmds)

# ─── Mensajes ─────────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg  = update.message
    if not msg or msg.from_user.is_bot:
        return
    chat, user = msg.chat, msg.from_user
    cfg = await config_collection.find_one({"_id": chat.id})
    if not cfg:
        return
    thread_id = cfg["thread_id"]
    key = make_key(chat.id, user.id)
    rec = await xp_collection.find_one({"_id": key})
    xp  = rec["xp"]    if rec else 0
    lvl = rec["nivel"] if rec else 0

    gan = random.randint(20,30) if msg.photo else random.randint(7,10)
    xp_nivel = xp + gan
    req = xp_para_subir(lvl)

    if xp_nivel >= req and lvl < 100:
        nuevo_nivel = lvl + 1
        xp_nivel = 0
        falta = xp_para_subir(nuevo_nivel)
        mention = f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
        await context.bot.send_message(
            chat_id=chat.id,
            message_thread_id=thread_id,
            text=(
                f"🎉 <b>¡Felicidades!</b> {mention} alcanzó el nivel <b>{nuevo_nivel}</b> 🚀\n\n"
                f"Ahora necesitas <b>{falta} XP</b> para el nivel {nuevo_nivel+1}."
            ),
            parse_mode="HTML"
        )
    else:
        nuevo_nivel = lvl

    await xp_collection.update_one(
        {"_id": key},
        {"$set": {"xp": xp_nivel, "nivel": nuevo_nivel}},
        upsert=True
    )

# ─── Main ─────────────────────────────────────────────────────────
def main():
    app = ApplicationBuilder()\
        .token(BOT_TOKEN)\
        .post_init(on_startup)\
        .build()

    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("levsettema",  levsettema))
    app.add_handler(CommandHandler("levalerta",   levalerta))
    app.add_handler(CommandHandler("levperfil",   levperfil))
    app.add_handler(CommandHandler("levtop",      levtop))
    app.add_handler(CommandHandler("levcomandos", levcomandos))
    app.add_handler(CallbackQueryHandler(levtop_callback, pattern=r"^levtop_\d+$"))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    app.run_polling()

if __name__ == "__main__":
    main()

