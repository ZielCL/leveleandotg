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
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from telegram.error import Forbidden, BadRequest

# ─── Keep-Alive Server ────────────────────────────────────────────
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    def do_HEAD(self):
        self.send_response(200); self.end_headers()

threading.Thread(
    target=lambda: HTTPServer(("0.0.0.0", int(os.getenv("PORT", "3000"))), KeepAliveHandler).serve_forever(),
    daemon=True
).start()

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
xp_collection     = db.xp_usuarios    # XP total acumulado
db_monthly        = db.xp_mensual     # XP del mes actual
config_collection = db.temas_configurados
alerts_collection = db.level_alerts
stats_collection  = db.user_stats     # conteo top3 y meses pasados

from wcwidth import wcswidth

def corta_nombre(nombre, max_width=12):
    """Recorta nombres para que no sobrepasen el ancho visual en la tabla (ideal móvil)."""
    ancho = 0
    resultado = ""
    for char in nombre:
        char_width = wcswidth(char)
        if ancho + char_width > max_width - 1:
            return resultado + "…"
        resultado += char
        ancho += char_width
    return resultado




# ─── Helpers ──────────────────────────────────────────────────────
def xp_para_subir(nivel: int) -> int:
    """Calcula XP necesaria para subir del nivel n al n+1."""
    return 100 + 7 * (nivel - 1)

def make_key(chat_id: int, user_id: int) -> str:
    """Genera clave única chat_usuario."""
    return f"{chat_id}_{user_id}"

async def rollover_month(chat_id: int):
    """Cierra el mes: guarda top3 en stats y limpia XP mensual."""
    top3 = await db_monthly.find({"_id": {"$regex": f"^{chat_id}_"}}) \
                           .sort([("nivel", -1), ("xp", -1)]).limit(3).to_list(3)
    for doc in top3:
        uid = doc["_id"].split("_", 1)[1]
        await stats_collection.update_one(
            {"_id": f"{chat_id}_{uid}"}, {"$inc": {"top3_count": 1}}, upsert=True
        )
    cfg = await config_collection.find_one({"_id": chat_id}) or {}
    meses = cfg.get("meses_pasados", 0) + 1
    await config_collection.update_one(
        {"_id": chat_id},
        {"$set": {"meses_pasados": meses, "last_month": datetime.utcnow().month}},
        upsert=True
    )
    await db_monthly.delete_many({"_id": {"$regex": f"^{chat_id}_"}})

async def ensure_monthly_state(chat_id: int):
    """Verifica si cambió el mes y, de ser así, aplica rollover."""
    now = datetime.utcnow()
    cfg = await config_collection.find_one({"_id": chat_id})
    if not cfg or cfg.get("last_month") != now.month:
        await rollover_month(chat_id)

async def send_top_page(bot, chat_id: int, page: int, collec):
    """
    Genera texto y botones para paginar ranking de una colección.
    Tabla móvil: compacta y que no se desborda con nombres raros.
    """
    prefix = f"{chat_id}_"
    total = await collec.count_documents({"_id": {"$regex": f"^{prefix}"}})
    pages = max(1, math.ceil(total / 10))
    page = max(1, min(page, pages))
    docs = await collec.find({"_id": {"$regex": f"^{prefix}"}}) \
        .sort([("nivel", -1), ("xp", -1)]) \
        .skip((page-1)*10).limit(10).to_list(10)

    lines = []
    lines.append(f"🏆 XP Ranking (página {page}/{pages}):")
    lines.append(" #   Usuario        Nv XP   Sig.")
    lines.append("────────────────────────────────────")
    for idx, doc in enumerate(docs, start=(page-1)*10+1):
        uid = int(doc["_id"].split("_", 1)[1])
        try:
            name = (await bot.get_chat_member(chat_id, uid)).user.full_name
        except:
            name = f"User {uid}"
        # Top 3 con emoji, luego solo número
        if idx == 1:
            pos_emoji = "🥇"
        elif idx == 2:
            pos_emoji = "🥈"
        elif idx == 3:
            pos_emoji = "🥉"
        else:
            pos_emoji = f"{idx:>2}"

        # Nombre ajustado para móvil
        name_fmt = corta_nombre(name, max_width=12)
        nivel_fmt = str(doc.get('nivel', 0)).rjust(2)
        xp_fmt = str(doc.get('xp', 0)).rjust(3)
        next_xp = xp_para_subir(doc.get('nivel', 0))
        next_fmt = str(next_xp).rjust(4)
        # Compacta para móvil
        lines.append(f"{pos_emoji:<2} | {name_fmt:<12} |{nivel_fmt}|{xp_fmt}|{next_fmt}")

    text = "```\n" + "\n".join(lines) + "\n```"
    btns = []
    if page > 1:
        btns.append(InlineKeyboardButton("◀️", callback_data=f"top_{page-1}_{collec.name}"))
    if page < pages:
        btns.append(InlineKeyboardButton("▶️", callback_data=f"top_{page+1}_{collec.name}"))
    return text, InlineKeyboardMarkup([btns]) if btns else None

async def get_rank_and_total(collec, chat_id, nivel, xp):
    """Obtiene la posición del usuario dado su nivel y xp."""
    prefix = f"{chat_id}_"
    higher = await collec.count_documents({
        "_id": {"$regex": f"^{prefix}"},
        "$or": [
            {"nivel": {"$gt": nivel}},
            {"nivel": nivel, "xp": {"$gt": xp}},
        ]
    })
    total = await collec.count_documents({"_id": {"$regex": f"^{prefix}"}})
    return higher+1, total

# ─── Startup ──────────────────────────────────────────────────────
async def on_startup(app):
    logger.info("✅ Bot arrancando")
    await client.admin.command("ping")
    await app.bot.delete_webhook(drop_pending_updates=True)
    await app.bot.set_my_commands([
        BotCommand("start",           "💬 Muestra instrucciones de configuración"),
        BotCommand("levsettema",      "🧵 Define hilo de alertas (admins)"),
        BotCommand("levalerta",       "🎁 Define mensaje personalizado por nivel (admins)"),
        BotCommand("levalertalist",   "📋 Lista alertas configuradas (admins)"),
        BotCommand("levperfil",       "👤 Perfil interactivo mensual/acumulado"),
        BotCommand("levtop",          "📈 Top XP del mes"),
        BotCommand("levtopacumulado", "📊 Top XP acumulado"),
        BotCommand("levcomandos",     "📜 Lista de todos los comandos"),
        BotCommand("restarlev",       "🔻 Resta niveles a un usuario (admin)"),
    ])
    # Avisar operatividad solo en hilos si corresponde
    async for cfg in config_collection.find({}):
        chat_id = cfg["_id"]
        thread_id = cfg.get("thread_id")
        try:
            await app.bot.send_message(chat_id, "🤖 LeveleandoTG activo en el grupo.")
            chat = await app.bot.get_chat(chat_id)
            if thread_id and getattr(chat, "is_forum", False):
                await app.bot.send_message(
                    chat_id,
                    "🎉 Alertas habilitadas en este hilo.",
                    message_thread_id=thread_id
                )
        except Forbidden:
            await config_collection.delete_one({"_id": chat_id})

# ─── Comando /restarlev ──────────────────────────────────────────
async def restarlev(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    admin = update.effective_user

    # Solo admin o creador puede usar el comando
    m = await context.bot.get_chat_member(chat.id, admin.id)
    if m.status not in ("administrator", "creator"):
        return await update.message.reply_text("❌ Solo admins pueden usar este comando.")

    # Determinar usuario objetivo
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        try:
            cantidad = int(context.args[0])
        except (IndexError, ValueError):
            return await update.message.reply_text("❌ Uso correcto: responde a un mensaje y escribe /restarlev <cantidad>")
    else:
        if not context.args or len(context.args) < 2:
            return await update.message.reply_text("❌ Uso correcto: /restarlev @usuario <cantidad>")
        username = context.args[0]
        if not username.startswith("@"):
            return await update.message.reply_text("❌ Debes mencionar con @usuario.")
        username = username[1:]
        # Buscar en miembros del grupo (solo admins y recientes, mejor esfuerzo)
        target_user = None
        try:
            async for member in context.bot.get_chat_administrators(chat.id):
                if member.user.username and member.user.username.lower() == username.lower():
                    target_user = member.user
                    break
            if not target_user:
                chat_members = await context.bot.get_chat(chat.id)
                if hasattr(chat_members, "username") and chat_members.username and chat_members.username.lower() == username.lower():
                    target_user = chat_members
            if not target_user:
                return await update.message.reply_text("❌ Usuario no encontrado. Usa mejor respondiendo a un mensaje.")
        except Exception:
            return await update.message.reply_text("❌ No pude buscar el usuario. Usa mejor respondiendo a un mensaje.")
        try:
            cantidad = int(context.args[1])
        except (IndexError, ValueError):
            return await update.message.reply_text("❌ Uso correcto: /restarlev @usuario <cantidad>")

    if cantidad < 1:
        return await update.message.reply_text("❌ La cantidad debe ser mayor a 0.")

    key = make_key(chat.id, target_user.id)
    rec_total = await xp_collection.find_one({"_id": key}) or {"nivel": 1, "xp": 0}
    rec_mes   = await db_monthly.find_one({"_id": key}) or {"nivel": 1, "xp": 0}
    old_total = rec_total.get("nivel", 1)
    old_mes = rec_mes.get("nivel", 1)

    nuevo_total = max(1, old_total - cantidad)
    nuevo_mes = max(1, old_mes - cantidad)

    await xp_collection.update_one({"_id": key}, {"$set": {"nivel": nuevo_total, "xp": 0}}, upsert=True)
    await db_monthly.update_one({"_id": key}, {"$set": {"nivel": nuevo_mes, "xp": 0}}, upsert=True)

    mention = f'<a href="tg://user?id={target_user.id}">{target_user.full_name}</a>'
    await update.message.reply_text(
        f"🔻 {mention} ahora tiene nivel <b>{nuevo_total}</b> (acumulado), <b>{nuevo_mes}</b> (mensual).",
        parse_mode=ParseMode.HTML
    )

# ─── Comandos originales y principales ───────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 * ¡Hola! Soy tu bot LeveleandoTG*:\n"
        "Para habilitarme en tu grupo:\n"
        "Añádeme como admin y luego:\n"
        "• /levsettema <thread_id>: define el hilo para alertas\n"
        "• /levalerta <nivel> <mensaje>: Define mensaje personalizado por nivel\n"
        "• /levperfil: ve tu perfil mensual/acumulado\n"
        "• /levtop: top 10 del mes\n"
        "• /levtopacumulado: top 10 acumulado\n\n"
        "Escribe /levcomandos para ver todos los comandos.",
        parse_mode="Markdown"
    )

async def levsettema(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat, user = update.effective_chat, update.effective_user
    if chat.type not in ("group", "supergroup"):
        return
    m = await context.bot.get_chat_member(chat.id, user.id)
    if m.status not in ("administrator", "creator"):
        return await update.message.reply_text("❌ Solo admins pueden usar este comando.")
    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text(
            "❌ Para usar: /levsettema <thread_id> • En Telegram Desktop/Web, copia el enlace de un mensaje en el tema donde quieras activar esta alerta → el número antes del segundo / es el thread_id."
        )
    thread_id = int(context.args[0])
    await config_collection.update_one(
        {"_id": chat.id},
        {"$set": {"thread_id": thread_id}},
        upsert=True
    )
    await update.message.reply_text(f"✅ Hilo de alertas configurado: {thread_id}", parse_mode="Markdown")

async def levalerta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat, user = update.effective_chat, update.effective_user
    m = await context.bot.get_chat_member(chat.id, user.id)
    if m.status not in ("administrator", "creator"):
        return await update.message.reply_text("❌ Solo admins pueden usar este comando.")
    if len(context.args) < 2 or not context.args[0].isdigit():
        return await update.message.reply_text("❌ Uso: /levalerta <nivel> <mensaje>")
    nivel = int(context.args[0])
    mensaje = " ".join(context.args[1:])
    await alerts_collection.update_one(
        {"_id": f"{chat.id}_{nivel}"},
        {"$set": {"message": mensaje}},
        upsert=True
    )
    await update.message.reply_text(f"✅ Premio guardado para nivel *{nivel}*", parse_mode="Markdown")

async def levalertalist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    m = await context.bot.get_chat_member(chat.id, update.effective_user.id)
    if m.status not in ("administrator", "creator"):
        return await update.message.reply_text("❌ Solo admins pueden usar este comando.")
    docs = await alerts_collection.find({"_id": {"$regex": f"^{chat.id}_"}}).to_list(None)
    if not docs:
        return await update.message.reply_text("🚫 No hay alertas configuradas.")
    text = "📋 *Alertas configuradas:*\n"
    for doc in docs:
        _, lvl = doc["_id"].split("_", 1)
        text += f"• Nivel {lvl}: _{doc['message']}_\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def levperfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat, user = update.effective_chat, update.effective_user
    await ensure_monthly_state(chat.id)
    key = make_key(chat.id, user.id)
    rec = await db_monthly.find_one({"_id": key}) or {}
    xp_m, lvl_m = rec.get("xp", 0), rec.get("nivel", 1)
    pos_m, total_m = await get_rank_and_total(db_monthly, chat.id, lvl_m, xp_m)
    falta = xp_para_subir(lvl_m) - xp_m
    text = (
        f"*{user.full_name}*\n"
        f"• Nivel: *{lvl_m}*  Posición: *{pos_m}/{total_m}*\n\n"
        f"• XP: *{xp_m}*  XP para siguiente nivel: *{falta}*"
    )
    btn = InlineKeyboardButton("➡️ Acumulado", callback_data="perfil_acum")
    await update.message.reply_text(text, parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup([[btn]]))

async def perfil_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    chat, user = update.effective_chat, update.effective_user

    if data == "perfil_acum":
        key = make_key(chat.id, user.id)
        rec = await xp_collection.find_one({"_id": key}) or {}
        xp_a, lvl_a = rec.get("xp", 0), rec.get("nivel", 1)
        pos_a, total_a = await get_rank_and_total(xp_collection, chat.id, lvl_a, xp_a)
        stats = await stats_collection.find_one({"_id": key}) or {}
        top3c = stats.get("top3_count", 0)
        cfg = await config_collection.find_one({"_id": chat.id}) or {}
        meses = cfg.get("meses_pasados", 0)
        text = (
            f"*{user.full_name}* _(acumulado)_\n"
            f"• Nivel total: *{lvl_a}*  Posición: *{pos_a}/{total_a}*\n"
            f"• Veces en top 3: *{top3c}/{meses}*"
        )
        btn = InlineKeyboardButton("⬅️ Mensual", callback_data="perfil_mes")
    else:
        await ensure_monthly_state(chat.id)
        key = make_key(chat.id, user.id)
        rec = await db_monthly.find_one({"_id": key}) or {}
        xp_m, lvl_m = rec.get("xp", 0), rec.get("nivel", 1)
        pos_m, total_m = await get_rank_and_total(db_monthly, chat.id, lvl_m, xp_m)
        falta = xp_para_subir(lvl_m) - xp_m
        text = (
            f"*{user.full_name}* _(mensual)_\n"
            f"• Nivel: *{lvl_m}*  Posición: *{pos_m}/{total_m}*\n"
            f"• XP: *{xp_m}*  XP siguiente: *{falta}*"
        )
        btn = InlineKeyboardButton("➡️ Acumulado", callback_data="perfil_acum")

    try:
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn]])
        )
    except (Forbidden, BadRequest):
        pass

async def levtop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    await ensure_monthly_state(chat.id)
    text, kb = await send_top_page(context.bot, chat.id, 1, db_monthly)
    await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

async def levtopacumulado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    text, kb = await send_top_page(context.bot, chat.id, 1, xp_collection)
    await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

async def top_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = update.callback_query.data.split("_")
    page = int(parts[1])
    col_name = "_".join(parts[2:])
    collec = xp_collection if col_name == "xp_usuarios" else db_monthly
    text, kb = await send_top_page(context.bot, update.effective_chat.id, page, collec)
    await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

async def levcomandos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = [
        "/start — guía rápida de configuración",
        "/levsettema — define hilo de alertas (admin)",
        "/levalerta — Define mensaje personalizado por nivel (admin)",
        "/levalertalist — muestra alertas creadas (admin)",
        "/levperfil — perfil mensual y botones",
        "/levtop — top 10 del mes",
        "/levtopacumulado — top 10 total",
        "/levcomandos — lista de comandos",
        "/restarlev — restar niveles a un usuario (admin)"
    ]
    await update.message.reply_text("📜 *Comandos disponibles:*\n" + "\n".join(lines), parse_mode="Markdown")

# Cambia esto por TU USER ID de Telegram (entero)
MI_USER_ID = 1111798714  # <-- reemplaza con tu ID real

async def reiniciarmes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if user.id != MI_USER_ID:
        return await update.message.reply_text("⛔ No tienes permisos para esto.")

    await db_monthly.delete_many({"_id": {"$regex": f"^{chat.id}_"}})
    await config_collection.update_one(
        {"_id": chat.id},
        {"$set": {"last_month": datetime.utcnow().month}},
        upsert=True
    )
    await update.message.reply_text(
        "✅ El ranking mensual fue REINICIADO solo para este grupo.\n(No afecta el ranking acumulado)"
    )


# ─── Mensajería y XP ─────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or msg.from_user.is_bot:
        return
    chat, user = msg.chat, msg.from_user
    cfg = await config_collection.find_one({"_id": chat.id})
    if not cfg:
        return

    key = make_key(chat.id, user.id)
    rec = await xp_collection.find_one({"_id": key})
    rec_mes = await db_monthly.find_one({"_id": key})

    if rec is None:
        await xp_collection.insert_one({"_id": key, "xp": 0, "nivel": 1})
        await db_monthly.insert_one({"_id": key, "xp": 0, "nivel": 1})
        xp, lvl = 0, 1
        xp_m, lvl_m = 0, 1
    elif rec_mes is None:
        await db_monthly.insert_one({"_id": key, "xp": 0, "nivel": 1})
        xp = rec.get("xp", 0)
        lvl = rec.get("nivel", 1)
        xp_m, lvl_m = 0, 1
    else:
        xp = rec.get("xp", 0)
        lvl = rec.get("nivel", 1)
        xp_m = rec_mes.get("xp", 0)
        lvl_m = rec_mes.get("nivel", 1)

    gan = random.randint(11, 16) if msg.photo else random.randint(7, 10)
    xp_nuevo = xp + gan
    xp_m_nuevo = xp_m + gan
    req = xp_para_subir(lvl)
    req_m = xp_para_subir(lvl_m)

    # Guarda niveles anteriores para comparar
    old_lvl = lvl
    old_lvl_m = lvl_m

    # Subida de nivel acumulado
    if xp_nuevo >= req and lvl < 100:
        lvl += 1
        xp_nuevo = 0
    # Subida de nivel mensual
    if xp_m_nuevo >= req_m and lvl_m < 100:
        lvl_m += 1
        xp_m_nuevo = 0

    await xp_collection.update_one(
        {"_id": key}, {"$set": {"xp": xp_nuevo, "nivel": lvl}}, upsert=True
    )
    await db_monthly.update_one(
        {"_id": key}, {"$set": {"xp": xp_m_nuevo, "nivel": lvl_m}}, upsert=True
    )

    # Chequear si subió de nivel, solo mostrar uno: prioridad mensual
    subio_nivel_mensual = (xp_m_nuevo == 0 and lvl_m > old_lvl_m)
    subio_nivel_acumulado = (xp_nuevo == 0 and lvl > old_lvl)

    msg_subida = None
    alt = None
    tipo = None
    if subio_nivel_mensual:
        tipo = "mensual"
        nivel_msg = lvl_m
        falta = xp_para_subir(lvl_m)
        alt = await alerts_collection.find_one({"_id": f"{chat.id}_{lvl_m}"})
    elif subio_nivel_acumulado:
        tipo = "acumulado"
        nivel_msg = lvl
        falta = xp_para_subir(lvl)
        alt = await alerts_collection.find_one({"_id": f"{chat.id}_{lvl}"})

    if tipo:
        mention = f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
        msg_subida = (
            f"🎉 <b>¡Felicidades!</b> {mention} alcanzó nivel <b>{nivel_msg}</b> <b>{tipo}</b>!\n"
            f"XP necesaria para siguiente nivel: <b>{falta}</b>"
        )
        chat_info = await context.bot.get_chat(chat.id)
        try:
            if cfg.get("thread_id") and getattr(chat_info, "is_forum", False):
                await context.bot.send_message(
                    chat_id=chat.id,
                    message_thread_id=cfg["thread_id"],
                    text=msg_subida,
                    parse_mode="HTML"
                )
                if alt and alt.get("message"):
                    await context.bot.send_message(
                        chat_id=chat.id,
                        message_thread_id=cfg["thread_id"],
                        text=alt["message"]
                    )
            else:
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=msg_subida,
                    parse_mode="HTML"
                )
                if alt and alt.get("message"):
                    await context.bot.send_message(
                        chat_id=chat.id,
                        text=alt["message"]
                    )
        except BadRequest as e:
            logger.warning(f"Error enviando alerta de nivel: {e}")


    # Si quieres, puedes poner "elif subio_acumulado:" para enviar solo si sube el acumulado (pero normalmente no es necesario).


# ─── MAIN ────────────────────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(on_startup).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("levsettema", levsettema))
    app.add_handler(CommandHandler("levalerta", levalerta))
    app.add_handler(CommandHandler("levalertalist", levalertalist))
    app.add_handler(CommandHandler("levperfil", levperfil))
    app.add_handler(CallbackQueryHandler(perfil_callback, pattern=r"^perfil_"))
    app.add_handler(CommandHandler("levtop", levtop))
    app.add_handler(CommandHandler("levtopacumulado", levtopacumulado))
    app.add_handler(CallbackQueryHandler(top_callback, pattern=r"^top_"))
    app.add_handler(CommandHandler("levcomandos", levcomandos))
    app.add_handler(CommandHandler("restarlev", restarlev))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    app.add_handler(CommandHandler("reiniciarmes", reiniciarmes))
    app.run_polling()
    

if __name__ == "__main__":
    main()
