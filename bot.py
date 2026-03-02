"""
🕵️ Bot del Impostor para Telegram
Juego donde todos reciben la misma palabra excepto el impostor.
"""

import logging
import random
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes
)

# ── Configuración ──────────────────────────────────────────────
TOKEN = "8220277406:AAH3woDQ-SIv6PKuQoLMM5hKAsQoVgkQgWY"  # ← reemplaza con tu token de BotFather

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Palabras por categoría ─────────────────────────────────────
CATEGORIAS = {
    "🐾 Animales": [
        "León", "Delfín", "Pingüino", "Canguro", "Jirafa",
        "Pulpo", "Cocodrilo", "Flamenco", "Panda", "Tiburón",
        "Camello", "Murciélago", "Tortuga", "Lobo", "Oso polar",
    ],
    "⚽ Deportes": [
        "Fútbol", "Tenis", "Natación", "Boxeo", "Escalada",
        "Surf", "Golf", "Rugby", "Voleibol", "Esgrima",
        "Ciclismo", "Patinaje", "Arquería", "Polo", "Judo",
    ],
    "🌍 Lugares del mundo": [
        "Machu Picchu", "Times Square", "Coliseo", "Sahara",
        "Amazonas", "Venecia", "Tokio", "Islandia", "Maldivas",
        "Gran Cañón", "Siberia", "Dubái", "Patagonia", "Bangkok",
    ],
    "📦 Objetos cotidianos": [
        "Paraguas", "Tijeras", "Termómetro", "Candado", "Espejo",
        "Calculadora", "Maletín", "Percha", "Colador", "Lupa",
        "Destornillador", "Embudo", "Pinzas", "Brújula", "Reloj", "Cuaderno", "Mesa",
    ],
    "🎨 Colores": [
        "Turquesa", "Magenta", "Escarlata", "Índigo", "Negro",
        "Lavanda", "Carmesí", "Rosado", "Marfil", "Rojo",
        "Amarillo", "Violeta", "Dorado", "Plateado", "Coral", "Azul", "Blanco",
    ],
    "🌐 Países": [
        "Noruega", "Brasil", "Japón", "Marruecos", "Australia",
        "Canadá", "Tailandia", "Sudáfrica", "Argentina", "Grecia",
        "Egipto", "México", "India", "Portugal", "Colombia", "Chile",
    ],
}

# ── Base de datos ──────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect("impostor.db")
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS partidas (
            chat_id     INTEGER PRIMARY KEY,
            estado      TEXT DEFAULT 'esperando',
            categoria   TEXT,
            palabra     TEXT,
            impostor_id INTEGER,
            ronda       INTEGER DEFAULT 1,
            creador_id  INTEGER
        );
        CREATE TABLE IF NOT EXISTS jugadores (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id     INTEGER,
            user_id     INTEGER,
            username    TEXT,
            puntos      INTEGER DEFAULT 0,
            UNIQUE(chat_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS historial (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id     INTEGER,
            ganador     TEXT,
            palabra     TEXT,
            categoria   TEXT,
            fecha       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()

def get_conn():
    return sqlite3.connect("impostor.db")

# ── Helpers ────────────────────────────────────────────────────
def get_partida(chat_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM partidas WHERE chat_id=?", (chat_id,)
        ).fetchone()
    # devuelve: (chat_id, estado, categoria, palabra, impostor_id, ronda, creador_id)

def get_jugadores(chat_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT user_id, username, puntos FROM jugadores WHERE chat_id=? ORDER BY puntos DESC",
            (chat_id,)
        ).fetchall()

def upsert_jugador(chat_id, user_id, username):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO jugadores (chat_id, user_id, username) VALUES (?,?,?)",
            (chat_id, user_id, username)
        )
        conn.execute(
            "UPDATE jugadores SET username=? WHERE chat_id=? AND user_id=?",
            (username, chat_id, user_id)
        )

def sumar_puntos(chat_id, user_id, puntos):
    with get_conn() as conn:
        conn.execute(
            "UPDATE jugadores SET puntos = puntos + ? WHERE chat_id=? AND user_id=?",
            (puntos, chat_id, user_id)
        )

def nombre(user):
    return user.first_name or user.username or str(user.id)

def esc(text):
    """Escapa caracteres especiales de MarkdownV2."""
    chars = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in chars else c for c in str(text))


# ══════════════════════════════════════════════════════════════
# COMANDOS
# ══════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🕵️ *Bienvenido al Bot del Impostor\\!*\n\n"
        "El juego es simple:\n"
        "• Todos reciben la *misma palabra secreta*\n"
        "• Excepto el *impostor*, que no la sabe\n"
        "• Den pistas sin decirla directamente 🎭\n"
        "• El grupo vota quién es el impostor\n\n"
        "*Comandos:*\n"
        "`/nueva` — Crear una partida\n"
        "`/unirse` — Unirse a la partida\n"
        "`/iniciar` — Empezar \\(mín\\. 3 jugadores\\)\n"
        "`/votar` — Abrir votación final\n"
        "`/puntaje` — Ver marcador\n"
        "`/cancelar` — Cancelar partida",
        parse_mode="MarkdownV2"
    )


async def cmd_nueva(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user

    partida = get_partida(chat_id)
    if partida and partida[1] not in ("terminada",):
        await update.message.reply_text("⚠️ Ya hay una partida activa. Usa /cancelar primero.")
        return

    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO partidas (chat_id, estado, creador_id, ronda) VALUES (?,?,?,1)",
            (chat_id, "esperando", user.id)
        )
        conn.execute("DELETE FROM jugadores WHERE chat_id=?", (chat_id,))

    upsert_jugador(chat_id, user.id, nombre(user))

    keyboard = [[InlineKeyboardButton("✋ Unirse a la partida", callback_data="unirse")]]
    await update.message.reply_text(
        f"🎮 *{esc(nombre(user))} creó una nueva partida\\!*\n\n"
        "Pulsen el botón o usen /unirse para sumarse\\.\n"
        "Cuando estén listos, el creador usa /iniciar\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def cmd_unirse(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _unirse(update.effective_chat.id, update.effective_user, update.message.reply_text)

async def btn_unirse(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _unirse(update.effective_chat.id, update.effective_user, update.callback_query.message.reply_text)

async def _unirse(chat_id, user, reply_fn):
    partida = get_partida(chat_id)
    if not partida or partida[1] != "esperando":
        await reply_fn("⚠️ No hay ninguna partida abierta. Usa /nueva para crear una.")
        return

    upsert_jugador(chat_id, user.id, nombre(user))
    jugadores = get_jugadores(chat_id)
    lista = "\n".join(f"  {i+1}\\. {esc(j[1])}" for i, j in enumerate(jugadores))

    await reply_fn(
        f"✅ *{esc(nombre(user))} se unió\\!*\n\n"
        f"*Jugadores* \\({len(jugadores)}\\):\n{lista}",
        parse_mode="MarkdownV2"
    )


async def cmd_iniciar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    partida = get_partida(chat_id)

    if not partida or partida[1] != "esperando":
        await update.message.reply_text("⚠️ No hay partida en espera. Usa /nueva.")
        return
    if partida[6] != user.id:
        await update.message.reply_text("⚠️ Solo el creador puede iniciar la partida.")
        return

    jugadores = get_jugadores(chat_id)
    if len(jugadores) < 3:
        await update.message.reply_text(
            f"⚠️ Necesitas al menos 3 jugadores. Ahora hay {len(jugadores)}."
        )
        return

    keyboard = [
        [InlineKeyboardButton(cat, callback_data=f"cat:{cat}")]
        for cat in CATEGORIAS
    ]
    await update.message.reply_text(
        "🗂️ *Elige una categoría:*",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def btn_categoria(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    user = update.effective_user

    partida = get_partida(chat_id)
    if not partida or partida[6] != user.id:
        await query.answer("Solo el creador puede elegir la categoría.", show_alert=True)
        return

    categoria = query.data.split(":", 1)[1]
    palabra = random.choice(CATEGORIAS[categoria])
    jugadores = get_jugadores(chat_id)
    impostor = random.choice(jugadores)

    with get_conn() as conn:
        conn.execute(
            "UPDATE partidas SET estado='jugando', categoria=?, palabra=?, impostor_id=? WHERE chat_id=?",
            (categoria, palabra, impostor[0], chat_id)
        )

    await query.edit_message_text(
        f"✅ Categoría: *{esc(categoria)}*\n\n📩 Enviando palabras en privado\\.\\.\\.",
        parse_mode="MarkdownV2"
    )

    # Enviar palabra en privado
    fallidos = []
    for uid, uname, _ in jugadores:
        try:
            if uid == impostor[0]:
                msg = (
                    "🕵️ *¡Eres el IMPOSTOR\\!*\n\n"
                    f"Categoría: *{esc(categoria)}*\n\n"
                    "No conoces la palabra\\. Intenta descubrirla por las pistas de los demás\\. ¡No te atrapen\\! 🎭"
                )
            else:
                msg = (
                    f"🔑 Tu palabra secreta es:\n\n"
                    f"✨ *{esc(palabra)}* ✨\n\n"
                    f"Categoría: *{esc(categoria)}*\n\n"
                    "Da pistas sin decirla directamente\\. ¡Encuentra al impostor\\! 🕵️"
                )
            await ctx.bot.send_message(uid, msg, parse_mode="MarkdownV2")
        except Exception:
            fallidos.append(uname)

    lista = "\n".join(f"  • {esc(j[1])}" for j in jugadores)
    aviso = ""
    if fallidos:
        aviso = (
            "\n\n⚠️ No pude enviar mensaje a: "
            + ", ".join(esc(f) for f in fallidos)
            + "\n_Deben iniciar conversación con el bot primero_"
        )

    await ctx.bot.send_message(
        chat_id,
        f"🎮 *¡La partida comienza\\!*\n\n"
        f"Categoría: *{esc(categoria)}*\n\n"
        f"*Jugadores:*\n{lista}\n\n"
        "Cada jugador recibirá su palabra en privado\\.\n"
        "Comenten en el grupo y cuando estén listos usen /votar 🗳️"
        + aviso,
        parse_mode="MarkdownV2"
    )


async def cmd_votar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    partida = get_partida(chat_id)

    if not partida or partida[1] != "jugando":
        await update.message.reply_text("⚠️ No hay partida en curso.")
        return

    jugadores = get_jugadores(chat_id)
    keyboard = [
        [InlineKeyboardButton(f"🗳️ {j[1]}", callback_data=f"voto:{j[0]}")]
        for j in jugadores
    ]
    ctx.bot_data[f"votos_{chat_id}"] = {}

    await update.message.reply_text(
        "🗳️ *¿Quién es el impostor\\?*\n\n_Cada jugador debe votar:_",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def btn_voto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = update.effective_chat.id
    voter_id = query.from_user.id

    partida = get_partida(chat_id)
    if not partida or partida[1] != "jugando":
        await query.answer("La votación ya cerró.", show_alert=True)
        return

    jugadores = get_jugadores(chat_id)
    if not any(j[0] == voter_id for j in jugadores):
        await query.answer("No eres parte de esta partida.", show_alert=True)
        return

    votado_id = int(query.data.split(":")[1])
    votos = ctx.bot_data.setdefault(f"votos_{chat_id}", {})

    if voter_id in votos:
        await query.answer("Ya votaste.", show_alert=True)
        return

    votos[voter_id] = votado_id
    await query.answer("✅ ¡Voto registrado!")

    # Progreso
    faltantes = len(jugadores) - len(votos)
    await query.message.reply_text(
        f"✅ *{esc(query.from_user.first_name)}* votó\\. "
        + (f"Faltan *{faltantes}* votos\\." if faltantes > 0 else ""),
        parse_mode="MarkdownV2"
    )

    if len(votos) >= len(jugadores):
        await resolver_votacion(chat_id, ctx, partida, jugadores, votos, query.message)


async def resolver_votacion(chat_id, ctx, partida, jugadores, votos, message):
    # Contar votos
    conteo = {}
    for votado in votos.values():
        conteo[votado] = conteo.get(votado, 0) + 1

    eliminado_id = max(conteo, key=conteo.get)
    eliminado = next((j for j in jugadores if j[0] == eliminado_id), None)
    impostor_id = partida[4]
    impostor = next((j for j in jugadores if j[0] == impostor_id), None)
    palabra = partida[3]
    categoria = partida[2]

    if eliminado_id == impostor_id:
        ganador = "grupo"
        titulo = "🎉 ¡El grupo ganó\\!"
        desc = f"¡Encontraron al impostor *{esc(impostor[1])}*\\! \\+2 puntos para todos 🏆"
        for j in jugadores:
            if j[0] != impostor_id:
                sumar_puntos(chat_id, j[0], 2)
    else:
        ganador = "impostor"
        titulo = "🕵️ ¡El impostor ganó\\!"
        desc = (
            f"*{esc(impostor[1])}* era el impostor y no fue descubierto\\! \\+3 puntos 🏆\n"
            f"Votaron incorrectamente por *{esc(eliminado[1])}*"
        )
        sumar_puntos(chat_id, impostor_id, 3)

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO historial (chat_id, ganador, palabra, categoria) VALUES (?,?,?,?)",
            (chat_id, ganador, palabra, categoria)
        )
        conn.execute("UPDATE partidas SET estado='terminada' WHERE chat_id=?", (chat_id,))

    nombre_map = {j[0]: j[1] for j in jugadores}
    detalle_votos = "\n".join(
        f"  • {esc(nombre_map.get(v_from, '?'))} → {esc(nombre_map.get(v_to, '?'))}"
        for v_from, v_to in votos.items()
    )

    jugadores_act = get_jugadores(chat_id)
    puntaje = "\n".join(
        f"  {'🥇' if i==0 else '🥈' if i==1 else '🥉' if i==2 else f'{i+1}\\.'} "
        f"{esc(j[1])}: *{j[2]} pts*"
        for i, j in enumerate(jugadores_act)
    )

    await message.reply_text(
        f"{titulo}\n\n"
        f"{desc}\n\n"
        f"🔑 La palabra era: *{esc(palabra)}* \\({esc(categoria)}\\)\n\n"
        f"*Votos:*\n{detalle_votos}\n\n"
        f"*🏆 Puntaje:*\n{puntaje}\n\n"
        "_Usa /nueva para jugar otra ronda_",
        parse_mode="MarkdownV2"
    )


async def cmd_puntaje(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    jugadores = get_jugadores(chat_id)

    if not jugadores:
        await update.message.reply_text("📊 No hay puntajes aún\\. ¡Juega una partida primero\\!", parse_mode="MarkdownV2")
        return

    tabla = "\n".join(
        f"  {'🥇' if i==0 else '🥈' if i==1 else '🥉' if i==2 else f'{i+1}\\.'} "
        f"{esc(j[1])}: *{j[2]} pts*"
        for i, j in enumerate(jugadores)
    )
    await update.message.reply_text(
        f"🏆 *Puntaje del grupo:*\n\n{tabla}",
        parse_mode="MarkdownV2"
    )


async def cmd_cancelar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    with get_conn() as conn:
        conn.execute("UPDATE partidas SET estado='terminada' WHERE chat_id=?", (chat_id,))
    await update.message.reply_text("❌ Partida cancelada\\. Usa /nueva para empezar otra\\.", parse_mode="MarkdownV2")


# ── Main ───────────────────────────────────────────────────────
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("nueva",    cmd_nueva))
    app.add_handler(CommandHandler("unirse",   cmd_unirse))
    app.add_handler(CommandHandler("iniciar",  cmd_iniciar))
    app.add_handler(CommandHandler("votar",    cmd_votar))
    app.add_handler(CommandHandler("puntaje",  cmd_puntaje))
    app.add_handler(CommandHandler("cancelar", cmd_cancelar))

    app.add_handler(CallbackQueryHandler(btn_unirse,    pattern="^unirse$"))
    app.add_handler(CallbackQueryHandler(btn_categoria, pattern="^cat:"))
    app.add_handler(CallbackQueryHandler(btn_voto,      pattern="^voto:"))

    logger.info("🤖 Bot iniciado...")
    app.run_polling()

if __name__ == "__main__":
    main()
