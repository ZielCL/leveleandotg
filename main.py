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
from telegram.error import Forbidden

# ─── Keep-Alive Server (opcional, para pings HTTP) ────────────────
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
MONGO_URI  = os.getenv("MONGO_URI")
BASE_URL   = os.getenv("BASE_URL")  # p.ej. https://tu-app.onrender.com
if not BOT_TOKEN or not MONGO_URI or not BASE_URL:
    print("❌ Faltan BOT_TOKEN, MONGO_URI o BASE_URL en variables de entorno")
    exit(1)

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
    # Ejemplo de fórmula, ajusta a tu gusto
    return max(100, round(0.18 * nivel**2 + 5 * nivel))

def make_key(chat_id: int, user_id: int) -> str:
    return f"{chat_id}_{user_id}"

async def send_top_page(bot, chat_id: int, page: int):
    prefix = f"{chat_id}_"
    total  = await xp_collection.count_documents({"_id": {"$regex": f"^{prefix}"}})
    pages  = max(1, math.ceil(total/10))
    page   = max(1, min(page, pages))
    cursor = xp_collection.find({"_id": {"$regex": f"^{prefix}"}})\
                          .sort("xp", -1).skip((page-1)*10).limit(10)
    docs   = await cursor.to_list(10)

    text = f"🏆 XP Ranking (página {page}/{pages}):\n"
    for idx, doc in enumerate(docs, start=(page-1)*10+1):
        _, uid_str = doc["_id"].split("_",1)
        uid = int(uid_str)
        try:
            name = (await bot.get_chat_member(chat_id, uid)).user.full_name
        except:
            name = f"User {uid}"
        text += f"{idx}. {name} — Nivel {doc['nivel']}, {doc['xp']} XP\n"

    btns = []
    if page > 1:
        btns.append(InlineKeyboardButton("◀️", callback_data=f"levtop_{page-1}"))
    if page < pages:
        btns.append(InlineKeyboardButton("▶️", callback_data=f"levtop_{page+1}"))
    kb = InlineKeyboardMarkup([btns]) if btns else None
    return text, kb

# ─── Startup ──────────────────────────────────────────────────────
async def on_startup(app):
    logger.info("✅ Token cargado")
    await client.admin.command("ping")
    logger.info("✅ Conectado a MongoDB Atlas")

    # eliminar webhook viejo
    await app.bot.delete_webhook(drop_pending_updates=True)
    logger.info("✅ Webhook borrado, listo para recibir")

    # comandos de bot
    await app.bot.set_my_commands([
        BotCommand("start",      "Cómo instalar y configurar el bot"),
        BotCommand("levsettema", "Configura hilo de alertas de nivel (admin)"),
        BotCommand("levalerta",  "Define premio por nivel (admin)"),
        BotCommand("levperfil",  "Muestra XP, nivel, posición y XP para siguiente"),
        BotCommand("levtop",     "Ranking XP con paginado"),
        BotCommand("levcomandos","Lista de comandos disponibles"),
    ])
    logger.info("✅ Comandos registrados")

    # notificar a grupos ya configurados
    async for cfg in config_collection.find({}):
        chat_id, thread_id = cfg["_id"], cfg["thread_id"]
        try:
            await app.bot.send_message(chat_id, "🤖 LeveleandoTG activo.")
            await app.bot.send_message(
                chat_id,
                message_thread_id=thread_id,
                text="🎉 Alertas de nivel activas."
            )
        except Forbidden:
            await config_collection.delete_one({"_id": chat_id})
            logger.warning(f"Configuración eliminada para chat {chat_id} (bot expulsado)")
        except Exception as e:
            logger.error(f"Error notificando inicio en chat {chat_id}: {e}")

# ─── Comandos ─────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 ¡Hola! Soy LeveleandoTG.\n"
        "1️⃣ Agrégame como admin.\n"
        "2️⃣ /levsettema <thread_id> para definir hilo de alertas.\n"
        "   • En Desktop/Web copia enlace de mensaje → el número final es el thread_id.\n"
        "3️⃣ /levalerta <nivel> <mensaje> para definir premio al subir nivel.\n\n"
        "Escribe /levcomandos para ver todos los comandos."
    )

async def levsettema(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat, user = update.effective_chat, update.effective_user
    if chat.type not in ("group","supergroup"): return
    member = await context.bot.get_chat_member(chat.id, user.id)
    if member.status not in ("administrator","creator"):
        return await update.message.reply_text("❌ Solo administradores.")
    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text(
            "❌ Uso: /levsettema <thread_id>\n"
            "🔍 Copia enlace de mensaje en tema → número final es thread_id."
        )
    thread_id = int(context.args[0])
    await config_collection.update_one(
        {"_id": chat.id},
        {"$set": {"thread_id": thread_id}},
        upsert=True
    )
    await update.message.reply_text(f"✅ Hilo configurado: {thread_id}")

async def levalerta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat, user = update.effective_chat, update.effective_user
    if chat.type not in ("group","supergroup"): return
    member = await context.bot.get_chat_member(chat.id, user.id)
    if member.status not in ("administrator","creator"):
        return await update.message.reply_text("❌ Solo administradores.")
    if len(context.args) < 2 or not context.args[0].isdigit():
        return await update.message.reply_text("❌ Uso: /levalerta <nivel> <mensaje>")
    nivel   = int(context.args[0])
    mensaje = " ".join(context.args[1:])
    await alerts_collection.update_one(
        {"_id": f"{chat.id}_{nivel}"},
        {"$set": {"message": mensaje}},
        upsert=True
    )
    await update.message.reply_text(f"✅ Premio guardado para nivel {nivel}.")

async def levperfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat, user = update.effective_chat, update.effective_user
    key = make_key(chat.id, user.id)
    doc = await xp_collection.find_one({"_id": key})
    xp  = doc["xp"]    if doc else 0
    lvl = doc["nivel"] if doc else 0

    prefix  = f"{chat.id}_"
    mayores = await xp_collection.count_documents({
        "_id": {"$regex": f"^{prefix}"}, "xp": {"$gt": xp}
    })
    pos   = mayores + 1
    total = await xp_collection.count_documents({"_id": {"$regex": f"^{prefix}"}})
    falta = xp_para_subir(lvl) - xp if lvl < 100 else 0

    # barra de progreso estilo Pokémon (10 bloques)
    pct = 0 if lvl == 0 else (xp / xp_para_subir(lvl))
    pct = min(pct, 1.0)
    llenos = int(pct * 10)
    vacios = 10 - llenos
    bar = "▰" * llenos + "▱" * vacios

    await update.message.reply_text(
        f"{user.full_name}\n"
        f"Nivel {lvl}  {bar}\n"
        f"XP: {xp}/{xp_para_subir(lvl)}  ({falta} para siguiente)\n"
        f"Posición: {pos}/{total}"
    )

async def levtop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    cfg  = await config_collection.find_one({"_id": chat.id})
    if not cfg:
        return await update.message.reply_text("❌ No hay hilo configurado (/levsettema).")
    text, kb = await send_top_page(context.bot, chat.id, page=1)
    await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")

async def levtop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query; await q.answer()
    chat = q.message.chat
    page = int(q.data.split("_",1)[1])
    text, kb = await send_top_page(context.bot, chat.id, page)
    await q.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

async def levcomandos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmds = (
        "📜 Comandos disponibles:\n"
        "/start         — Instalar/configurar el bot\n"
        "/levsettema    — Define hilo de alertas (admin)\n"
        "/levalerta     — Define premio por nivel (admin)\n"
        "/levperfil     — Muestra XP, nivel, barra y posición\n"
        "/levtop        — Ranking XP con paginado\n"
        "/levcomandos   — Lista de comandos\n"
    )
    await update.message.reply_text(cmds)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or msg.from_user.is_bot: return
    chat, user = msg.chat, msg.from_user
    cfg = await config_collection.find_one({"_id": chat.id})
    if not cfg: return
    thread_id = cfg["thread_id"]

    key = make_key(chat.id, user.id)
    rec = await xp_collection.find_one({"_id": key})
    xp  = rec["xp"]    if rec else 0
    lvl = rec["nivel"] if rec else 0

    gan = random.randint(20,30) if msg.photo else random.randint(7,10)
    xp_nivel = xp + gan
    req      = xp_para_subir(lvl)

    # subir nivel estilo Pokémon
    if xp_nivel >= req and lvl < 100:
        nuevo_nivel = lvl + 1
        xp_nivel    = 0
        falta       = xp_para_subir(nuevo_nivel)
        mention     = f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
        # felicitación
        await context.bot.send_message(
            chat_id=chat.id,
            message_thread_id=thread_id,
            text=(
                f"🎉 <b>¡Felicidades!</b> {mention} subió al nivel <b>{nuevo_nivel}</b> 🚀\n\n"
                f"Ahora necesitas <b>{falta} XP</b> para nivel {nuevo_nivel+1}."
            ),
            parse_mode="HTML"
        )
        # mensaje de premio
        alt = await alerts_collection.find_one({"_id": f"{chat.id}_{nuevo_nivel}"})
        if alt:
            await context.bot.send_message(
                chat_id=chat.id,
                message_thread_id=thread_id,
                text=alt["message"]
            )
    else:
        nuevo_nivel = lvl

    await xp_collection.update_one(
        {"_id": key},
        {"$set": {"xp": xp_nivel, "nivel": nuevo_nivel}},
        upsert=True
    )

# ─── Main: webhook en Render ──────────────────────────────────────
def main():
    app = ApplicationBuilder()\
        .token(BOT_TOKEN)\
        .post_init(on_startup)\
        .build()

    # registramos handlers
    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("levsettema",  levsettema))
    app.add_handler(CommandHandler("levalerta",   levalerta))
    app.add_handler(CommandHandler("levperfil",   levperfil))
    app.add_handler(CommandHandler("levtop",      levtop))
    app.add_handler(CommandHandler("levcomandos", levcomandos))
    app.add_handler(CallbackQueryHandler(levtop_callback, pattern=r"^levtop_\d+$"))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    # arrancamos webhook
    port = int(os.getenv("PORT", "3000"))
    webhook_url = f"{BASE_URL}/{BOT_TOKEN}"
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        webhook_url=webhook_url
    )

if __name__ == "__main__":
    main()
