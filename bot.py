"""
🕵️ Bot del Impostor para Telegram
Juego donde todos reciben la misma palabra excepto el impostor.
Soporte de idiomas: Español / English
"""

import asyncio
import logging
import random
import sqlite3
import anthropic
import io
import os
import urllib.request
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime

# ── Fuentes con cobertura unicode completa ──────────────────────

def _get_font_dir():
    """Retorna directorio escribible para fuentes: /data/fonts o /tmp/fonts."""
    for d in ["/data/fonts", "/tmp/fonts"]:
        try:
            os.makedirs(d, exist_ok=True)
            # Verificar que es escribible
            test = os.path.join(d, ".write_test")
            open(test, "w").close()
            os.remove(test)
            return d
        except Exception:
            continue
    return "/tmp"

_FONT_DIR     = _get_font_dir()
_FONT_REGULAR = f"{_FONT_DIR}/NotoSans-Regular.ttf"
_FONT_BOLD    = f"{_FONT_DIR}/NotoSans-Bold.ttf"
_FONT_UNIFONT    = f"{_FONT_DIR}/unifont.otf"
_FONT_FREESERIF_DL = f"{_FONT_DIR}/FreeSerif.ttf"
_FONT_FREESANS_DL  = f"{_FONT_DIR}/FreeSans.ttf"

# Fuentes del sistema (Ubuntu/Debian — disponibles en Render si se instalan)
_FONT_UNIFONT_SYS  = "/usr/share/fonts/opentype/unifont/unifont.otf"
_FONT_FREESERIF    = "/usr/share/fonts/truetype/freefont/FreeSerif.ttf"
_FONT_FREESANS     = "/usr/share/fonts/truetype/freefont/FreeSans.ttf"
_FONT_FREESANSBOLD = "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
_FONT_DEJAVUSANS   = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_FONT_DEJAVUBOLD   = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_FONT_CJK_REGULAR  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
_FONT_CJK_BOLD     = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

# Prioridad de fuentes para nombres de usuario
# Unifont cubre BMP (runas, syllabics, coreano, etc.)
# FreeSerif cubre SMP matemático (U+1D400-U+1D7FF)
# Ambas son necesarias para cobertura completa
# IMPORTANTE: fuentes vectoriales (DejaVu, NotoSans) van PRIMERO.
# Unifont es bitmap y solo funciona bien a 16px; va al final como
# ultimo recurso para caracteres exoticos no cubiertos por vectoriales.
_RENDER_FONT_PRIORITY = [
    _FONT_DEJAVUSANS,      # vectorial: Latin/Griego/Cirilico/Arabe basico
    _FONT_REGULAR,         # NotoSans vectorial
    _FONT_FREESANS,        # sistema (si disponible)
    _FONT_FREESANS_DL,     # descargado
    _FONT_CJK_REGULAR,     # CJK/coreano
    _FONT_FREESERIF,       # SMP math (sistema)
    _FONT_FREESERIF_DL,    # SMP math (descargado)
    _FONT_UNIFONT_SYS,     # Unifont sistema - exoticos BMP
    _FONT_UNIFONT,         # Unifont descargado - ultimo recurso
]
_RENDER_FONT_PRIORITY_BOLD = [
    _FONT_DEJAVUBOLD,
    _FONT_BOLD,
    _FONT_FREESANSBOLD,
    _FONT_CJK_BOLD,
    _FONT_UNIFONT_SYS,
    _FONT_UNIFONT,
]

# Cache: (path, size) → ImageFont
_font_cache: dict = {}
# Cache: codepoint → path con el glifo
_codepoint_to_path: dict = {}
# Cache de cmaps por path: path → set de codepoints
_font_cmaps: dict = {}

def _get_font_cmap(path: str) -> set:
    """Retorna el conjunto de codepoints soportados por la fuente (via fonttools)."""
    if path in _font_cmaps:
        return _font_cmaps[path]
    cmap = set()
    try:
        from fontTools.ttLib import TTFont as _TTFont
        tt = _TTFont(path, fontNumber=0)
        best = tt.getBestCmap()
        if best:
            cmap = set(best.keys())
        tt.close()
    except Exception:
        pass
    _font_cmaps[path] = cmap
    return cmap

def _path_has_glyph(path: str, char: str) -> bool:
    """Verifica via cmap si la fuente tiene el glifo para el carácter."""
    cmap = _get_font_cmap(path)
    if cmap:
        return ord(char) in cmap
    # Fallback si fonttools no está disponible: comparación pixel
    f = _load(path, 22)
    if not f:
        return False
    try:
        _NOTDEF_REF = "\uE000"
        img_c = Image.new("L", (30, 30), 0)
        img_r = Image.new("L", (30, 30), 0)
        ImageDraw.Draw(img_c).text((2, 2), char, font=f, fill=255)
        ImageDraw.Draw(img_r).text((2, 2), _NOTDEF_REF, font=f, fill=255)
        return img_c.tobytes() != img_r.tobytes()
    except Exception:
        return False

def _load(path: str, size: int):
    """Carga fuente con cache. Retorna None si falla."""
    key = (path, size)
    if key in _font_cache:
        return _font_cache[key]
    result = None
    if path and os.path.exists(path) and os.path.getsize(path) > 10_000:
        try:
            result = ImageFont.truetype(path, size)
        except Exception:
            pass
    _font_cache[key] = result
    return result

def _best_font_for_char(char: str, size: int):
    """Encuentra la mejor fuente disponible para un carácter específico."""
    cp = ord(char)
    # Cache por codepoint (el path es independiente del size)
    if cp not in _codepoint_to_path:
        best_path = None
        for path in _RENDER_FONT_PRIORITY:
            if not (path and os.path.exists(path) and os.path.getsize(path) > 10_000):
                continue
            if _path_has_glyph(path, char):
                best_path = path
                break
        _codepoint_to_path[cp] = best_path

    path = _codepoint_to_path[cp]
    if path:
        f = _load(path, size)
        if f:
            return f
    # Fallback: primera fuente cargable
    for p in _RENDER_FONT_PRIORITY:
        f = _load(p, size)
        if f:
            return f
    return ImageFont.load_default()

def _get_font(size: int, bold: bool = False):
    """Fuente principal para headers/labels."""
    priority = _RENDER_FONT_PRIORITY_BOLD if bold else _RENDER_FONT_PRIORITY
    for path in priority:
        f = _load(path, size)
        if f:
            return f
    return ImageFont.load_default()

def draw_text_smart(draw, pos, text: str, size: int, fill):
    """Dibuja texto eligiendo automáticamente la mejor fuente para cada carácter."""
    x, y = pos
    for char in text:
        if char == " ":
            x += size // 3
            continue
        font = _best_font_for_char(char, size)
        bbox = draw.textbbox((0, 0), char, font=font)
        draw.text((x, y), char, font=font, fill=fill)
        x += max(bbox[2] - bbox[0], 2)
    return x

def _init_fonts():
    """Descarga fuentes necesarias y loguea el estado del sistema de fuentes."""
    _log = logging.getLogger(__name__)
    _log.info(f"[FONTS] Directorio de fuentes: {_FONT_DIR}")

    # Descargar fuentes si no existen en sistema ni en cache
    # Unifont  → BMP completo (runas, syllabics, coreano, etc.)
    # FreeSerif → SMP math alphanumeric (𝓩 𝙄 etc.)
    DOWNLOAD_LIST = [
        (_FONT_UNIFONT, [
            "https://unifoundry.com/pub/unifont/unifont-15.1.05/font-builds/unifont-15.1.05.otf",
            "https://github.com/nicowillis/fonts/raw/master/Unifont.ttf",
        ]),
        (_FONT_FREESERIF_DL, [
            "https://cdn.jsdelivr.net/gh/opensourcedesign/fonts@master/gnu-freefont_freefont-20120503/FreeSerif.ttf",
            "https://noto-website-2.storage.googleapis.com/pkgs/NotoSerif-unhinted.zip",
        ]),
        (_FONT_FREESANS_DL, [
            "https://cdn.jsdelivr.net/gh/opensourcedesign/fonts@master/gnu-freefont_freefont-20120503/FreeSans.ttf",
        ]),
        (_FONT_REGULAR, [
            "https://cdn.jsdelivr.net/gh/googlefonts/noto-fonts@main/hinted/ttf/NotoSans/NotoSans-Regular.ttf",
            "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf",
        ]),
        (_FONT_BOLD, [
            "https://cdn.jsdelivr.net/gh/googlefonts/noto-fonts@main/hinted/ttf/NotoSans/NotoSans-Bold.ttf",
            "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Bold.ttf",
        ]),
    ]
    for dest, urls in DOWNLOAD_LIST:
        if os.path.exists(dest) and os.path.getsize(dest) > 50_000:
            _log.info(f"[FONTS] OK (cache): {dest} ({os.path.getsize(dest)//1024}KB)")
            continue
        for url in urls:
            try:
                _log.info(f"[FONTS] Descargando: {url}")
                urllib.request.urlretrieve(url, dest)
                size = os.path.getsize(dest)
                if size > 50_000:
                    _log.info(f"[FONTS] ✅ Descargado: {dest} ({size//1024}KB)")
                    break
                os.remove(dest)
            except Exception as e:
                _log.warning(f"[FONTS] Falló {url}: {e}")
        else:
            _log.warning(f"[FONTS] No se pudo descargar: {os.path.basename(dest)}")

    # Loguear estado final de todas las fuentes
    all_paths = _RENDER_FONT_PRIORITY + _RENDER_FONT_PRIORITY_BOLD
    for p in dict.fromkeys(all_paths):  # deduplicar
        exists = p and os.path.exists(p)
        size_kb = os.path.getsize(p)//1024 if exists else 0
        _log.info(f"[FONTS] {'✅' if exists else '❌'} {os.path.basename(p) if p else '?'} ({size_kb}KB)")

    # Pre-calentar cmap de las fuentes disponibles
    for p in _RENDER_FONT_PRIORITY:
        if p and os.path.exists(p) and os.path.getsize(p) > 10_000:
            cmap = _get_font_cmap(p)
            _log.info(f"[FONTS] cmap {os.path.basename(p)}: {len(cmap)} codepoints")

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Conflict
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

TOKEN = os.environ.get("BOT_TOKEN")
MAX_JUGADORES = 8

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# TEXTOS EN AMBOS IDIOMAS
# ══════════════════════════════════════════════════════════════

TEXTOS = {
    "es": {
        # cmd_start
        "start": (
            "🕵️ *¡Bienvenido al Bot del Impostor\\!*\n\n"
            "El juego es simple:\n"
            "• Todos reciben la *misma palabra secreta*\n"
            "• Excepto el/los *impostores*, que no la saben\n"
            "• Den pistas sin decirla directamente 🎭\n"
            "• El grupo vota para eliminar jugadores por rondas\n\n"
            "*Comandos:*\n"
            "`/playimpostor` — Crear una partida\n"
            "`/join` — Unirse a la partida\n"
            "`/vote` — Abrir votación \\(solo el creador\\)\n"
            "`/howtoplay` — Cómo se juega\n"
            "`/score` — Ver marcador\n"
            "`/resetimpostor` — Resetear puntajes\n"
            "`/language` — Cambiar idioma\n"
            "`/cancel` — Cancelar partida"
        ),
        # cmd_como_jugar
        "comojugar": (
            "🕵️ *¿Cómo se juega El Impostor?*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "*📋 Objetivo*\n"
            "El grupo debe eliminar a todos los impostores\\. "
            "Los impostores deben pasar desapercibidos o adivinar la palabra secreta\\.\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "*🎮 Pasos del juego*\n\n"
            "*0\\. Iniciar el bot en privado*\n"
            "Debes ingresar a @impostortg\\_bot y apretar el botón de la parte inferior que dice `Iniciar`, luego en comandos usa `/howtoplay` para aprender sobre el bot\\.\n\n"
            "*1\\. Crear la partida*\n"
            "Alguien usa `/playimpostor` y los demás se unen con `/join` o el botón\\.\n\n"
            "*2\\. Iniciar*\n"
            "Con mínimo 3 jugadores, el creador elige una categoría y pulsa *¡Iniciar partida\\!*\n\n"
            "*3\\. Palabras secretas*\n"
            "El bot envía un mensaje privado a cada jugador:\n"
            "• Los jugadores normales reciben la *palabra secreta*\n"
            "• El/los impostor\\(es\\) NO reciben la palabra, solo la categoría 🎭\n\n"
            "*4\\. Dar pistas*\n"
            "Siguiendo el orden aleatorio, cada jugador da *una pista* sobre la palabra\\. "
            "El impostor debe inventar una pista convincente sin saber la palabra\\.\n\n"
            "*5\\. Votar*\n"
            "Cuando todos hayan dado su pista, el creador abre la votación\\. "
            "Solo los jugadores *vivos* votan\\. El más votado queda eliminado\\.\n\n"
            "*6\\. Revelación y nueva ronda*\n"
            "Se revela si el eliminado era impostor o inocente\\. "
            "Si quedan jugadores, se muestra un nuevo orden y continúa el juego\\.\n\n"
            "*7\\. Último intento del impostor*\n"
            "Si el grupo vota a un impostor, este tiene *una última oportunidad*: "
            "adivinar la palabra escribiéndola en el chat\\. "
            "Si la adivina, *todos los impostores ganan*\\.\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "*🏆 ¿Quién gana?*\n\n"
            "🎉 *Grupo gana* si:\n"
            "  • Eliminan a todos los impostores\n\n"
            "🕵️ *Impostor\\(es\\) gana\\(n\\)* si:\n"
            "  • Solo queda 1 inocente junto a un impostor\n"
            "  • Un impostor adivina la palabra al ser votado\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "*👥 Impostores según jugadores*\n"
            "  • 3\\-4 jugadores → 1 impostor\n"
            "  • 5\\-6 jugadores → 1 a 3 impostores \\(al azar\\)\n"
            "  • 7\\+ jugadores → 2 a 3 impostores \\(al azar\\)\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "*📌 Comandos*\n"
            "`/playimpostor` — Crear partida\n"
            "`/join` — Unirse a la partida\n"
            "`/vote` — Abrir votación \\(creador\\)\n"
            "`/score` — Ver marcador\n"
            "`/resetimpostor` — Resetear puntajes\n"
            "`/language` — Cambiar idioma\n"
            "`/cancel` — Cancelar partida"
        ),
        "bot_no_iniciado":          "⚠️ Debes iniciar el bot primero para recibir tu palabra secreta.\n\nAbre el chat privado con el bot, presiona INICIAR y luego vuelve aquí para unirte.",
        "btn_unirse":               "✋ Unirse a la partida",
        "nueva_partida":            "🎮 *{nombre} creó una nueva partida del juego Impostor\\!*\n\nPulsen el botón o usen /join para sumarse\\.\nCuando estén listos, el creador pulsa *¡Iniciar partida\\!*",
        "sin_partida":              "⚠️ No hay ninguna partida abierta. Usa /playimpostor para crear una.",
        "partida_en_curso":         "⚠️ La partida ya está en curso, no puedes unirte ahora.",
        "ya_en_partida":            "⚠️ Ya estás en la partida.",
        "partida_llena":            "⚠️ La partida está llena \\(máximo {n} jugadores\\)\\.",
        "unido":                    "✅ *{nombre} se unió\\!*\n\n*Jugadores* \\({n}\\):\n{lista}\n\n",
        "puede_iniciar":            "_El creador puede iniciar cuando quiera\\._",
        "faltan_jugadores":         "Faltan *{n}* jugadores más para poder iniciar\\.",
        "btn_iniciar":              "🚀 ¡Iniciar partida!",
        "no_partida_espera":        "No hay partida en espera.",
        "solo_creador_iniciar":     "⚠️ Solo el creador puede iniciar la partida.",
        "pocos_jugadores":          "⚠️ Necesitas al menos 3 jugadores. Ahora hay {n}.",
        "elige_categoria":          "🗂️ *Elige una categoría:*",
        "btn_random":               "🎲 ¡Sorpréndeme! (Random)",
        "solo_creador_categoria":   "Solo el creador puede elegir la categoría.",
        "cat_sorpresa_grupo":       "🎲 *¡Categoría sorpresa\\!*",
        "cat_confirmacion":         "✅ Categoría: *{cat}*",
        "cat_grupo":                "Categoría: *{cat}*",
        "enviando_privado":         "📩 Enviando palabras en privado\\.\\.\\.",
        "eres_impostor":            "🕵️ *¡Eres el IMPOSTOR\\!*\n\nCategoría: *{cat}*\n\nNo conoces la palabra\\. Intenta descubrirla por las pistas de los demás\\. ¡No te atrapen\\! 🎭",
        "eres_inocente":            "🔑 Tu palabra secreta es:\n\n✨ *{palabra}* ✨\n\nCategoría: *{cat}*\n\n💡 *Cómo puedes describirla:*\n{pistas}\n\n_Da pistas sin decir la palabra directamente\\. ¡Encuentra al impostor\\!_ 🕵️",
        "aviso_fallidos":           "\n\n⚠️ No pude enviar mensaje a: {nombres}\n_Deben iniciar conversación con el bot primero_",
        "aviso_2rondas":            "Esta partida se juega en *2 rondas* de pistas antes de votar\\. ¡Atención\\! 👀",
        "aviso_votar":              "Cuando todos hayan dado su pista, el creador abre la votación 🗳️",
        "partida_comienza":         "🎮 *¡La partida comienza\\!*\n\n{cat}\n\n*🎲 Orden de pistas \\(elegido al azar\\):*\n{orden}\n\nCada uno da *una pista* sobre la palabra sin decirla directamente\\.\n{aviso_rondas}",
        "turno":                    "👆 *¡Es el turno de* [{nombre}](tg://user?id={uid})\\!\nEscribe tu pista en el chat\\.\n⏱️ _Tienes 1 minuto\\._",
        "turno_timeout":            "⏰ *¡Tiempo\\!* [{nombre}](tg://user?id={uid}) no dio pista a tiempo\\. Se salta su turno\\.",
        "turno_timeout_autoconf":   "⏰ *¡Tiempo\\!* Se confirmó automáticamente la última pista de [{nombre}](tg://user?id={uid})\\.",
        "quien_es_impostor":        "🗳️ *¿Quién es el impostor\\?*\n\n_Jugadores vivos \\({n}\\) — solo ellos votan:_",
        "no_partida_curso":         "⚠️ No hay partida en curso.",
        "solo_creador_votar":       "⚠️ Solo el creador puede abrir la votación.",
        "no_partida_votacion":      "La votación ya cerró.",
        "no_puedes_votar":          "No puedes votar: estás eliminado o no eres parte de esta partida.",
        "voto_ya":                  "Ya votaste.",
        "voto_ok":                  "✅ ¡Voto registrado!",
        "voto_confirmado":          "✅ *{nombre}* votó\\. {faltantes}",
        "voto_confirmado_revoto":   "✅ *{nombre}* votó en la revotación\\. {faltantes}",
        "faltan_votos":             "Faltan *{n}* votos\\.",
        "no_revotacion":            "No hay revotación activa.",
        "voto_invalido":            "Voto inválido.",
        "segundo_empate":           "⚖️ *¡Segundo empate\\!*\n\nNadie es eliminado en esta ronda\\. ¡El juego continúa\\!\n\nEl creador abre la votación cuando estén listos\\.",
        "btn_abrir_votacion":       "🗳️ ¡Abrir votación!",
        "empate":                   "⚖️ *¡Empate\\!*\n\n{nombres} tienen *{n} votos* cada uno\\.\n\n🔁 *Revotación* — Solo entre los empatados:\n_Jugadores vivos, voten de nuevo:_",
        "nuevo_creador":            "👑 *{nombre}* es el nuevo creador y puede abrir la votación\\.",
        "resultado_votacion":       "🗳️ *Resultado de la votación:*\n\nEl grupo votó por *{nombre}*\n{etiqueta}\n\n*Votos:*\n{detalle}",
        "era_impostor":             "🕵️ ¡Era impostor\\!",
        "era_inocente":             "✅ Era inocente\\.",
        "ultima_oportunidad":       "🎯 *¡Última oportunidad, {nombre}\\!*\n\nSi adivinas la palabra secreta *¡tú y todos los impostores ganarán\\!*\n\n📝 Escribe la palabra ahora en el chat\\.\n_Categoría: {cat}_\n⏱️ _Tienes 30 segundos\\._",
        "adiv_timeout":             "⏰ *¡Tiempo\\!* [{nombre}](tg://user?id={uid}) no adivinó a tiempo\\. ¡El grupo gana\\!",
        "adivino":                  "🎯 *¡{nombre} adivinó la palabra\\!*\n\nLa palabra era *{palabra}*\\. ¡Los impostores ganan\\! 🕵️",
        "incorrecto":               "❌ *{nombre}* escribió *{texto}*\\.\\.\\. ¡Incorrecto\\!\n\n*{nombre}* queda eliminado definitivamente\\.",
        "confirmar_pista_btn":      "✅ Confirmar esta como mi pista",
        "confirmar_adivinanza_btn": "✅ Confirmar esta como mi respuesta",
        "confirmar_adivinanza_msg": "¿Confirmas *{palabra}* como tu respuesta\\?",

        "confirmar_pista_msg":      "¿Confirmas *{pista}* como tu pista\\?",
        "no_tu_turno":              "⚠️ No es tu turno.",
        "pista_confirmada":         "✅ ¡Pista confirmada!",
        "pista_auto_confirmada":    "⚠️ Tercer intento — pista enviada automáticamente\\.",
        "segunda_ronda":            "🔄 *¡Segunda ronda de pistas\\!*\n\nAhora sí, después de esta ronda se abrirá la votación\\.\n\n*🎲 Nuevo orden:*\n{orden}",
        "todos_dieron_pista":       "✅ *¡Todos dieron su pista\\!*\n\nEl creador puede abrir la votación 🗳️",
        "nueva_ronda_pistas":       "🔄 *¡Nueva ronda de pistas\\!*\n\n👥 Jugadores vivos: *{n}*\n\n*🎲 Nuevo orden de pistas:*\n{orden}\n\nCada uno da *una pista* sobre la palabra\\.\nCuando terminen, el creador abre la votación 🗳️",
        "grupo_gana":               "🎉 *¡El grupo ganó\\!*\n\nLos impostores eran: {impostores}\n¡Fueron eliminados sin adivinar la palabra\\!\n\n🔑 La palabra era: *{palabra}* \\({cat}\\)\n\n_Usa /playimpostor para otra ronda_",
        "impostores_ganan":         "🕵️ *¡Los impostores ganaron\\!*\n\nEran: {impostores}\n{desc}\n\n🔑 La palabra era: *{palabra}* \\({cat}\\)\n\n_Usa /playimpostor para otra ronda_",
        "desc_supervivencia":       "Los impostores sobrevivieron hasta quedar solos con un inocente\\.",
        "desc_adivino":             "Un impostor adivinó la palabra correcta\\.",
        "desc_error_voto":          "Votaron incorrectamente por *{nombre}*\\.",
        "sin_estadisticas":         "📊 No hay estadísticas aún\\. ¡Juega primero\\!",
        "marcador":                 "🏆 *Marcador del grupo:*\n\n{tabla}",
        "col_jugador":              "Jugador",
        "solo_admin_reset":         "⚠️ Solo los administradores del grupo pueden resetear los puntajes.",
        "reset_ok":                 "🔄 *Puntajes reseteados\\.*\n\nTodas las victorias y derrotas vuelven a cero\\. ¡A empezar de nuevo\\! 🎮",
        "resetroles_ok":            "🔄 *Roles reseteados\\.*\n\nTodos los contadores de impostor e inocente vuelven a cero\\. 🎭",
        "sin_partida_activa":       "⚠️ No hay ninguna partida activa.",
        "solo_creador_cancelar":    "⚠️ Solo el creador puede cancelar la partida.",
        "cancelado":                "❌ Partida cancelada\\. Usa /playimpostor para empezar otra\\.",
        "idioma_actual":            "🌐 *Idioma actual: Español*\n\nElige un idioma:",
        "idioma_cambiado_es":       "✅ Idioma cambiado a *Español*\\.",
        "idioma_cambiado_en":       "✅ Language changed to *English*\\.",
        "solo_admin_idioma":        "⚠️ Solo los administradores del grupo pueden cambiar el idioma.",
        "btn_es":                   "🇪🇸 Español",
        "btn_en":                   "🇬🇧 English",
        "pistas_fallback":          "1. Piensa en sus características principales\n2. Recuerda dónde o cómo se usa",
        "prompt_pistas":            (
            "Genera exactamente 2 pistas para describir '{palabra}' (categoría: {categoria}) "
            "en el juego del impostor. Las pistas deben:\n"
            "- Ayudar a describir la palabra SIN decirla directamente ni usar palabras muy obvias\n"
            "- Ser cortas, de máximo 10 palabras cada una\n"
            "- Estar numeradas como 1. y 2.\n"
            "Responde SOLO con las 2 pistas, sin explicaciones."
        ),
        "cat_custom":               "⭐ Personalizado",
        "addword_ok":               "✅ Palabra *{palabra}* agregada a la categoría personalizada\\.",
        "addword_ya_existe":        "⚠️ *{palabra}* ya está en la lista\\.",
        "addword_uso":              "⚠️ Uso: `/addword <palabra>`",
        "addword_solo_admin":       "⚠️ Solo los administradores pueden agregar palabras.",
        "words_lista":              "⭐ *Palabras personalizadas* \\({n}\\):\n\n{lista}\n\n_Usa /addword para agregar más\\._",
        "words_vacia":              "📭 No hay palabras personalizadas aún\\.\n\nUsa `/addword <palabra>` para agregar\\.",
        "removeword_ok":            "🗑️ Palabra *{palabra}* eliminada\\.",
        "removeword_no_existe":     "⚠️ *{palabra}* no está en la lista\\.",
        "removeword_solo_admin":    "⚠️ Solo los administradores pueden eliminar palabras.",
        "removeword_uso":           "⚠️ Uso: `/removeword <palabra>`",
        "roles_tabla":              "🎭 *Roles por jugador:*\n\n{tabla}",
        "roles_tabla_header":       "🎭 *Roles por jugador:*",
        "roles_sin_datos":          "📊 No hay datos de roles aún\\. ¡Juega primero\\!",
        "col_impostor":             "😈",
        "col_inocente":             "😇",
    },
    "en": {
        # cmd_start
        "start": (
            "🕵️ *Welcome to The Impostor Bot\\!*\n\n"
            "The game is simple:\n"
            "• Everyone gets the *same secret word*\n"
            "• Except the *impostors*, who don't know it\n"
            "• Give clues without saying it directly 🎭\n"
            "• The group votes to eliminate players each round\n\n"
            "*Commands:*\n"
            "`/playimpostor` — Create a game\n"
            "`/join` — Join the game\n"
            "`/vote` — Open voting \\(creator only\\)\n"
            "`/howtoplay` — How to play\n"
            "`/score` — View scoreboard\n"
            "`/resetimpostor` — Reset scores\n"
            "`/language` — Change language\n"
            "`/cancel` — Cancel game"
        ),
        # cmd_como_jugar
        "comojugar": (
            "🕵️ *How to play The Impostor?*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "*📋 Objective*\n"
            "The group must eliminate all impostors\\. "
            "Impostors must blend in or guess the secret word\\.\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "*🎮 Game steps*\n\n"
            "*0\\. Start the bot in private*\n"
            "Go to @impostortg\\_bot and press the `Start` button at the bottom, then use `/howtoplay` to learn about the bot\\.\n\n"
            "*1\\. Create the game*\n"
            "Someone uses `/playimpostor` and others join with `/join` or the button\\.\n\n"
            "*2\\. Start*\n"
            "With at least 3 players, the creator picks a category and taps *Start game\\!*\n\n"
            "*3\\. Secret words*\n"
            "The bot sends a private message to each player:\n"
            "• Regular players receive the *secret word*\n"
            "• The impostor\\(s\\) do NOT receive the word, only the category 🎭\n\n"
            "*4\\. Give clues*\n"
            "Following a random order, each player gives *one clue* about the word\\. "
            "The impostor must make up a convincing clue without knowing the word\\.\n\n"
            "*5\\. Vote*\n"
            "When everyone has given their clue, the creator opens voting\\. "
            "Only *alive* players vote\\. The most voted player is eliminated\\.\n\n"
            "*6\\. Reveal and new round*\n"
            "It's revealed if the eliminated player was an impostor or innocent\\. "
            "If players remain, a new order is shown and the game continues\\.\n\n"
            "*7\\. Impostor's last chance*\n"
            "If the group votes out an impostor, they get *one last chance*: "
            "guess the word by typing it in the chat\\. "
            "If they guess it, *all impostors win*\\.\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "*🏆 Who wins?*\n\n"
            "🎉 *Group wins* if:\n"
            "  • They eliminate all impostors\n\n"
            "🕵️ *Impostor\\(s\\) win\\(s\\)* if:\n"
            "  • Only 1 innocent remains alongside an impostor\n"
            "  • An impostor guesses the word when voted out\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "*👥 Impostors by player count*\n"
            "  • 3\\-4 players → 1 impostor\n"
            "  • 5\\-6 players → 1 to 3 impostors \\(random\\)\n"
            "  • 7\\+ players → 2 to 3 impostors \\(random\\)\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "*📌 Commands*\n"
            "`/playimpostor` — Create game\n"
            "`/join` — Join game\n"
            "`/vote` — Open voting \\(creator\\)\n"
            "`/score` — View scoreboard\n"
            "`/resetimpostor` — Reset scores\n"
            "`/language` — Change language\n"
            "`/cancel` — Cancel game"
        ),
        "bot_no_iniciado":          "⚠️ You need to start the bot first to receive your secret word.\n\nOpen the private chat with the bot, press START and then come back here to join.",
        "btn_unirse":               "✋ Join the game",
        "nueva_partida":            "🎮 *{nombre} created a new Impostor game\\!*\n\nPress the button or use /join to join\\.\nWhen ready, the creator presses *Start game\\!*",
        "sin_partida":              "⚠️ There's no open game. Use /playimpostor to create one.",
        "partida_en_curso":         "⚠️ The game is already in progress, you can't join now.",
        "ya_en_partida":            "⚠️ You're already in the game.",
        "partida_llena":            "⚠️ The game is full \\(maximum {n} players\\)\\.",
        "unido":                    "✅ *{nombre} joined\\!*\n\n*Players* \\({n}\\):\n{lista}\n\n",
        "puede_iniciar":            "_The creator can start whenever ready\\._",
        "faltan_jugadores":         "Need *{n}* more players to start\\.",
        "btn_iniciar":              "🚀 Start game!",
        "no_partida_espera":        "No game waiting to start.",
        "solo_creador_iniciar":     "⚠️ Only the creator can start the game.",
        "pocos_jugadores":          "⚠️ You need at least 3 players. There are {n} now.",
        "elige_categoria":          "🗂️ *Choose a category:*",
        "btn_random":               "🎲 Surprise me! (Random)",
        "solo_creador_categoria":   "Only the creator can choose the category.",
        "cat_sorpresa_grupo":       "🎲 *Surprise category\\!*",
        "cat_confirmacion":         "✅ Category: *{cat}*",
        "cat_grupo":                "Category: *{cat}*",
        "enviando_privado":         "📩 Sending words in private\\.\\.\\.",
        "eres_impostor":            "🕵️ *You are the IMPOSTOR\\!*\n\nCategory: *{cat}*\n\nYou don't know the word\\. Try to figure it out from others' clues\\. Don't get caught\\! 🎭",
        "eres_inocente":            "🔑 Your secret word is:\n\n✨ *{palabra}* ✨\n\nCategory: *{cat}*\n\n💡 *How you can describe it:*\n{pistas}\n\n_Give clues without saying the word directly\\. Find the impostor\\!_ 🕵️",
        "aviso_fallidos":           "\n\n⚠️ Could not message: {nombres}\n_They must start a conversation with the bot first_",
        "aviso_2rondas":            "This game is played in *2 clue rounds* before voting\\. Pay attention\\! 👀",
        "aviso_votar":              "When everyone has given their clue, the creator opens voting 🗳️",
        "partida_comienza":         "🎮 *The game begins\\!*\n\n{cat}\n\n*🎲 Clue order \\(randomly chosen\\):*\n{orden}\n\nEach player gives *one clue* about the word without saying it directly\\.\n{aviso_rondas}",
        "turno":                    "👆 *It's* [{nombre}](tg://user?id={uid})*'s turn\\!*\nWrite your clue in the chat\\.\n⏱️ _You have 1 minute\\._",
        "turno_timeout":            "⏰ *Time's up\\!* [{nombre}](tg://user?id={uid}) didn't give a clue in time\\. Skipping their turn\\.",
        "turno_timeout_autoconf":   "⏰ *Time's up\\!* [{nombre}](tg://user?id={uid})'s last clue was automatically confirmed\\.",
        "quien_es_impostor":        "🗳️ *Who is the impostor\\?*\n\n_Alive players \\({n}\\) — only they vote:_",
        "no_partida_curso":         "⚠️ There's no game in progress.",
        "solo_creador_votar":       "⚠️ Only the creator can open voting.",
        "no_partida_votacion":      "Voting has already closed.",
        "no_puedes_votar":          "You can't vote: you're eliminated or not part of this game.",
        "voto_ya":                  "You already voted.",
        "voto_ok":                  "✅ Vote registered!",
        "voto_confirmado":          "✅ *{nombre}* voted\\. {faltantes}",
        "voto_confirmado_revoto":   "✅ *{nombre}* voted in the re-vote\\. {faltantes}",
        "faltan_votos":             "*{n}* votes remaining\\.",
        "no_revotacion":            "No re-vote active.",
        "voto_invalido":            "Invalid vote.",
        "segundo_empate":           "⚖️ *Second tie\\!*\n\nNobody is eliminated this round\\. The game continues\\!\n\nThe creator opens voting when ready\\.",
        "btn_abrir_votacion":       "🗳️ Open voting!",
        "empate":                   "⚖️ *Tie\\!*\n\n{nombres} have *{n} votes* each\\.\n\n🔁 *Re-vote* — Only tied players:\n_Alive players, vote again:_",
        "nuevo_creador":            "👑 *{nombre}* is the new creator and can open voting\\.",
        "resultado_votacion":       "🗳️ *Voting result:*\n\nThe group voted for *{nombre}*\n{etiqueta}\n\n*Votes:*\n{detalle}",
        "era_impostor":             "🕵️ Was an impostor\\!",
        "era_inocente":             "✅ Was innocent\\.",
        "ultima_oportunidad":       "🎯 *Last chance, {nombre}\\!*\n\nIf you guess the secret word *you and all impostors win\\!*\n\n📝 Write the word now in the chat\\.\n_Category: {cat}_\n⏱️ _You have 30 seconds\\._",
        "adiv_timeout":             "⏰ *Time's up\\!* [{nombre}](tg://user?id={uid}) didn't guess in time\\. The group wins\\!",
        "adivino":                  "🎯 *{nombre} guessed the word\\!*\n\nThe word was *{palabra}*\\. Impostors win\\! 🕵️",
        "incorrecto":               "❌ *{nombre}* wrote *{texto}*\\.\\.\\. Wrong\\!\n\n*{nombre}* is permanently eliminated\\.",
        "confirmar_pista_btn":      "✅ Confirm this as my clue",
        "confirmar_adivinanza_btn": "✅ Confirm this as my answer",
        "confirmar_adivinanza_msg": "Confirm *{palabra}* as your answer\\?",

        "confirmar_pista_msg":      "Confirm *{pista}* as your clue\\?",
        "no_tu_turno":              "⚠️ It's not your turn.",
        "pista_confirmada":         "✅ Clue confirmed!",
        "pista_auto_confirmada":    "⚠️ Third attempt — clue sent automatically\\.",
        "segunda_ronda":            "🔄 *Second clue round\\!*\n\nAfter this round, voting will open\\.\n\n*🎲 New order:*\n{orden}",
        "todos_dieron_pista":       "✅ *Everyone gave their clue\\!*\n\nThe creator can open voting 🗳️",
        "nueva_ronda_pistas":       "🔄 *New clue round\\!*\n\n👥 Alive players: *{n}*\n\n*🎲 New clue order:*\n{orden}\n\nEach player gives *one clue* about the word\\.\nWhen done, the creator opens voting 🗳️",
        "grupo_gana":               "🎉 *The group won\\!*\n\nThe impostors were: {impostores}\nThey were eliminated without guessing the word\\!\n\n🔑 The word was: *{palabra}* \\({cat}\\)\n\n_Use /playimpostor for another round_",
        "impostores_ganan":         "🕵️ *The impostors won\\!*\n\nThey were: {impostores}\n{desc}\n\n🔑 The word was: *{palabra}* \\({cat}\\)\n\n_Use /playimpostor for another round_",
        "desc_supervivencia":       "The impostors survived until only one innocent remained\\.",
        "desc_adivino":             "An impostor guessed the correct word\\.",
        "desc_error_voto":          "They incorrectly voted for *{nombre}*\\.",
        "sin_estadisticas":         "📊 No stats yet\\. Play first\\!",
        "marcador":                 "🏆 *Group scoreboard:*\n\n{tabla}",
        "col_jugador":              "Player",
        "solo_admin_reset":         "⚠️ Only group admins can reset scores.",
        "reset_ok":                 "🔄 *Scores reset\\.*\n\nAll wins and losses back to zero\\. Let's start fresh\\! 🎮",
        "resetroles_ok":            "🔄 *Roles reset\\.*\n\nAll impostor and innocent counters back to zero\\. 🎭",
        "sin_partida_activa":       "⚠️ There's no active game.",
        "solo_creador_cancelar":    "⚠️ Only the creator can cancel the game.",
        "cancelado":                "❌ Game cancelled\\. Use /playimpostor to start another\\.",
        "idioma_actual":            "🌐 *Current language: English*\n\nChoose a language:",
        "idioma_cambiado_es":       "✅ Idioma cambiado a *Español*\\.",
        "idioma_cambiado_en":       "✅ Language changed to *English*\\.",
        "solo_admin_idioma":        "⚠️ Only group admins can change the language.",
        "btn_es":                   "🇪🇸 Español",
        "btn_en":                   "🇬🇧 English",
        "pistas_fallback":          "1. Think about its main characteristics\n2. Remember where or how it's used",
        "prompt_pistas":            (
            "Generate exactly 2 clues to describe '{palabra}' (category: {categoria}) "
            "in the impostor game. The clues must:\n"
            "- Help describe the word WITHOUT saying it directly or using very obvious words\n"
            "- Be short, maximum 10 words each\n"
            "- Be numbered as 1. and 2.\n"
            "Reply ONLY with the 2 clues, no explanations."
        ),
        "cat_custom":               "⭐ Custom",
        "addword_ok":               "✅ Word *{palabra}* added to the custom category\\.",
        "addword_ya_existe":        "⚠️ *{palabra}* is already in the list\\.",
        "addword_uso":              "⚠️ Usage: `/addword <word>`",
        "addword_solo_admin":       "⚠️ Only admins can add words.",
        "words_lista":              "⭐ *Custom words* \\({n}\\):\n\n{lista}\n\n_Use /addword to add more\\._",
        "words_vacia":              "📭 No custom words yet\\.\n\nUse `/addword <word>` to add some\\.",
        "removeword_ok":            "🗑️ Word *{palabra}* removed\\.",
        "removeword_no_existe":     "⚠️ *{palabra}* is not in the list\\.",
        "removeword_solo_admin":    "⚠️ Only admins can remove words.",
        "removeword_uso":           "⚠️ Usage: `/removeword <word>`",
        "roles_tabla":              "🎭 *Roles per player:*\n\n{tabla}",
        "roles_tabla_header":       "🎭 *Roles per player:*",
        "roles_sin_datos":          "📊 No role data yet\\. Play first\\!",
        "col_impostor":             "😈",
        "col_inocente":             "😇",
    }
}

# ══════════════════════════════════════════════════════════════
# CATEGORÍAS EN AMBOS IDIOMAS
# ══════════════════════════════════════════════════════════════

CATEGORIAS = {
    "es": {
        "🐾 Animales": [
            "León", "Tigre", "Leopardo", "Guepardo", "Jaguar",
            "Elefante", "Jirafa", "Hipopótamo", "Rinoceronte", "Cebra",
            "Gorila", "Chimpancé", "Orangután", "Koala", "Canguro",
            "Panda", "Oso polar", "Oso grizzly", "Lobo", "Zorro",
            "Camello", "Bisonte", "Alce", "Ciervo", "Jabalí",
            "Delfín", "Ballena", "Orca", "Foca", "Manatí", "Nutria", "Castor",
            "Cocodrilo", "Caimán", "Iguana", "Camaleón", "Gecko",
            "Tortuga", "Serpiente", "Cobra", "Anaconda", "Dragón de Komodo",
            "Salamandra", "Rana toro",
            "Flamenco", "Pingüino", "Tucán", "Loro", "Cóndor",
            "Águila", "Búho", "Pavo real", "Pelícano", "Colibrí", "Avestruz", "Kiwi",
            "Tiburón", "Pulpo", "Medusa", "Mantarraya", "Caballito de mar",
            "Estrella de mar", "Cangrejo", "Langosta", "Pez payaso",
            "Murciélago", "Ornitorrinco", "Armadillo", "Pangolín", "Axolote",
            "Tarántula", "Escorpión", "Mantis religiosa",
        ],
        "⚽ Deportes": [
            "Fútbol", "Baloncesto", "Voleibol", "Rugby", "Hockey sobre hielo",
            "Béisbol", "Waterpolo", "Handball", "Fútbol americano",
            "Cricket", "Polo", "Ultimate Frisbee",
            "Tenis", "Pádel", "Bádminton", "Squash", "Tenis de mesa",
            "Boxeo", "Judo", "Karate", "Taekwondo", "Esgrima",
            "Lucha libre", "Sumo", "Muay Thai", "Kendo",
            "Natación", "Surf", "Remo", "Kayak",
            "Vela", "Esquí acuático", "Buceo", "Triatlón", "Natación sincronizada",
            "Escalada", "Esquí", "Snowboard", "Parapente", "Rappel",
            "Senderismo", "Ciclismo de montaña",
            "Maratón", "Salto de altura", "Lanzamiento de jabalina", "Decatlón",
            "Golf", "Arquería", "Ciclismo", "Patinaje artístico", "Gimnasia",
            "Tiro con arco", "Equitación",
        ],
        "🌍 Lugares del mundo": [
            "Machu Picchu", "Coliseo Romano", "Torre Eiffel", "Taj Mahal", "Gran Muralla China",
            "Stonehenge", "Angkor Wat", "Petra", "Cristo Redentor", "Pirámides de Giza",
            "Alhambra", "Sagrada Familia", "Big Ben", "Estatua de la Libertad", "Kremlin",
            "Times Square", "Tokio", "Venecia", "Dubái", "Bangkok",
            "Estambul", "Río de Janeiro", "Ciudad del Cabo", "Singapur", "Praga",
            "Buenos Aires", "Marrakech", "Amsterdam", "Nueva Orleans", "Kioto",
            "Sahara", "Amazonas", "Patagonia", "Islandia", "Maldivas",
            "Gran Cañón", "Siberia", "Antártida", "Serengeti", "Fiordos Noruegos",
            "Gran Barrera de Coral", "Selva Negra", "Desierto de Atacama", "Valle de la Muerte", "Galápagos",
            "Lago Titicaca", "Mar Muerto", "Río Nilo", "Lago Baikal", "Cataratas del Niágara",
            "Cataratas Victoria", "Mar Mediterráneo", "Río Amazonas", "Mar Caribe",
            "La Toscana", "Bali", "Santorini", "Cappadocia", "Polinesia Francesa",
            "Tibet", "Laponia", "Zanzibar", "Maasai Mara", "Borneo",
        ],
        "📦 Objetos cotidianos": [
            "Paraguas", "Espejo", "Gancho", "Colador", "Embudo",
            "Tijeras", "Candado", "Lupa", "Brújula", "Termómetro",
            "Reloj", "Cuaderno", "Mesa", "Silla", "Lámpara",
            "Almohada", "Cobija", "Cortina", "Jabonera", "Tapete",
            "Florero", "Portarretrato", "Canasto", "Escoba", "Trapeador",
            "Sartén", "Olla", "Cuchillo", "Tenedor", "Cuchara",
            "Rallador", "Destapador", "Corcho", "Delantal", "Licuadora",
            "Tostadora", "Microondas", "Mortero", "Espátula", "Batidora",
            "Calculadora", "Maletín", "Destornillador", "Engrapadora", "Regla",
            "Sacapuntas", "Borrador", "Clip", "Carpeta", "Sello",
            "Archivador", "Pizarrón", "Marcador", "Compás", "Resaltador",
            "Billetera", "Llavero", "Pañuelo", "Agenda",
            "Audífonos", "Cargador", "Termo", "Linterna", "Veladora",
            "Martillo", "Alicate", "Taladro", "Serrucho", "Escalera",
            "Pincel", "Rodillo", "Cinta", "Llave", "Nivel",
        ],
        "🎨 Colores": [
            "Turquesa", "Magenta", "Escarlata", "Índigo", "Negro",
            "Lavanda", "Carmesí", "Rosado", "Marfil", "Rojo",
            "Amarillo", "Violeta", "Dorado", "Plateado", "Coral", "Azul", "Blanco",
        ],
        "🌐 Países": [
            "Noruega", "Grecia", "Portugal", "Islandia", "Suecia",
            "Finlandia", "Dinamarca", "Polonia", "Hungría", "Rumania",
            "Croacia", "Serbia", "Austria", "Suiza", "Bélgica",
            "Países Bajos", "Irlanda", "Escocia", "Albania", "Montenegro",
            "Brasil", "Argentina", "Colombia", "Chile", "Perú",
            "México", "Canadá", "Cuba", "Venezuela", "Bolivia",
            "Ecuador", "Uruguay", "Paraguay", "Costa Rica", "Panamá",
            "Guatemala", "Honduras", "Jamaica", "República Dominicana", "Haití",
            "Japón", "Tailandia", "India", "China", "Corea del Sur", "Corea del Norte",
            "Vietnam", "Indonesia", "Filipinas", "Malasia", "Nepal",
            "Pakistán", "Bangladés", "Sri Lanka", "Myanmar", "Camboya",
            "Mongolia", "Kazajistán", "Uzbekistán", "Georgia", "Armenia",
            "Marruecos", "Sudáfrica", "Egipto",
            "Tanzania", "Ghana", "Senegal", "Nigeria", "Túnez",
            "Argelia", "Mozambique", "Madagascar", "Zimbabue", "Camerún",
            "Australia", "Nueva Zelanda",
            "Israel", "Irán", "Iraq", "Arabia Saudita",
        ],
        "🎌 Anime (personajes/series)": [
            "Goku", "Naruto", "Luffy", "Ichigo", "Eren Jaeger",
            "Levi Ackerman", "Edward Elric", "Spike Spiegel", "Light Yagami", "L Lawliet",
            "Sailor Moon", "Sakura Kinomoto", "Asuka Langley", "Rei Ayanami", "Mikasa Ackerman",
            "Killua", "Gon Freecss", "Meruem", "Hisoka", "Kurapika",
            "Zoro", "Sanji", "Nami", "Nico Robin", "Shanks",
            "Sasuke", "Itachi", "Kakashi", "Madara", "Hinata",
            "Tanjiro", "Nezuko", "Zenitsu", "Inosuke", "Muzan",
            "Deku", "Bakugo", "All Might", "Todoroki", "Endeavor",
            "Vegeta", "Piccolo", "Gohan", "Frieza", "Cell",
            "Saitama", "Genos", "Garou", "Bang", "Tatsumaki",
            "Dragon Ball", "One Piece", "Bleach", "Attack on Titan",
            "Fullmetal Alchemist", "Death Note", "Hunter x Hunter", "Demon Slayer", "My Hero Academia",
            "Neon Genesis Evangelion", "Cowboy Bebop", "Sword Art Online", "Tokyo Ghoul", "Fairy Tail",
            "One Punch Man", "Jujutsu Kaisen", "Chainsaw Man", "Spy x Family", "Re:Zero",
            "Steins;Gate", "Code Geass", "No Game No Life", "Overlord", "Black Clover",
            "Vinland Saga", "Mob Psycho 100", "Violet Evergarden", "Your Lie in April", "Clannad",
            "Studio Ghibli", "Shonen Jump", "Isekai", "Tsundere", "Shōnen",
            "Seinen", "Mecha", "Filler", "Mangaka",
        ],
        "⚽ Futbolistas": [
            "Pelé", "Diego Maradona", "Johan Cruyff", "Franz Beckenbauer", "Ronaldo Nazário",
            "Zinedine Zidane", "Ronaldinho", "Roberto Carlos", "Cafu", "Paolo Maldini",
            "Franco Baresi", "Marco van Basten", "Ruud Gullit", "George Best", "Bobby Charlton",
            "Michel Platini", "Eusébio", "Garrincha", "Lev Yashin", "Ferenc Puskás",
            "Thierry Henry", "Andrés Iniesta", "Xavi Hernández", "Steven Gerrard", "Frank Lampard",
            "Wayne Rooney", "Fernando Torres", "David Villa", "Kaká", "Samuel Eto'o",
            "Didier Drogba", "Gianluigi Buffon", "Carles Puyol", "John Terry", "Ashley Cole",
            "Lionel Messi", "Cristiano Ronaldo", "Neymar", "Luka Modric", "Sergio Ramos",
            "Luis Suárez", "Zlatan Ibrahimović", "Arjen Robben", "Franck Ribéry", "Iker Casillas",
            "Manuel Neuer", "Sergio Busquets", "David Silva", "Cesc Fàbregas", "Mesut Özil",
            "Kylian Mbappé", "Erling Haaland", "Vinicius Jr", "Pedri", "Gavi",
            "Rodri", "Jude Bellingham", "Phil Foden", "Bukayo Saka", "Jamal Musiala",
            "Federico Valverde", "Rafael Leão", "Victor Osimhen", "Mohamed Salah", "Sadio Mané",
            "Kevin De Bruyne", "Harry Kane", "Marcus Rashford", "Trent Alexander-Arnold", "Alphonso Davies",
        ],
        "🎤 K-Pop (idols/grupos)": [
            # Grupos femeninos actuales
            "BLACKPINK", "TWICE", "aespa", "IVE", "NewJeans",
            "ITZY", "NMIXX", "LE SSERAFIM", "MAMAMOO", "Red Velvet",
            "BABYMONSTER", "STAYC", "Kep1er", "EVERGLOW", "WEEEKLY",
            "tripleS", "(G)I-DLE", "APINK", "EXID", "AOA",
            # Grupos femeninos legendarios/2ª y 3ª generación
            "Girls Generation", "2NE1", "Wonder Girls", "T-ARA", "SISTAR",
            "4MINUTE", "f(x)", "After School", "MISS A", "Brown Eyed Girls",
            "SECRET", "KARA", "Rainbow", "Hello Venus", "Stellar",
            "GFRIEND", "MOMOLAND", "LOONA", "Oh My Girl", "MAMAMOO",
            "CLC", "Dreamcatcher", "Brave Girls", "fromis_9", "DIA",
            # Solistas femeninas
            "IU", "Sunmi", "HyunA", "Chungha", "Heize",
            "Jessi", "Somi", "Gain", "BoA", "CL",
            "Taeyeon", "Tiffany", "Hyolyn", "Ailee", "Wheein",
            "Hwasa", "Yubin", "Hyosung", "Lee Hyori", "Park Bom",
            # Integrantes BLACKPINK
            "Jennie", "Lisa", "Rosé", "Jisoo",
            # Integrantes TWICE
            "Nayeon", "Jeongyeon", "Momo", "Sana", "Jihyo",
            "Mina", "Dahyun", "Chaeyoung", "Tzuyu",
            # Integrantes aespa
            "Karina", "Giselle", "Winter", "Ningning",
            # Integrantes IVE
            "Yujin", "Gaeul", "Rei", "Wonyoung", "Liz", "Leeseo",
            # Integrantes NewJeans
            "Minji", "Hanni", "Danielle", "Haerin", "Hyein",
            # Integrantes Red Velvet
            "Irene", "Seulgi", "Wendy", "Joy", "Yeri",
            # Integrantes ITZY
            "Yeji", "Lia", "Ryujin", "Chaeryeong", "Yuna",
            # Integrantes LE SSERAFIM
            "Sakura", "Chaewon", "Yunjin", "Kazuha", "Eunchae",
            # Integrantes Girls Generation
            "Taeyeon", "Tiffany", "Yoona", "Yuri", "Sooyoung",
            "Hyoyeon", "Sunny", "Seohyun",
            # Integrantes MAMAMOO
            "Solar", "Moonbyul", "Wheein", "Hwasa",
            # Integrantes NMIXX
            "Lily", "Haewon", "Sullyoon", "Bae", "Jiwoo", "Kyujin",
            # Integrantes STAYC
            "Sumin", "Sieun", "ISA", "Seeun", "Yoon", "J",
            # Integrantes Kep1er
            "Mashiro", "Chaehyun", "Hikaru", "Dayeon", "Xiaoting", "Yeseo", "Youngeun",
            # Integrantes EVERGLOW
            "Aisha", "Sihyeon", "Mia", "Onda", "Yiren",
            # Integrantes (G)I-DLE
            "Miyeon", "Minnie", "Soojin", "Soyeon", "Yuqi", "Shuhua",
            # Integrantes EXID
            "Solji", "LE", "Hani", "Hyelin", "Jeonghwa",
            # Integrantes APINK
            "Chorong", "Bomi", "Eunji", "Namjoo", "Hayoung",
            # Integrantes GFRIEND
            "SinB", "Eunha", "Umji",
            # Integrantes BABYMONSTER
            "Ruka", "Pharita", "Asa", "Rami", "Ahyeon", "Rora", "Chiquita",
            # Integrantes Oh My Girl
            "Hyojung", "Mimi", "YooA", "Seunghee", "Jiho", "Binnie", "Arin",
            # Integrantes fromis_9
            "Hayoung", "Saerom", "Nagyung", "Jiwon", "Jisun", "Seoyeon", "Chaeyoung", "Gyuri",
            # Integrantes LOONA
            "Heejin", "Hyunjin", "Haseul", "Yeojin", "Vivi", "Kim Lip", "Jinsoul", "Choerry",
            # Integrantes Dreamcatcher
            "JiU", "SuA", "Siyeon", "Handong", "Yoohyeon", "Dami", "Gahyeon",
        ],
        "🍽️ Comidas del mundo": [
            "Pizza", "Pasta Carbonara", "Lasaña", "Risotto", "Paella",
            "Sushi", "Ramen", "Arroz frito", "Bibimbap",
            "Hamburguesa", "Hot Dog", "Asado argentino", "Peking Duck", "Shawarma",
            "Kebab", "Tacos", "Barbacoa", "Churrasco", "Cordero al horno",
            "Tom Yum", "Gazpacho", "Borscht", "Caldo de pollo",
            "Miso", "Minestrone", "Goulash", "Ceviche",
            "Croissant", "Bagel", "Pretzel", "Falafel", "Empanada",
            "Arepa", "Tortilla", "Naan", "Baguette", "Pita",
            "Curry", "Hummus", "Moussaka", "Couscous", "Kimchi",
            "Tempura", "Dim Sum", "Gyoza", "Burrito", "Enchilada",
            "Tiramisu", "Crêpe", "Waffle",
            "Cheesecake", "Macarons", "Baklava", "Mochi", "Churros",
            "Crème Brûlée", "Brownie", "Donut", "Cannoli", "Profiteroles",
            "Pancakes", "Eggs Benedict", "Granola", "Acai Bowl", "Shakshuka",
            "Nachos", "Spring Rolls", "Samosa", "Poutine",
            "Fish and Chips", "Currywurst", "Takoyaki", "Elote", "Pupusas",
        ],
        "🌟 Famosos": [
            "Tom Hanks", "Meryl Streep", "Leonardo DiCaprio", "Scarlett Johansson", "Denzel Washington",
            "Brad Pitt", "Angelina Jolie", "Johnny Depp", "Natalie Portman", "Cate Blanchett",
            "Robert Downey Jr", "Chris Evans", "Margot Robbie", "Ryan Reynolds", "Dwayne Johnson",
            "Will Smith", "Morgan Freeman", "Samuel L. Jackson", "Jennifer Lawrence", "Emma Stone",
            "Steven Spielberg", "Christopher Nolan", "Quentin Tarantino", "Martin Scorsese", "Tim Burton",
            "Michael Jackson", "Madonna", "Beyoncé", "Taylor Swift", "Rihanna",
            "Eminem", "Drake", "Bad Bunny", "J Balvin", "Shakira",
            "Ed Sheeran", "Adele", "Lady Gaga", "Justin Bieber", "Billie Eilish",
            "The Weeknd", "Kanye West", "Jay-Z", "Ariana Grande", "Dua Lipa",
            "MrBeast", "PewDiePie", "Ibai", "Auronplay", "TheGrefg",
            "Ninja", "Pokimane", "xQc", "Rubius", "Vegetta777",
            "Elon Musk", "Jeff Bezos", "Mark Zuckerberg", "Steve Jobs", "Bill Gates",
        ],
        "🎬 Películas & Series": [
            "El Padrino", "Titanic", "Schindler's List", "Pulp Fiction", "Forrest Gump",
            "El Rey León", "Matrix", "Gladiador", "Interstellar", "Inception",
            "El Señor de los Anillos", "Star Wars", "Indiana Jones", "Jurassic Park", "Alien",
            "Terminator", "RoboCop", "Blade Runner", "2001 Odisea en el espacio", "Psicosis",
            "Avatar", "Avengers Endgame", "Spider-Man", "Batman", "Superman",
            "Black Panther", "Iron Man", "Doctor Strange", "Joker", "Oppenheimer",
            "Barbie", "Top Gun", "John Wick", "Everything Everywhere", "Get Out",
            "Breaking Bad", "Game of Thrones", "The Wire", "Los Soprano", "The Office",
            "Friends", "Seinfeld", "Lost", "24", "House of Cards",
            "Stranger Things", "Black Mirror", "Peaky Blinders", "Narcos", "Dexter",
            "The Crown", "Chernobyl", "Squid Game", "Dark", "Severance",
            "Los Simpsons", "South Park", "Futurama", "Rick y Morty", "Bob's Burgers",
            "Avatar La Leyenda de Aang", "Arcane", "Bojack Horseman", "Gravity Falls", "Steven Universe",
            "Walter White", "Tony Soprano", "Daenerys Targaryen", "Jon Snow", "Tyrion Lannister",
            "Hannibal Lecter", "James Bond", "Ellen Ripley", "El Guasón",
        ],
        "💼 Profesiones": [
            "Médico", "Enfermero", "Cirujano", "Psicólogo", "Dentista",
            "Veterinario", "Farmacéutico", "Fisioterapeuta", "Paramédico", "Nutricionista",
            "Programador", "Diseñador web", "Ingeniero de software", "Hacker ético", "Analista de datos",
            "Administrador de redes", "Desarrollador móvil", "DevOps",
            "Actor", "Director de cine", "Músico", "Fotógrafo", "Ilustrador",
            "Escritor", "Periodista", "Diseñador gráfico", "Animador", "Productor musical",
            "Maestro", "Profesor universitario", "Científico", "Arqueólogo", "Astrónomo",
            "Biólogo marino", "Geólogo", "Antropólogo", "Historiador", "Filósofo",
            "Chef", "Bombero", "Policía", "Abogado", "Juez",
            "Arquitecto", "Piloto", "Astronauta", "Detective", "Diplomático",
            "Mecánico", "Electricista", "Carpintero", "Plomero", "Soldador",
            "Futbolista", "Atleta olímpico", "Entrenador personal", "Árbitro", "Escalador profesional",
            "Buzo", "Piloto de carreras", "Jinete", "Surfista profesional", "Boxeador",
        ],
        "🎮 Videojuegos": [
            "Mario", "Link", "Master Chief", "Kratos", "Geralt de Rivia",
            "Lara Croft", "Nathan Drake", "Cloud Strife", "Solid Snake", "Samus Aran",
            "Sonic", "Pikachu", "Crash Bandicoot", "Spyro", "Mega Man",
            "Dante", "Ryu", "Sub-Zero", "Scorpion", "Kazuya Mishima",
            "Arthur Morgan", "Joel", "Ellie", "Aloy",
            "Minecraft", "Fortnite", "League of Legends", "Counter-Strike", "Valorant",
            "Grand Theft Auto", "Red Dead Redemption", "The Last of Us", "God of War", "Zelda",
            "Dark Souls", "Elden Ring", "Cyberpunk 2077", "The Witcher", "Skyrim",
            "Call of Duty", "Halo", "FIFA", "NBA 2K",
            "Among Us", "Rocket League", "Overwatch", "Apex Legends", "PUBG",
            "Resident Evil", "Silent Hill", "Bioshock", "Portal", "Half-Life",
            "Super Mario", "Pokemon", "Tetris", "Pac-Man", "Space Invaders",
            "Final Fantasy", "Dragon Quest", "Monster Hunter", "Street Fighter", "Mortal Kombat",
            "PlayStation", "Xbox", "Nintendo Switch", "Game Boy", "Atari",
            "Nintendo", "Sony", "Valve", "Rockstar Games",
            "Naughty Dog", "CD Projekt Red", "FromSoftware", "Blizzard", "Epic Games",
        ],
    },
    "en": {
        "🐾 Animals": [
            "Lion", "Tiger", "Leopard", "Cheetah", "Jaguar",
            "Elephant", "Giraffe", "Hippopotamus", "Rhinoceros", "Zebra",
            "Gorilla", "Chimpanzee", "Orangutan", "Koala", "Kangaroo",
            "Panda", "Polar bear", "Grizzly bear", "Wolf", "Fox",
            "Camel", "Bison", "Moose", "Deer", "Wild boar",
            "Dolphin", "Whale", "Orca", "Seal", "Manatee", "Otter", "Beaver",
            "Crocodile", "Alligator", "Iguana", "Chameleon", "Gecko",
            "Turtle", "Snake", "Cobra", "Anaconda", "Komodo dragon",
            "Salamander", "Bullfrog",
            "Flamingo", "Penguin", "Toucan", "Parrot", "Condor",
            "Eagle", "Owl", "Peacock", "Pelican", "Hummingbird", "Ostrich", "Kiwi",
            "Shark", "Octopus", "Jellyfish", "Manta ray", "Seahorse",
            "Starfish", "Crab", "Lobster", "Clownfish",
            "Bat", "Platypus", "Armadillo", "Pangolin", "Axolotl",
            "Tarantula", "Scorpion", "Praying mantis",
        ],
        "⚽ Sports": [
            "Soccer", "Basketball", "Volleyball", "Rugby", "Ice hockey",
            "Baseball", "Water polo", "Handball", "American football",
            "Cricket", "Polo", "Ultimate Frisbee",
            "Tennis", "Padel", "Badminton", "Squash", "Table tennis",
            "Boxing", "Judo", "Karate", "Taekwondo", "Fencing",
            "Wrestling", "Sumo", "Muay Thai", "Kendo",
            "Swimming", "Surfing", "Rowing", "Kayaking",
            "Sailing", "Water skiing", "Scuba diving", "Triathlon", "Synchronized swimming",
            "Rock climbing", "Skiing", "Snowboarding", "Paragliding", "Rappelling",
            "Hiking", "Mountain biking",
            "Marathon", "High jump", "Javelin throw", "Decathlon",
            "Golf", "Archery", "Cycling", "Figure skating", "Gymnastics",
            "Horseback riding",
        ],
        "🌍 World Places": [
            "Machu Picchu", "Roman Colosseum", "Eiffel Tower", "Taj Mahal", "Great Wall of China",
            "Stonehenge", "Angkor Wat", "Petra", "Christ the Redeemer", "Pyramids of Giza",
            "Alhambra", "Sagrada Familia", "Big Ben", "Statue of Liberty", "Kremlin",
            "Times Square", "Tokyo", "Venice", "Dubai", "Bangkok",
            "Istanbul", "Rio de Janeiro", "Cape Town", "Singapore", "Prague",
            "Buenos Aires", "Marrakech", "Amsterdam", "New Orleans", "Kyoto",
            "Sahara", "Amazon", "Patagonia", "Iceland", "Maldives",
            "Grand Canyon", "Siberia", "Antarctica", "Serengeti", "Norwegian Fjords",
            "Great Barrier Reef", "Black Forest", "Atacama Desert", "Death Valley", "Galapagos",
            "Lake Titicaca", "Dead Sea", "Nile River", "Lake Baikal", "Niagara Falls",
            "Victoria Falls", "Mediterranean Sea", "Amazon River", "Caribbean Sea",
            "Tuscany", "Bali", "Santorini", "Cappadocia", "French Polynesia",
            "Tibet", "Lapland", "Zanzibar", "Maasai Mara", "Borneo",
        ],
        "📦 Everyday Objects": [
            "Umbrella", "Mirror", "Hanger", "Colander", "Funnel",
            "Scissors", "Padlock", "Magnifying glass", "Compass", "Thermometer",
            "Clock", "Notebook", "Table", "Chair", "Lamp",
            "Pillow", "Blanket", "Curtain", "Soap dish", "Doormat",
            "Vase", "Picture frame", "Basket", "Broom", "Mop",
            "Frying pan", "Pot", "Knife", "Fork", "Spoon",
            "Grater", "Bottle opener", "Cork", "Apron", "Blender",
            "Toaster", "Microwave", "Mortar", "Spatula", "Hand mixer",
            "Calculator", "Briefcase", "Screwdriver", "Stapler", "Ruler",
            "Pencil sharpener", "Eraser", "Paperclip", "Folder", "Stamp",
            "Binder", "Whiteboard", "Marker", "Drawing compass", "Highlighter",
            "Wallet", "Keychain", "Handkerchief", "Planner",
            "Headphones", "Charger", "Thermos", "Flashlight", "Candle",
            "Hammer", "Pliers", "Drill", "Handsaw", "Ladder",
            "Paintbrush", "Roller", "Tape", "Wrench", "Level",
        ],
        "🎨 Colors": [
            "Turquoise", "Magenta", "Scarlet", "Indigo", "Black",
            "Lavender", "Crimson", "Pink", "Ivory", "Red",
            "Yellow", "Violet", "Gold", "Silver", "Coral", "Blue", "White",
        ],
        "🌐 Countries": [
            "Norway", "Greece", "Portugal", "Iceland", "Sweden",
            "Finland", "Denmark", "Poland", "Hungary", "Romania",
            "Croatia", "Serbia", "Austria", "Switzerland", "Belgium",
            "Netherlands", "Ireland", "Scotland", "Albania", "Montenegro",
            "Brazil", "Argentina", "Colombia", "Chile", "Peru",
            "Mexico", "Canada", "Cuba", "Venezuela", "Bolivia",
            "Ecuador", "Uruguay", "Paraguay", "Costa Rica", "Panama",
            "Guatemala", "Honduras", "Jamaica", "Dominican Republic", "Haiti",
            "Japan", "Thailand", "India", "China", "South Korea", "North Korea",
            "Vietnam", "Indonesia", "Philippines", "Malaysia", "Nepal",
            "Pakistan", "Bangladesh", "Sri Lanka", "Myanmar", "Cambodia",
            "Mongolia", "Kazakhstan", "Uzbekistan", "Georgia", "Armenia",
            "Morocco", "South Africa", "Egypt",
            "Tanzania", "Ghana", "Senegal", "Nigeria", "Tunisia",
            "Algeria", "Mozambique", "Madagascar", "Zimbabwe", "Cameroon",
            "Australia", "New Zealand",
            "Israel", "Iran", "Iraq", "Saudi Arabia",
        ],
        "🎌 Anime (characters/series)": [
            "Goku", "Naruto", "Luffy", "Ichigo", "Eren Jaeger",
            "Levi Ackerman", "Edward Elric", "Spike Spiegel", "Light Yagami", "L Lawliet",
            "Sailor Moon", "Sakura Kinomoto", "Asuka Langley", "Rei Ayanami", "Mikasa Ackerman",
            "Killua", "Gon Freecss", "Meruem", "Hisoka", "Kurapika",
            "Zoro", "Sanji", "Nami", "Nico Robin", "Shanks",
            "Sasuke", "Itachi", "Kakashi", "Madara", "Hinata",
            "Tanjiro", "Nezuko", "Zenitsu", "Inosuke", "Muzan",
            "Deku", "Bakugo", "All Might", "Todoroki", "Endeavor",
            "Vegeta", "Piccolo", "Gohan", "Frieza", "Cell",
            "Saitama", "Genos", "Garou", "Bang", "Tatsumaki",
            "Dragon Ball", "One Piece", "Bleach", "Attack on Titan",
            "Fullmetal Alchemist", "Death Note", "Hunter x Hunter", "Demon Slayer", "My Hero Academia",
            "Neon Genesis Evangelion", "Cowboy Bebop", "Sword Art Online", "Tokyo Ghoul", "Fairy Tail",
            "One Punch Man", "Jujutsu Kaisen", "Chainsaw Man", "Spy x Family", "Re:Zero",
            "Steins;Gate", "Code Geass", "No Game No Life", "Overlord", "Black Clover",
            "Vinland Saga", "Mob Psycho 100", "Violet Evergarden", "Your Lie in April", "Clannad",
            "Studio Ghibli", "Shonen Jump", "Isekai", "Tsundere", "Shōnen",
            "Seinen", "Mecha", "Filler", "Mangaka",
        ],
        "⚽ Footballers": [
            "Pelé", "Diego Maradona", "Johan Cruyff", "Franz Beckenbauer", "Ronaldo Nazário",
            "Zinedine Zidane", "Ronaldinho", "Roberto Carlos", "Cafu", "Paolo Maldini",
            "Franco Baresi", "Marco van Basten", "Ruud Gullit", "George Best", "Bobby Charlton",
            "Michel Platini", "Eusébio", "Garrincha", "Lev Yashin", "Ferenc Puskás",
            "Thierry Henry", "Andrés Iniesta", "Xavi Hernández", "Steven Gerrard", "Frank Lampard",
            "Wayne Rooney", "Fernando Torres", "David Villa", "Kaká", "Samuel Eto'o",
            "Didier Drogba", "Gianluigi Buffon", "Carles Puyol", "John Terry", "Ashley Cole",
            "Lionel Messi", "Cristiano Ronaldo", "Neymar", "Luka Modric", "Sergio Ramos",
            "Luis Suárez", "Zlatan Ibrahimović", "Arjen Robben", "Franck Ribéry", "Iker Casillas",
            "Manuel Neuer", "Sergio Busquets", "David Silva", "Cesc Fàbregas", "Mesut Özil",
            "Kylian Mbappé", "Erling Haaland", "Vinicius Jr", "Pedri", "Gavi",
            "Rodri", "Jude Bellingham", "Phil Foden", "Bukayo Saka", "Jamal Musiala",
            "Federico Valverde", "Rafael Leão", "Victor Osimhen", "Mohamed Salah", "Sadio Mané",
            "Kevin De Bruyne", "Harry Kane", "Marcus Rashford", "Trent Alexander-Arnold", "Alphonso Davies",
        ],
        "🎤 K-Pop (idols/groups)": [
            # Current girl groups
            "BLACKPINK", "TWICE", "aespa", "IVE", "NewJeans",
            "ITZY", "NMIXX", "LE SSERAFIM", "MAMAMOO", "Red Velvet",
            "BABYMONSTER", "STAYC", "Kep1er", "EVERGLOW", "WEEEKLY",
            "tripleS", "(G)I-DLE", "APINK", "EXID", "AOA",
            # Legendary/2nd & 3rd gen girl groups
            "Girls Generation", "2NE1", "Wonder Girls", "T-ARA", "SISTAR",
            "4MINUTE", "f(x)", "After School", "MISS A", "Brown Eyed Girls",
            "SECRET", "KARA", "Rainbow", "Hello Venus", "Stellar",
            "GFRIEND", "MOMOLAND", "LOONA", "Oh My Girl", "MAMAMOO",
            "CLC", "Dreamcatcher", "Brave Girls", "fromis_9", "DIA",
            # Female soloists
            "IU", "Sunmi", "HyunA", "Chungha", "Heize",
            "Jessi", "Somi", "Gain", "BoA", "CL",
            "Taeyeon", "Tiffany", "Hyolyn", "Ailee", "Wheein",
            "Hwasa", "Yubin", "Hyosung", "Lee Hyori", "Park Bom",
            # BLACKPINK members
            "Jennie", "Lisa", "Rosé", "Jisoo",
            # TWICE members
            "Nayeon", "Jeongyeon", "Momo", "Sana", "Jihyo",
            "Mina", "Dahyun", "Chaeyoung", "Tzuyu",
            # aespa members
            "Karina", "Giselle", "Winter", "Ningning",
            # IVE members
            "Yujin", "Gaeul", "Rei", "Wonyoung", "Liz", "Leeseo",
            # NewJeans members
            "Minji", "Hanni", "Danielle", "Haerin", "Hyein",
            # Red Velvet members
            "Irene", "Seulgi", "Wendy", "Joy", "Yeri",
            # ITZY members
            "Yeji", "Lia", "Ryujin", "Chaeryeong", "Yuna",
            # LE SSERAFIM members
            "Sakura", "Chaewon", "Yunjin", "Kazuha", "Eunchae",
            # Girls Generation members
            "Taeyeon", "Tiffany", "Yoona", "Yuri", "Sooyoung",
            "Hyoyeon", "Sunny", "Seohyun",
            # MAMAMOO members
            "Solar", "Moonbyul", "Wheein", "Hwasa",
            # NMIXX members
            "Lily", "Haewon", "Sullyoon", "Bae", "Jiwoo", "Kyujin",
            # STAYC members
            "Sumin", "Sieun", "ISA", "Seeun", "Yoon", "J",
            # Kep1er members
            "Mashiro", "Chaehyun", "Hikaru", "Dayeon", "Xiaoting", "Yeseo", "Youngeun",
            # EVERGLOW members
            "Aisha", "Sihyeon", "Mia", "Onda", "Yiren",
            # (G)I-DLE members
            "Miyeon", "Minnie", "Soojin", "Soyeon", "Yuqi", "Shuhua",
            # EXID members
            "Solji", "LE", "Hani", "Hyelin", "Jeonghwa",
            # APINK members
            "Chorong", "Bomi", "Eunji", "Namjoo", "Hayoung",
            # GFRIEND members
            "SinB", "Eunha", "Umji",
            # BABYMONSTER members
            "Ruka", "Pharita", "Asa", "Rami", "Ahyeon", "Rora", "Chiquita",
            # Oh My Girl members
            "Hyojung", "Mimi", "YooA", "Seunghee", "Jiho", "Binnie", "Arin",
            # fromis_9 members
            "Hayoung", "Saerom", "Nagyung", "Jiwon", "Jisun", "Seoyeon", "Chaeyoung", "Gyuri",
            # LOONA members
            "Heejin", "Hyunjin", "Haseul", "Yeojin", "Vivi", "Kim Lip", "Jinsoul", "Choerry",
            # Dreamcatcher members
            "JiU", "SuA", "Siyeon", "Handong", "Yoohyeon", "Dami", "Gahyeon",
        ],
        "🍽️ World Foods": [
            "Pizza", "Pasta Carbonara", "Lasagna", "Risotto", "Paella",
            "Sushi", "Ramen", "Fried rice", "Bibimbap",
            "Hamburger", "Hot Dog", "Argentine BBQ", "Peking Duck", "Shawarma",
            "Kebab", "Tacos", "BBQ ribs", "Churrasco", "Roast lamb",
            "Tom Yum", "Gazpacho", "Borscht", "Chicken soup",
            "Miso soup", "Minestrone", "Goulash", "Ceviche",
            "Croissant", "Bagel", "Pretzel", "Falafel", "Empanada",
            "Arepa", "Tortilla", "Naan", "Baguette", "Pita",
            "Curry", "Hummus", "Moussaka", "Couscous", "Kimchi",
            "Tempura", "Dim Sum", "Gyoza", "Burrito", "Enchilada",
            "Tiramisu", "Crepe", "Waffle",
            "Cheesecake", "Macarons", "Baklava", "Mochi", "Churros",
            "Crème Brûlée", "Brownie", "Donut", "Cannoli", "Profiteroles",
            "Pancakes", "Eggs Benedict", "Granola", "Acai Bowl", "Shakshuka",
            "Nachos", "Spring Rolls", "Samosa", "Poutine",
            "Fish and Chips", "Currywurst", "Takoyaki", "Elote", "Pupusas",
        ],
        "🌟 Famous People": [
            "Tom Hanks", "Meryl Streep", "Leonardo DiCaprio", "Scarlett Johansson", "Denzel Washington",
            "Brad Pitt", "Angelina Jolie", "Johnny Depp", "Natalie Portman", "Cate Blanchett",
            "Robert Downey Jr", "Chris Evans", "Margot Robbie", "Ryan Reynolds", "Dwayne Johnson",
            "Will Smith", "Morgan Freeman", "Samuel L. Jackson", "Jennifer Lawrence", "Emma Stone",
            "Steven Spielberg", "Christopher Nolan", "Quentin Tarantino", "Martin Scorsese", "Tim Burton",
            "Michael Jackson", "Madonna", "Beyoncé", "Taylor Swift", "Rihanna",
            "Eminem", "Drake", "Bad Bunny", "J Balvin", "Shakira",
            "Ed Sheeran", "Adele", "Lady Gaga", "Justin Bieber", "Billie Eilish",
            "The Weeknd", "Kanye West", "Jay-Z", "Ariana Grande", "Dua Lipa",
            "MrBeast", "PewDiePie", "Ibai", "Auronplay", "TheGrefg",
            "Ninja", "Pokimane", "xQc", "Rubius", "Vegetta777",
            "Elon Musk", "Jeff Bezos", "Mark Zuckerberg", "Steve Jobs", "Bill Gates",
        ],
        "🎬 Movies & Series": [
            "The Godfather", "Titanic", "Schindler's List", "Pulp Fiction", "Forrest Gump",
            "The Lion King", "The Matrix", "Gladiator", "Interstellar", "Inception",
            "The Lord of the Rings", "Star Wars", "Indiana Jones", "Jurassic Park", "Alien",
            "Terminator", "RoboCop", "Blade Runner", "2001 A Space Odyssey", "Psycho",
            "Avatar", "Avengers Endgame", "Spider-Man", "Batman", "Superman",
            "Black Panther", "Iron Man", "Doctor Strange", "Joker", "Oppenheimer",
            "Barbie", "Top Gun", "John Wick", "Everything Everywhere", "Get Out",
            "Breaking Bad", "Game of Thrones", "The Wire", "The Sopranos", "The Office",
            "Friends", "Seinfeld", "Lost", "24", "House of Cards",
            "Stranger Things", "Black Mirror", "Peaky Blinders", "Narcos", "Dexter",
            "The Crown", "Chernobyl", "Squid Game", "Dark", "Severance",
            "The Simpsons", "South Park", "Futurama", "Rick and Morty", "Bob's Burgers",
            "Avatar The Last Airbender", "Arcane", "Bojack Horseman", "Gravity Falls", "Steven Universe",
            "Walter White", "Tony Soprano", "Daenerys Targaryen", "Jon Snow", "Tyrion Lannister",
            "Hannibal Lecter", "James Bond", "Ellen Ripley", "The Joker",
        ],
        "💼 Professions": [
            "Doctor", "Nurse", "Surgeon", "Psychologist", "Dentist",
            "Veterinarian", "Pharmacist", "Physiotherapist", "Paramedic", "Nutritionist",
            "Programmer", "Web designer", "Software engineer", "Ethical hacker", "Data analyst",
            "Network admin", "Mobile developer", "DevOps",
            "Actor", "Film director", "Musician", "Photographer", "Illustrator",
            "Writer", "Journalist", "Graphic designer", "Animator", "Music producer",
            "Teacher", "Professor", "Scientist", "Archaeologist", "Astronomer",
            "Marine biologist", "Geologist", "Anthropologist", "Historian", "Philosopher",
            "Chef", "Firefighter", "Police officer", "Lawyer", "Judge",
            "Architect", "Pilot", "Astronaut", "Detective", "Diplomat",
            "Mechanic", "Electrician", "Carpenter", "Plumber", "Welder",
            "Soccer player", "Olympic athlete", "Personal trainer", "Referee", "Pro climber",
            "Diver", "Race car driver", "Jockey", "Pro surfer", "Boxer",
        ],
        "🎮 Video Games": [
            "Mario", "Link", "Master Chief", "Kratos", "Geralt of Rivia",
            "Lara Croft", "Nathan Drake", "Cloud Strife", "Solid Snake", "Samus Aran",
            "Sonic", "Pikachu", "Crash Bandicoot", "Spyro", "Mega Man",
            "Dante", "Ryu", "Sub-Zero", "Scorpion", "Kazuya Mishima",
            "Arthur Morgan", "Joel", "Ellie", "Aloy",
            "Minecraft", "Fortnite", "League of Legends", "Counter-Strike", "Valorant",
            "Grand Theft Auto", "Red Dead Redemption", "The Last of Us", "God of War", "Zelda",
            "Dark Souls", "Elden Ring", "Cyberpunk 2077", "The Witcher", "Skyrim",
            "Call of Duty", "Halo", "FIFA", "NBA 2K",
            "Among Us", "Rocket League", "Overwatch", "Apex Legends", "PUBG",
            "Resident Evil", "Silent Hill", "Bioshock", "Portal", "Half-Life",
            "Super Mario", "Pokemon", "Tetris", "Pac-Man", "Space Invaders",
            "Final Fantasy", "Dragon Quest", "Monster Hunter", "Street Fighter", "Mortal Kombat",
            "PlayStation", "Xbox", "Nintendo Switch", "Game Boy", "Atari",
            "Nintendo", "Sony", "Valve", "Rockstar Games",
            "Naughty Dog", "CD Projekt Red", "FromSoftware", "Blizzard", "Epic Games",
        ],
    }
}

ANTHROPIC_CLIENT = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# ══════════════════════════════════════════════════════════════
# HELPERS DE IDIOMA
# ══════════════════════════════════════════════════════════════

def normalizar(texto: str) -> str:
    import unicodedata
    texto = texto.lower().strip()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto

def esc(text):
    chars = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in chars else c for c in str(text))

def esc_link(text):
    """Escape para texto dentro de [texto](url) — solo escapa ] y backslash."""
    return str(text).replace("\\", "\\\\").replace("]", "\\]")

def nombre(user):
    return user.first_name or user.username or str(user.id)

def get_chat_key(update):
    chat = update.effective_chat
    chat_id = chat.id
    if getattr(chat, "is_forum", False) and update.effective_message:
        thread_id = update.effective_message.message_thread_id
        return f"{chat_id}_{thread_id}" if thread_id else str(chat_id)
    return str(chat_id)

def get_thread_id(chat_key: str):
    """Extrae el thread_id del chat_key si existe (formato 'chat_id_thread_id')."""
    parts = chat_key.split("_")
    if len(parts) == 2:
        try:
            return int(parts[1])
        except ValueError:
            pass
    return None

def calcular_num_impostores(num_jugadores):
    if num_jugadores <= 4:
        return 1
    elif num_jugadores <= 6:
        return random.randint(1, 3)
    else:
        return random.randint(2, 3)

def t(chat_key: str, key: str) -> str:
    """Obtiene el texto en el idioma configurado para el grupo."""
    lang = get_idioma(chat_key)
    return TEXTOS[lang][key]

def cats(chat_key: str) -> dict:
    """Devuelve las categorías en el idioma del grupo, incluyendo Personalizado si hay palabras."""
    lang = get_idioma(chat_key)
    categorias = dict(CATEGORIAS[lang])
    palabras_custom = get_palabras_custom(chat_key)
    if palabras_custom:
        nombre_cat = TEXTOS[lang]["cat_custom"]
        categorias[nombre_cat] = palabras_custom
    return categorias

def elegir_palabra(chat_key: str, categoria: str, palabras: list) -> str:
    """
    Elige una palabra evitando repetir las usadas recientemente.
    - Las últimas N palabras de esa categoría reciben peso 0 (excluidas).
    - N = min(mitad del pool, 10). Si todas fueron usadas, se resetea.
    - El resto tiene peso uniforme → igual probabilidad entre sí.
    """
    if len(palabras) == 1:
        return palabras[0]

    excluir_n = min(len(palabras) // 2, 10)

    with get_conn() as conn:
        recientes = conn.execute(
            """SELECT palabra FROM historial
               WHERE chat_key=? AND categoria=?
               ORDER BY fecha DESC LIMIT ?""",
            (chat_key, categoria, excluir_n)
        ).fetchall()

    usadas = {r[0] for r in recientes}
    candidatas = [p for p in palabras if p not in usadas]

    if not candidatas:
        candidatas = palabras  # todas usadas → resetear

    return random.choice(candidatas)


def generar_pistas(palabra: str, categoria: str, chat_key: str) -> str:
    lang = get_idioma(chat_key)
    prompt = TEXTOS[lang]["prompt_pistas"].format(palabra=palabra, categoria=categoria)
    fallback = TEXTOS[lang]["pistas_fallback"]
    try:
        response = ANTHROPIC_CLIENT.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()
    except Exception:
        return fallback


# ══════════════════════════════════════════════════════════════
# BASE DE DATOS
# ══════════════════════════════════════════════════════════════
DB_PATH = "/data/impostor.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS partidas (
            chat_key        TEXT PRIMARY KEY,
            chat_id         INTEGER,
            estado          TEXT DEFAULT 'esperando',
            categoria       TEXT,
            palabra         TEXT,
            impostor_ids    TEXT,
            vivos           TEXT,
            ronda           INTEGER DEFAULT 1,
            creador_id      INTEGER
        );
        CREATE TABLE IF NOT EXISTS jugadores (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_key        TEXT,
            user_id         INTEGER,
            username        TEXT,
            victorias       INTEGER DEFAULT 0,
            derrotas        INTEGER DEFAULT 0,
            veces_impostor  INTEGER DEFAULT 0,
            veces_inocente  INTEGER DEFAULT 0,
            victorias_impostor INTEGER DEFAULT 0,
            victorias_inocente INTEGER DEFAULT 0,
            UNIQUE(chat_key, user_id)
        );
        CREATE TABLE IF NOT EXISTS partida_jugadores (
            chat_key    TEXT,
            user_id     INTEGER,
            username    TEXT,
            PRIMARY KEY (chat_key, user_id)
        );
        CREATE TABLE IF NOT EXISTS historial (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_key    TEXT,
            ganador     TEXT,
            palabra     TEXT,
            categoria   TEXT,
            fecha       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS config (
            chat_key    TEXT PRIMARY KEY,
            idioma      TEXT DEFAULT 'es'
        );
        CREATE TABLE IF NOT EXISTS palabras_custom (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_key    TEXT,
            palabra     TEXT,
            UNIQUE(chat_key, palabra)
        );
    """)
    conn.commit()
    # Migración: agregar columnas nuevas si no existen (DBs antiguas)
    for col, default in [("veces_impostor", 0), ("veces_inocente", 0), ("victorias_impostor", 0), ("victorias_inocente", 0)]:
        try:
            conn.execute(f"ALTER TABLE jugadores ADD COLUMN {col} INTEGER DEFAULT {default}")
            conn.commit()
        except Exception:
            pass  # Ya existe
    conn.close()

def get_conn():
    return sqlite3.connect(DB_PATH)

def get_idioma(chat_key: str) -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT idioma FROM config WHERE chat_key=?", (chat_key,)).fetchone()
    return row[0] if row else "es"

def set_idioma(chat_key: str, idioma: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO config (chat_key, idioma) VALUES (?,?)",
            (chat_key, idioma)
        )

def get_palabras_custom(chat_key: str) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT palabra FROM palabras_custom WHERE chat_key=? ORDER BY id",
            (chat_key,)
        ).fetchall()
    return [r[0] for r in rows]

def add_palabra_custom(chat_key: str, palabra: str) -> bool:
    """Retorna True si se agregó, False si ya existía."""
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO palabras_custom (chat_key, palabra) VALUES (?,?)",
                (chat_key, palabra)
            )
        return True
    except sqlite3.IntegrityError:
        return False

def remove_palabra_custom(chat_key: str, palabra: str) -> bool:
    """Retorna True si se eliminó, False si no existía."""
    with get_conn() as conn:
        rows = conn.execute(
            "DELETE FROM palabras_custom WHERE chat_key=? AND palabra=?",
            (chat_key, palabra)
        ).rowcount
    return rows > 0

def get_partida(chat_key):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM partidas WHERE chat_key=?", (chat_key,)).fetchone()

def get_jugadores_activos(chat_key):
    with get_conn() as conn:
        return conn.execute(
            "SELECT user_id, username FROM partida_jugadores WHERE chat_key=?", (chat_key,)
        ).fetchall()

def get_marcador(chat_key):
    with get_conn() as conn:
        return conn.execute(
            """SELECT j.user_id, j.username, j.victorias, j.derrotas
               FROM jugadores j
               INNER JOIN partida_jugadores pj ON j.chat_key = pj.chat_key AND j.user_id = pj.user_id
               WHERE j.chat_key=? ORDER BY (j.victorias - j.derrotas) DESC, j.victorias DESC""",
            (chat_key,)
        ).fetchall()

def get_marcador_global(chat_key):
    with get_conn() as conn:
        return conn.execute(
            "SELECT user_id, username, victorias, derrotas FROM jugadores WHERE chat_key=? AND (victorias > 0 OR derrotas > 0) ORDER BY (victorias - derrotas) DESC, victorias DESC",
            (chat_key,)
        ).fetchall()

def upsert_jugador(chat_key, user_id, username):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO jugadores (chat_key, user_id, username) VALUES (?,?,?)",
            (chat_key, user_id, username)
        )
        conn.execute(
            "UPDATE jugadores SET username=? WHERE chat_key=? AND user_id=?",
            (username, chat_key, user_id)
        )

def agregar_jugador_activo(chat_key, user_id, username):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO partida_jugadores (chat_key, user_id, username) VALUES (?,?,?)",
            (chat_key, user_id, username)
        )

def limpiar_jugadores_activos(chat_key):
    with get_conn() as conn:
        conn.execute("DELETE FROM partida_jugadores WHERE chat_key=?", (chat_key,))

def sumar_victoria(chat_key, user_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE jugadores SET victorias = victorias + 1 WHERE chat_key=? AND user_id=?",
            (chat_key, user_id)
        )

def sumar_derrota(chat_key, user_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE jugadores SET derrotas = derrotas + 1 WHERE chat_key=? AND user_id=?",
            (chat_key, user_id)
        )

def sumar_vez_impostor(chat_key, user_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE jugadores SET veces_impostor = veces_impostor + 1 WHERE chat_key=? AND user_id=?",
            (chat_key, user_id)
        )

def sumar_vez_inocente(chat_key, user_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE jugadores SET veces_inocente = veces_inocente + 1 WHERE chat_key=? AND user_id=?",
            (chat_key, user_id)
        )

def sumar_victoria_impostor(chat_key, user_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE jugadores SET victorias_impostor = victorias_impostor + 1 WHERE chat_key=? AND user_id=?",
            (chat_key, user_id)
        )

def sumar_victoria_inocente(chat_key, user_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE jugadores SET victorias_inocente = victorias_inocente + 1 WHERE chat_key=? AND user_id=?",
            (chat_key, user_id)
        )

def get_vivos(chat_key):
    with get_conn() as conn:
        row = conn.execute("SELECT vivos FROM partidas WHERE chat_key=?", (chat_key,)).fetchone()
    if not row or not row[0]:
        return []
    return [int(i) for i in row[0].split(",")]

def set_vivos(chat_key, vivos_ids):
    with get_conn() as conn:
        conn.execute(
            "UPDATE partidas SET vivos=? WHERE chat_key=?",
            (",".join(str(i) for i in vivos_ids), chat_key)
        )

def eliminar_de_vivos(chat_key, user_id):
    vivos = get_vivos(chat_key)
    vivos = [v for v in vivos if v != user_id]
    set_vivos(chat_key, vivos)
    return vivos


# ══════════════════════════════════════════════════════════════
# COMANDOS
# ══════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_key = get_chat_key(update)
    await update.message.reply_text(t(chat_key, "start"), parse_mode="MarkdownV2")


async def cmd_como_jugar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_key = get_chat_key(update)
    await update.message.reply_text(t(chat_key, "comojugar"), parse_mode="MarkdownV2")


async def cmd_idioma(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_key = get_chat_key(update)
    user = update.effective_user
    chat = update.effective_chat

    try:
        member = await chat.get_member(user.id)
        es_admin = member.status in ("administrator", "creator")
    except Exception:
        es_admin = False

    if not es_admin:
        await update.message.reply_text(t(chat_key, "solo_admin_idioma"))
        return

    lang = get_idioma(chat_key)
    keyboard = [[
        InlineKeyboardButton(t(chat_key, "btn_es"), callback_data="idioma:es"),
        InlineKeyboardButton(t(chat_key, "btn_en"), callback_data="idioma:en"),
    ]]
    await update.message.reply_text(
        t(chat_key, "idioma_actual"),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def btn_idioma(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_key = get_chat_key(update)
    user = update.effective_user

    try:
        member = await update.effective_chat.get_member(user.id)
        es_admin = member.status in ("administrator", "creator")
    except Exception:
        es_admin = False

    if not es_admin:
        await query.answer(t(chat_key, "solo_admin_idioma"), show_alert=True)
        return

    nuevo_idioma = query.data.split(":")[1]
    set_idioma(chat_key, nuevo_idioma)
    await query.answer()

    key = "idioma_cambiado_es" if nuevo_idioma == "es" else "idioma_cambiado_en"
    await query.edit_message_text(t(chat_key, key), parse_mode="MarkdownV2")


async def cmd_nueva(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_key = get_chat_key(update)
    chat_id = update.effective_chat.id
    user = update.effective_user

    partida = get_partida(chat_key)
    if partida and partida[2] not in ("terminada",):
        await update.message.reply_text(t(chat_key, "partida_activa"))
        return

    limpiar_jugadores_activos(chat_key)

    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO partidas (chat_key, chat_id, estado, creador_id, ronda) VALUES (?,?,?,?,1)",
            (chat_key, chat_id, "esperando", user.id)
        )

    upsert_jugador(chat_key, user.id, nombre(user))
    agregar_jugador_activo(chat_key, user.id, nombre(user))

    keyboard = [[InlineKeyboardButton(t(chat_key, "btn_unirse"), callback_data="unirse")]]
    await update.message.reply_text(
        t(chat_key, "nueva_partida").format(nombre=esc(nombre(user))),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def cmd_unirse(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _unirse(get_chat_key(update), update.effective_user, update.message.reply_text, ctx.bot)

async def btn_unirse(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_key = get_chat_key(update)
    user = update.effective_user

    # Verificar que el bot esté iniciado intentando enviar un mensaje de prueba
    try:
        await ctx.bot.send_chat_action(user.id, "typing")
    except Exception:
        # No tiene el bot iniciado → alerta flotante con deep link
        bot_username = (await ctx.bot.get_me()).username
        await query.answer(
            t(chat_key, "bot_no_iniciado"),
            show_alert=True,
            url=f"https://t.me/{bot_username}?start=join"
        )
        return

    # Verificar condiciones de error ANTES de llamar answer()
    # (Telegram solo permite una llamada a answer() por callback)
    partida = get_partida(chat_key)
    logger.info(f"[btn_unirse] user={user.id} partida_estado={partida[2] if partida else None} activos={[j[0] for j in get_jugadores_activos(chat_key)]}")
    if not partida:
        await query.answer(t(chat_key, "sin_partida"), show_alert=True)
        return
    if partida[2] != "esperando":
        await query.answer(t(chat_key, "partida_en_curso"), show_alert=True)
        return
    activos = get_jugadores_activos(chat_key)
    if user.id in [j[0] for j in activos]:
        await query.answer(t(chat_key, "ya_en_partida"), show_alert=True)
        return
    if len(activos) >= MAX_JUGADORES:
        await query.answer(t(chat_key, "partida_llena").format(n=MAX_JUGADORES), show_alert=True)
        return

    await query.answer()
    await _unirse(chat_key, user, query.message.reply_text, ctx.bot)

async def _unirse(chat_key, user, reply_fn, bot=None):
    partida = get_partida(chat_key)
    if not partida:
        await reply_fn(t(chat_key, "sin_partida"))
        return
    if partida[2] != "esperando":
        await reply_fn(t(chat_key, "partida_en_curso"))
        return

    activos = get_jugadores_activos(chat_key)
    if user.id in [j[0] for j in activos]:
        await reply_fn(t(chat_key, "ya_en_partida"))
        return

    if len(activos) >= MAX_JUGADORES:
        await reply_fn(t(chat_key, "partida_llena").format(n=MAX_JUGADORES))
        return

    upsert_jugador(chat_key, user.id, nombre(user))
    agregar_jugador_activo(chat_key, user.id, nombre(user))
    activos = get_jugadores_activos(chat_key)

    lista = "\n".join(f"  {i+1}\\. {esc(j[1])}" for i, j in enumerate(activos))

    # Botón unirse siempre presente (para que no se pierda en el chat)
    btn_unirse_row = [InlineKeyboardButton(t(chat_key, "btn_unirse"), callback_data="unirse")]

    if len(activos) >= MAX_JUGADORES:
        # Llena: solo mostrar unirse deshabilitado no es posible en TG, omitirlo
        keyboard = []
    elif len(activos) >= 3:
        keyboard = [
            btn_unirse_row,
            [InlineKeyboardButton(t(chat_key, "btn_iniciar"), callback_data="iniciar_partida")],
        ]
    else:
        keyboard = [btn_unirse_row]

    sufijo = (
        t(chat_key, "partida_llena").format(n=MAX_JUGADORES) if len(activos) >= MAX_JUGADORES
        else t(chat_key, "puede_iniciar") if len(activos) >= 3
        else t(chat_key, "faltan_jugadores").format(n=3 - len(activos))
    )
    await reply_fn(
        t(chat_key, "unido").format(nombre=esc(nombre(user)), n=len(activos), lista=lista) + sufijo,
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
    )


async def btn_iniciar_partida(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_key = get_chat_key(update)
    user = update.effective_user

    partida = get_partida(chat_key)
    if not partida or partida[2] != "esperando":
        await query.answer(t(chat_key, "no_partida_espera"), show_alert=True)
        return
    if partida[8] != user.id:
        await query.answer(t(chat_key, "solo_creador_iniciar"), show_alert=True)
        return

    jugadores = get_jugadores_activos(chat_key)
    if len(jugadores) < 3:
        await query.answer(t(chat_key, "pocos_jugadores").format(n=len(jugadores)), show_alert=True)
        return

    categorias = cats(chat_key)
    keyboard = [
        [InlineKeyboardButton(cat, callback_data=f"cat:{cat}")]
        for cat in categorias
    ]
    keyboard.append([InlineKeyboardButton(t(chat_key, "btn_random"), callback_data="cat:RANDOM")])
    await query.message.reply_text(
        t(chat_key, "elige_categoria"),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def btn_categoria(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_key = get_chat_key(update)
    chat_id = update.effective_chat.id
    user = update.effective_user

    partida = get_partida(chat_key)
    if not partida or partida[8] != user.id:
        await query.answer(t(chat_key, "solo_creador_categoria"), show_alert=True)
        return

    # Evitar doble ejecución: solo proceder si sigue en estado 'esperando'
    if partida[2] != "esperando":
        return

    # Marcar como 'iniciando' atómicamente para bloquear segundos clics
    with get_conn() as conn:
        updated = conn.execute(
            "UPDATE partidas SET estado='iniciando' WHERE chat_key=? AND estado='esperando'",
            (chat_key,)
        ).rowcount
    if updated == 0:
        return  # Otro proceso ya tomó el control

    try:
        categorias = cats(chat_key)
        categoria_raw = query.data.split(":", 1)[1]
        es_random = (categoria_raw == "RANDOM")
        categoria = random.choice(list(categorias.keys())) if es_random else categoria_raw

        # Verificar que la categoria exista (por si acaso llegó un valor inválido)
        if categoria not in categorias:
            logger.error(f"[btn_categoria] categoria invalida: {categoria!r}")
            with get_conn() as conn:
                conn.execute("UPDATE partidas SET estado='esperando' WHERE chat_key=?", (chat_key,))
            await query.message.reply_text("⚠️ Error al elegir categoría. Intenta de nuevo.")
            return

        texto_cat_grupo = t(chat_key, "cat_sorpresa_grupo") if es_random else t(chat_key, "cat_grupo").format(cat=esc(categoria))
        texto_cat_confirmacion = t(chat_key, "cat_sorpresa_grupo") if es_random else t(chat_key, "cat_confirmacion").format(cat=esc(categoria))

        palabra = elegir_palabra(chat_key, categoria, categorias[categoria])
        jugadores = get_jugadores_activos(chat_key)
        num_impostores = calcular_num_impostores(len(jugadores))
        impostores = random.sample(jugadores, num_impostores)
        impostor_ids = ",".join(str(i[0]) for i in impostores)
        impostor_ids_set = set(i[0] for i in impostores)
        vivos_ids = ",".join(str(j[0]) for j in jugadores)

        with get_conn() as conn:
            conn.execute(
                "UPDATE partidas SET estado='jugando', categoria=?, palabra=?, impostor_ids=?, vivos=? WHERE chat_key=?",
                (categoria, palabra, impostor_ids, vivos_ids, chat_key)
            )

    except Exception as e:
        # Si algo falla, devolver la partida a 'esperando' para que se pueda reintentar
        logger.error(f"[btn_categoria] error inesperado: {e}")
        with get_conn() as conn:
            conn.execute("UPDATE partidas SET estado='esperando' WHERE chat_key=?", (chat_key,))
        await query.message.reply_text("⚠️ Ocurrió un error al iniciar la partida. Intenta de nuevo.")
        return

    await query.edit_message_text(
        f"{texto_cat_confirmacion}\n\n{t(chat_key, 'enviando_privado')}",
        parse_mode="MarkdownV2"
    )

    pistas_raw = generar_pistas(palabra, categoria, chat_key)
    pistas = "\n".join(esc(linea) for linea in pistas_raw.splitlines())

    fallidos = []
    for uid, uname in jugadores:
        try:
            if uid in impostor_ids_set:
                msg = t(chat_key, "eres_impostor").format(cat=esc(categoria))
                sumar_vez_impostor(chat_key, uid)
            else:
                msg = t(chat_key, "eres_inocente").format(
                    palabra=esc(palabra), cat=esc(categoria), pistas=pistas
                )
                sumar_vez_inocente(chat_key, uid)
            await ctx.bot.send_message(uid, msg, parse_mode="MarkdownV2")
        except Exception:
            fallidos.append(uname)

    orden = list(jugadores)
    random.shuffle(orden)
    turno_lista = "\n".join(f"  {i+1}\\. {esc(j[1])}" for i, j in enumerate(orden))

    ctx.bot_data[f"turno_{chat_key}"] = {
        "orden": [j[0] for j in orden],
        "index": 0,
        "ya_dieron_pista": set(),
        "ronda_pistas": 1,
        "jugadores_iniciales": len(jugadores),
        "intentos_pista": {}
    }

    aviso = ""
    if fallidos:
        aviso = t(chat_key, "aviso_fallidos").format(
            nombres=", ".join(esc(f) for f in fallidos)
        )

    aviso_rondas = (
        t(chat_key, "aviso_2rondas") if len(jugadores) == 3
        else t(chat_key, "aviso_votar")
    )

    thread_id = get_thread_id(chat_key)
    await ctx.bot.send_message(
        chat_id,
        t(chat_key, "partida_comienza").format(
            cat=texto_cat_grupo, orden=turno_lista, aviso_rondas=aviso_rondas
        ) + aviso,
        parse_mode="MarkdownV2",
        message_thread_id=thread_id
    )

    primer = orden[0]
    await _anunciar_turno(chat_key, primer[0], primer[1], chat_id, thread_id, ctx)


async def _abrir_votacion(chat_key, ctx, message):
    vivos_ids = get_vivos(chat_key)
    jugadores = get_jugadores_activos(chat_key)
    vivos = [j for j in jugadores if j[0] in vivos_ids]

    keyboard = [
        [InlineKeyboardButton(f"🗳️ {j[1]}", callback_data=f"voto:{j[0]}")]
        for j in vivos
    ]
    ctx.bot_data[f"votos_{chat_key}"] = {}

    await message.reply_text(
        t(chat_key, "quien_es_impostor").format(n=len(vivos)),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def btn_abrir_votar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_key = get_chat_key(update)
    user = update.effective_user

    partida = get_partida(chat_key)
    if not partida or partida[2] != "jugando":
        await query.answer(t(chat_key, "no_partida_votacion"), show_alert=True)
        return
    if partida[8] != user.id:
        await query.answer(t(chat_key, "solo_creador_votar"), show_alert=True)
        return

    await query.answer()
    await _abrir_votacion(chat_key, ctx, query.message)


async def cmd_votar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_key = get_chat_key(update)
    partida = get_partida(chat_key)
    user = update.effective_user

    if not partida or partida[2] != "jugando":
        await update.message.reply_text(t(chat_key, "no_partida_curso"))
        return
    if partida[8] != user.id:
        await update.message.reply_text(t(chat_key, "solo_creador_votar"))
        return

    await _abrir_votacion(chat_key, ctx, update.message)


async def btn_voto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_key = get_chat_key(update)
    voter_id = query.from_user.id

    partida = get_partida(chat_key)
    if not partida or partida[2] != "jugando":
        await query.answer(t(chat_key, "no_partida_votacion"), show_alert=True)
        return

    vivos_ids = get_vivos(chat_key)
    if voter_id not in vivos_ids:
        await query.answer(t(chat_key, "no_puedes_votar"), show_alert=True)
        return

    jugadores = get_jugadores_activos(chat_key)
    vivos = [j for j in jugadores if j[0] in vivos_ids]

    votado_id = int(query.data.split(":")[1])
    votos = ctx.bot_data.setdefault(f"votos_{chat_key}", {})

    if voter_id in votos:
        await query.answer(t(chat_key, "voto_ya"), show_alert=True)
        return

    votos[voter_id] = votado_id
    await query.answer(t(chat_key, "voto_ok"))

    faltantes = len(vivos) - len(votos)
    sufijo_faltantes = t(chat_key, "faltan_votos").format(n=faltantes) if faltantes > 0 else ""
    await query.message.reply_text(
        t(chat_key, "voto_confirmado").format(nombre=esc(query.from_user.first_name), faltantes=sufijo_faltantes),
        parse_mode="MarkdownV2"
    )

    if len(votos) >= len(vivos):
        await resolver_votacion(chat_key, ctx, partida, jugadores, vivos, votos, query.message)


async def btn_revoto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_key = get_chat_key(update)
    voter_id = query.from_user.id

    partida = get_partida(chat_key)
    if not partida or partida[2] != "jugando":
        await query.answer(t(chat_key, "no_partida_votacion"), show_alert=True)
        return

    vivos_ids = get_vivos(chat_key)
    if voter_id not in vivos_ids:
        await query.answer(t(chat_key, "no_puedes_votar"), show_alert=True)
        return

    datos = ctx.bot_data.get(f"revotacion_{chat_key}")
    if not datos:
        await query.answer(t(chat_key, "no_revotacion"), show_alert=True)
        return

    votado_id = int(query.data.split(":")[1])
    if votado_id not in datos["candidatos"]:
        await query.answer(t(chat_key, "voto_invalido"), show_alert=True)
        return

    votos = ctx.bot_data.setdefault(f"votos_{chat_key}", {})
    if voter_id in votos:
        await query.answer(t(chat_key, "voto_ya"), show_alert=True)
        return

    votos[voter_id] = votado_id
    await query.answer(t(chat_key, "voto_ok"))

    vivos = datos["vivos"]
    faltantes = len(vivos) - len(votos)
    sufijo_faltantes = t(chat_key, "faltan_votos").format(n=faltantes) if faltantes > 0 else ""
    await query.message.reply_text(
        t(chat_key, "voto_confirmado_revoto").format(nombre=esc(query.from_user.first_name), faltantes=sufijo_faltantes),
        parse_mode="MarkdownV2"
    )

    if len(votos) >= len(vivos):
        ctx.bot_data.pop(f"revotacion_{chat_key}", None)

        conteo2 = {}
        for v in votos.values():
            conteo2[v] = conteo2.get(v, 0) + 1

        max_votos2 = max(conteo2.values())
        empatados2 = [uid for uid, cnt in conteo2.items() if cnt == max_votos2]
        jugadores = datos["jugadores"]

        if len(empatados2) > 1:
            await query.message.reply_text(
                t(chat_key, "segundo_empate"),
                parse_mode="MarkdownV2"
            )
            partida_fresca = get_partida(chat_key)
            vivos_ids_actual = get_vivos(chat_key)
            jugadores_frescos = get_jugadores_activos(chat_key)
            impostor_ids_set2 = set(int(i) for i in partida_fresca[5].split(","))
            await _nueva_ronda_pistas(
                chat_key, ctx, jugadores_frescos, vivos_ids_actual,
                impostor_ids_set2, partida_fresca[4], partida_fresca[3], query.message
            )
            return

        vivos_ids_actual = get_vivos(chat_key)
        vivos_actual = [j for j in jugadores if j[0] in vivos_ids_actual]
        await resolver_votacion(chat_key, ctx, partida, jugadores, vivos_actual, votos, query.message)


async def resolver_votacion(chat_key, ctx, partida, jugadores, vivos, votos, message):
    conteo = {}
    for votado in votos.values():
        conteo[votado] = conteo.get(votado, 0) + 1

    max_votos = max(conteo.values())
    empatados = [uid for uid, cnt in conteo.items() if cnt == max_votos]

    # ── Empate → revotación ──
    if len(empatados) > 1:
        vivos_ids = get_vivos(chat_key)
        jugadores_frescos = get_jugadores_activos(chat_key)
        vivos_frescos = [j for j in jugadores_frescos if j[0] in vivos_ids]
        nombre_map = {j[0]: j[1] for j in jugadores_frescos}
        nombres_empatados = " y ".join(f"*{esc(nombre_map.get(e, '?'))}*" for e in empatados)

        ctx.bot_data[f"revotacion_{chat_key}"] = {
            "candidatos": empatados,
            "partida": partida,
            "jugadores": jugadores_frescos,
            "vivos": vivos_frescos,
        }
        ctx.bot_data[f"votos_{chat_key}"] = {}

        keyboard = [
            [InlineKeyboardButton(f"🗳️ {nombre_map.get(uid, '?')}", callback_data=f"revoto:{uid}")]
            for uid in empatados
        ]
        await message.reply_text(
            t(chat_key, "empate").format(nombres=nombres_empatados, n=max_votos),
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ── Sin empate: procesar eliminación ──
    eliminado_id = empatados[0]

    # Recargar todo fresco desde DB para evitar datos desactualizados
    partida = get_partida(chat_key)
    if not partida:
        return

    impostor_ids_raw = partida[5] or ""
    impostor_ids_set = set(int(i) for i in impostor_ids_raw.split(",") if i.strip())

    todos_jugadores = get_jugadores_activos(chat_key)
    vivos_ids_frescos = get_vivos(chat_key)
    vivos = [j for j in todos_jugadores if j[0] in vivos_ids_frescos]

    impostor_names_map = {j[0]: j[1] for j in todos_jugadores}
    impostores = [(uid, impostor_names_map.get(uid, str(uid))) for uid in impostor_ids_set]

    eliminado = next((j for j in vivos if j[0] == eliminado_id), None)
    if eliminado is None:
        eliminado = (eliminado_id, impostor_names_map.get(eliminado_id, str(eliminado_id)))

    logger.info(f"[resolver_votacion] eliminado_id={eliminado_id} impostor_ids={impostor_ids_raw} impostor_ids_set={impostor_ids_set} es_impostor={eliminado_id in impostor_ids_set}")
    palabra = partida[4]
    categoria = partida[3]

    nombre_map = {j[0]: j[1] for j in todos_jugadores}
    detalle_votos = "\n".join(
        f"  • {esc(nombre_map.get(v_from, '?'))} → {esc(nombre_map.get(v_to, '?'))}"
        for v_from, v_to in votos.items()
    )

    es_impostor = eliminado_id in impostor_ids_set
    etiqueta = t(chat_key, "era_impostor") if es_impostor else t(chat_key, "era_inocente")

    vivos_restantes_ids = eliminar_de_vivos(chat_key, eliminado_id)
    impostores_vivos = [j for j in impostores if j[0] in vivos_restantes_ids]
    inocentes_vivos_ids = [v for v in vivos_restantes_ids if v not in impostor_ids_set]

    # Transferir creador si fue eliminado
    if eliminado_id == partida[8] and vivos_restantes_ids:
        nuevo_creador = vivos_restantes_ids[0]
        with get_conn() as conn:
            conn.execute(
                "UPDATE partidas SET creador_id=? WHERE chat_key=?",
                (nuevo_creador, chat_key)
            )
        nombre_nuevo = nombre_map.get(nuevo_creador, "?")
        await message.reply_text(
            t(chat_key, "nuevo_creador").format(nombre=esc(nombre_nuevo)),
            parse_mode="MarkdownV2"
        )

    await message.reply_text(
        t(chat_key, "resultado_votacion").format(
            nombre=esc(eliminado[1]), etiqueta=etiqueta, detalle=detalle_votos
        ),
        parse_mode="MarkdownV2"
    )

    # ── Impostor votado → oportunidad de adivinar ──
    if es_impostor:
        with get_conn() as conn:
            conn.execute("UPDATE partidas SET estado='adivinando' WHERE chat_key=?", (chat_key,))

        ctx.bot_data[f"adivinando_{chat_key}"] = {
            "impostor_id": eliminado_id,
            "impostor_ids_set": impostor_ids_set,
            "palabra": palabra,
            "categoria": categoria,
            "jugadores": todos_jugadores,
            "vivos_restantes_ids": vivos_restantes_ids,
            "impostores_vivos": impostores_vivos,
            "inocentes_vivos_ids": inocentes_vivos_ids,
            "detalle_votos": detalle_votos,
            "partida": partida,
            "impostores": impostores,
        }

        await message.reply_text(
            t(chat_key, "ultima_oportunidad").format(nombre=esc(eliminado[1]), cat=esc(categoria)),
            parse_mode="MarkdownV2"
        )
        chat_id = message.chat.id
        thread_id = get_thread_id(chat_key)
        tarea = asyncio.create_task(
            _timer_adivinanza(chat_key, eliminado[0], chat_id, thread_id, ctx)
        )
        ctx.bot_data[f"timer_adiv_{chat_key}"] = tarea
        return

    # ── Inocente votado ──
    if not impostores_vivos:
        await _fin_grupo_gana(chat_key, ctx, todos_jugadores, impostores, palabra, categoria, detalle_votos, message)
        return

    inocentes_restantes = [v for v in vivos_restantes_ids if v not in impostor_ids_set]
    if len(inocentes_restantes) <= 1:
        await _fin_impostores_ganan(
            chat_key, ctx, partida, todos_jugadores, impostores,
            None, palabra, categoria, detalle_votos, message, razon="supervivencia"
        )
        return

    await _nueva_ronda_pistas(chat_key, ctx, todos_jugadores, vivos_restantes_ids, impostor_ids_set, palabra, categoria, message)


TIMER_ADIV_SEGUNDOS = 30

async def _timer_adivinanza(chat_key, impostor_id, chat_id, thread_id, ctx):
    """Si el impostor no adivina en 30s, el grupo gana automáticamente."""
    await asyncio.sleep(TIMER_ADIV_SEGUNDOS)
    try:
        await _timer_adivinanza_body(chat_key, impostor_id, chat_id, thread_id, ctx)
    except Exception as e:
        logger.error(f"[TIMER_ADIV] excepcion no capturada: {e}", exc_info=True)

async def _timer_adivinanza_body(chat_key, impostor_id, chat_id, thread_id, ctx):

    # Si ya fue respondido (datos limpiados), ignorar
    datos = ctx.bot_data.pop(f"adivinando_{chat_key}", None)
    if not datos:
        return
    # Verificar que sigue siendo el mismo impostor esperando
    if datos.get("impostor_id") != impostor_id:
        return

    partida = get_partida(chat_key)
    if not partida or partida[2] != "adivinando":
        return

    jugadores = datos["jugadores"]
    impostores = datos["impostores"]
    palabra = datos["palabra"]
    categoria = datos["categoria"]
    detalle_votos = datos["detalle_votos"]
    impostor_ids_set = datos["impostor_ids_set"]
    vivos_restantes_ids = datos["vivos_restantes_ids"]
    impostores_vivos = datos["impostores_vivos"]
    inocentes_vivos_ids = datos["inocentes_vivos_ids"]

    nombre_j = next((j[1] for j in jugadores if j[0] == impostor_id), "?")

    # Si hay un intento pendiente (escribió pero no confirmó), procesarlo automáticamente
    intento = datos.get("intento")
    if intento:
        msg_auto = await ctx.bot.send_message(
            chat_id,
            t(chat_key, "pista_auto_confirmada"),
            parse_mode="MarkdownV2",
            message_thread_id=thread_id
        )
        if normalizar(intento) == normalizar(palabra):
            msg = await ctx.bot.send_message(
                chat_id,
                t(chat_key, "adivino").format(nombre=esc(nombre_j), palabra=esc(palabra)),
                parse_mode="MarkdownV2",
                message_thread_id=thread_id
            )
            await _fin_impostores_ganan(
                chat_key, ctx, partida, jugadores, impostores,
                None, palabra, categoria, detalle_votos, msg
            )
        else:
            msg = await ctx.bot.send_message(
                chat_id,
                t(chat_key, "incorrecto").format(nombre=esc(nombre_j), texto=esc(intento.lower())),
                parse_mode="MarkdownV2",
                message_thread_id=thread_id
            )
            if not impostores_vivos:
                await _fin_grupo_gana(chat_key, ctx, jugadores, impostores, palabra, categoria, detalle_votos, msg)
                return
            inocentes_restantes = [v for v in vivos_restantes_ids if v not in impostor_ids_set]
            if len(inocentes_restantes) <= 1:
                await _fin_impostores_ganan(
                    chat_key, ctx, partida, jugadores, impostores,
                    None, palabra, categoria, detalle_votos, msg, razon="supervivencia"
                )
                return
            await _nueva_ronda_pistas(chat_key, ctx, jugadores, vivos_restantes_ids, impostor_ids_set, palabra, categoria, msg)
        return

    # Sin intento → timeout real, el grupo gana
    msg_text = t(chat_key, "adiv_timeout").format(nombre=esc_link(nombre_j), uid=impostor_id)
    msg = await ctx.bot.send_message(chat_id, msg_text, parse_mode="MarkdownV2", message_thread_id=thread_id)

    await _fin_grupo_gana(chat_key, ctx, jugadores, impostores, palabra, categoria, detalle_votos, msg)


TIMER_TURNO_SEGUNDOS = 60

async def _timer_turno(chat_key, user_id, chat_id, thread_id, ctx):
    """Callback que se ejecuta cuando expira el tiempo de turno."""
    await asyncio.sleep(TIMER_TURNO_SEGUNDOS)
    try:
        await _timer_turno_body(chat_key, user_id, chat_id, thread_id, ctx)
    except Exception as e:
        logger.error(f"[TIMER_TURNO] excepcion no capturada: {e}", exc_info=True)

async def _timer_turno_body(chat_key, user_id, chat_id, thread_id, ctx):

    turno_data = ctx.bot_data.get(f"turno_{chat_key}")
    if not turno_data:
        return
    orden = turno_data["orden"]
    index = turno_data["index"]
    # Si ya no es el turno de este jugador, ignorar
    if index >= len(orden) or orden[index] != user_id:
        return

    jugadores = get_jugadores_activos(chat_key)
    nombre_j = next((j[1] for j in jugadores if j[0] == user_id), "?")

    pista_pendiente = turno_data.pop("pista_pendiente", None)

    if pista_pendiente:
        # Tenía algo escrito → auto-confirmar
        await ctx.bot.send_message(
            chat_id,
            t(chat_key, "turno_timeout_autoconf").format(nombre=esc_link(nombre_j), uid=user_id),
            parse_mode="MarkdownV2",
            message_thread_id=thread_id
        )
        await ctx.bot.send_message(
            chat_id,
            f"💬 *{esc(nombre_j)}*: *{esc(pista_pendiente)}*",
            parse_mode="MarkdownV2",
            message_thread_id=thread_id
        )
    else:
        # No escribió nada → saltar turno
        await ctx.bot.send_message(
            chat_id,
            t(chat_key, "turno_timeout").format(nombre=esc_link(nombre_j), uid=user_id),
            parse_mode="MarkdownV2",
            message_thread_id=thread_id
        )

    turno_data["ya_dieron_pista"].add(user_id)
    siguiente_index = index + 1
    turno_data["index"] = siguiente_index
    turno_data.setdefault("intentos_pista", {})[user_id] = 0

    if siguiente_index >= len(orden):
        ronda_pistas = turno_data.get("ronda_pistas", 1)
        jugadores_iniciales = turno_data.get("jugadores_iniciales", len(orden))

        if jugadores_iniciales == 3 and ronda_pistas == 1:
            ctx.bot_data.pop(f"turno_{chat_key}", None)
            vivos_ids = get_vivos(chat_key)
            vivos = [j for j in jugadores if j[0] in vivos_ids]
            nuevo_orden = list(vivos)
            random.shuffle(nuevo_orden)
            turno_lista = "\n".join(f"  {i+1}\\. {esc(j[1])}" for i, j in enumerate(nuevo_orden))
            ctx.bot_data[f"turno_{chat_key}"] = {
                "orden": [j[0] for j in nuevo_orden],
                "index": 0,
                "ya_dieron_pista": set(),
                "ronda_pistas": 2,
                "jugadores_iniciales": jugadores_iniciales,
                "intentos_pista": {}
            }
            await ctx.bot.send_message(chat_id, t(chat_key, "segunda_ronda").format(orden=turno_lista), parse_mode="MarkdownV2", message_thread_id=thread_id)
            primer = nuevo_orden[0]
            await _anunciar_turno(chat_key, primer[0], primer[1], chat_id, thread_id, ctx)
            return

        ctx.bot_data.pop(f"turno_{chat_key}", None)
        await ctx.bot.send_message(
            chat_id, t(chat_key, "todos_dieron_pista"), parse_mode="MarkdownV2",
            message_thread_id=thread_id,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(chat_key, "btn_abrir_votacion"), callback_data="abrir_votar")]])
        )
        return

    siguiente_id = orden[siguiente_index]
    nombre_sig = next((j[1] for j in jugadores if j[0] == siguiente_id), "?")
    await _anunciar_turno(chat_key, siguiente_id, nombre_sig, chat_id, thread_id, ctx)


async def _anunciar_turno(chat_key, user_id, nombre_j, chat_id, thread_id, ctx):
    """Anuncia el turno e inicia el timer de 1 minuto."""
    # Cancelar timer anterior si existe, pero nunca el task propio
    tarea_actual = asyncio.current_task()
    tarea_anterior = ctx.bot_data.pop(f"timer_{chat_key}", None)
    if tarea_anterior and tarea_anterior is not tarea_actual:
        tarea_anterior.cancel()

    await asyncio.shield(ctx.bot.send_message(
        chat_id,
        t(chat_key, "turno").format(nombre=esc_link(nombre_j), uid=user_id),
        parse_mode="MarkdownV2",
        message_thread_id=thread_id
    ))

    # Iniciar nuevo timer
    tarea = asyncio.create_task(_timer_turno(chat_key, user_id, chat_id, thread_id, ctx))
    ctx.bot_data[f"timer_{chat_key}"] = tarea


async def _nueva_ronda_pistas(chat_key, ctx, jugadores, vivos_ids, impostor_ids_set, palabra, categoria, message):
    vivos = [j for j in jugadores if j[0] in vivos_ids]
    orden = list(vivos)
    random.shuffle(orden)
    turno_lista = "\n".join(f"  {i+1}\\. {esc(j[1])}" for i, j in enumerate(orden))

    ctx.bot_data[f"turno_{chat_key}"] = {
        "orden": [j[0] for j in orden],
        "index": 0,
        "ya_dieron_pista": set(),
        "ronda_pistas": 2,
        "jugadores_iniciales": len(jugadores),
        "intentos_pista": {}
    }

    with get_conn() as conn:
        conn.execute("UPDATE partidas SET estado='jugando' WHERE chat_key=?", (chat_key,))

    await message.reply_text(
        t(chat_key, "nueva_ronda_pistas").format(n=len(vivos), orden=turno_lista),
        parse_mode="MarkdownV2"
    )

    primer = orden[0]
    chat_id = message.chat.id
    thread_id = get_thread_id(chat_key)
    await _anunciar_turno(chat_key, primer[0], primer[1], chat_id, thread_id, ctx)


async def btn_confirmar_pista(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_key = get_chat_key(update)
    user = query.from_user

    turno_data = ctx.bot_data.get(f"turno_{chat_key}")
    if not turno_data:
        await query.answer(t(chat_key, "no_tu_turno"), show_alert=True)
        return

    orden = turno_data["orden"]
    index = turno_data["index"]

    if user.id != orden[index]:
        await query.answer(t(chat_key, "no_tu_turno"), show_alert=True)
        return

    await query.answer(t(chat_key, "pista_confirmada"))

    # Cancelar timer activo
    tarea = ctx.bot_data.pop(f"timer_{chat_key}", None)
    if tarea:
        tarea.cancel()

    pista_texto = turno_data.pop("pista_pendiente", None)
    turno_data.setdefault("intentos_pista", {})[user.id] = 0  # resetear contador
    if pista_texto:
        try:
            await query.message.edit_text(
                f"💬 *{esc(nombre(user))}*: *{esc(pista_texto)}*",
                parse_mode="MarkdownV2"
            )
        except Exception:
            await query.message.delete()
    else:
        await query.message.delete()

    turno_data["ya_dieron_pista"].add(user.id)
    siguiente_index = index + 1
    turno_data["index"] = siguiente_index
    chat_id = query.message.chat.id
    thread_id = get_thread_id(chat_key)

    if siguiente_index >= len(orden):
        ronda_pistas = turno_data.get("ronda_pistas", 1)
        jugadores_iniciales = turno_data.get("jugadores_iniciales", len(orden))

        if jugadores_iniciales == 3 and ronda_pistas == 1:
            ctx.bot_data.pop(f"turno_{chat_key}", None)
            jugadores = get_jugadores_activos(chat_key)
            vivos_ids = get_vivos(chat_key)
            vivos = [j for j in jugadores if j[0] in vivos_ids]
            nuevo_orden = list(vivos)
            random.shuffle(nuevo_orden)
            turno_lista = "\n".join(f"  {i+1}\\. {esc(j[1])}" for i, j in enumerate(nuevo_orden))

            ctx.bot_data[f"turno_{chat_key}"] = {
                "orden": [j[0] for j in nuevo_orden],
                "index": 0,
                "ya_dieron_pista": set(),
                "ronda_pistas": 2,
                "jugadores_iniciales": jugadores_iniciales,
                "intentos_pista": {}
            }

            await ctx.bot.send_message(
                chat_id,
                t(chat_key, "segunda_ronda").format(orden=turno_lista),
                parse_mode="MarkdownV2",
                message_thread_id=thread_id
            )
            primer = nuevo_orden[0]
            await _anunciar_turno(chat_key, primer[0], primer[1], chat_id, thread_id, ctx)
            return

        ctx.bot_data.pop(f"turno_{chat_key}", None)
        await ctx.bot.send_message(
            chat_id,
            t(chat_key, "todos_dieron_pista"),
            parse_mode="MarkdownV2",
            message_thread_id=thread_id,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(t(chat_key, "btn_abrir_votacion"), callback_data="abrir_votar")
            ]])
        )
        return

    siguiente_id = orden[siguiente_index]
    jugadores = get_jugadores_activos(chat_key)
    nombre_siguiente = next((j[1] for j in jugadores if j[0] == siguiente_id), "?")

    await _anunciar_turno(chat_key, siguiente_id, nombre_siguiente, chat_id, thread_id, ctx)


async def handle_adivinanza(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    chat_key = get_chat_key(update)
    user = update.effective_user
    texto = update.message.text.strip()

    partida = get_partida(chat_key)
    if not partida:
        return

    # ── Modo adivinanza del impostor ──
    if partida[2] == "adivinando":
        datos = ctx.bot_data.get(f"adivinando_{chat_key}")
        if not datos or user.id != datos["impostor_id"]:
            return

        palabra = datos["palabra"]
        jugadores = datos["jugadores"]
        categoria = datos["categoria"]
        detalle_votos = datos["detalle_votos"]
        impostores = datos["impostores"]
        vivos_restantes_ids = datos["vivos_restantes_ids"]
        impostores_vivos = datos["impostores_vivos"]
        inocentes_vivos_ids = datos["inocentes_vivos_ids"]
        impostor_ids_set = datos["impostor_ids_set"]

        # Cancelar timer y procesar directamente sin confirmación
        ctx.bot_data.pop(f"adivinando_{chat_key}", None)
        tarea_adiv = ctx.bot_data.pop(f"timer_adiv_{chat_key}", None)
        if tarea_adiv:
            tarea_adiv.cancel()

        chat_id = update.effective_chat.id
        thread_id = get_thread_id(chat_key)

        async def send(text):
            return await ctx.bot.send_message(chat_id, text, parse_mode="MarkdownV2", message_thread_id=thread_id)

        if normalizar(texto) == normalizar(palabra):
            msg = await send(t(chat_key, "adivino").format(nombre=esc(nombre(user)), palabra=esc(palabra)))
            await _fin_impostores_ganan(
                chat_key, ctx, partida, jugadores, impostores,
                None, palabra, categoria, detalle_votos, msg
            )
        else:
            msg = await send(t(chat_key, "incorrecto").format(nombre=esc(nombre(user)), texto=esc(texto.lower())))
            if not impostores_vivos:
                await _fin_grupo_gana(chat_key, ctx, jugadores, impostores, palabra, categoria, detalle_votos, msg)
                return
            inocentes_restantes = [v for v in vivos_restantes_ids if v not in impostor_ids_set]
            if len(inocentes_restantes) <= 1:
                await _fin_impostores_ganan(
                    chat_key, ctx, partida, jugadores, impostores,
                    None, palabra, categoria, detalle_votos, msg, razon="supervivencia"
                )
                return
            await _nueva_ronda_pistas(chat_key, ctx, jugadores, vivos_restantes_ids, impostor_ids_set, palabra, categoria, msg)
        return

    # ── Modo pistas: detectar turno ──
    if partida[2] != "jugando":
        return

    turno_data = ctx.bot_data.get(f"turno_{chat_key}")
    if not turno_data:
        return

    orden = turno_data["orden"]
    index = turno_data["index"]

    if index >= len(orden) or user.id != orden[index]:
        return

    impostor_ids_raw = partida[5] or ""
    impostor_ids_set = set(int(i) for i in impostor_ids_raw.split(",") if i.strip())
    if user.id in impostor_ids_set and normalizar(texto) == normalizar(partida[4]):
        todos_jugadores = get_jugadores_activos(chat_key)
        impostores = [(uid, next((j[1] for j in todos_jugadores if j[0] == uid), str(uid))) for uid in impostor_ids_set]
        ctx.bot_data.pop(f"turno_{chat_key}", None)
        chat_id = update.effective_chat.id
        thread_id = get_thread_id(chat_key)
        await ctx.bot.send_message(
            chat_id,
            t(chat_key, "adivino").format(nombre=esc(nombre(user)), palabra=esc(partida[4])),
            parse_mode="MarkdownV2",
            message_thread_id=thread_id
        )
        msg = update.message
        nombre_map = {j[0]: j[1] for j in todos_jugadores}
        await _fin_impostores_ganan(
            chat_key, ctx, partida, todos_jugadores, impostores,
            None, partida[4], partida[3], {}, msg
        )
        return

    keyboard = [[InlineKeyboardButton(
        t(chat_key, "confirmar_pista_btn"),
        callback_data=f"confirmar_pista:{user.id}"
    )]]
    turno_data["pista_pendiente"] = texto

    intentos = turno_data.setdefault("intentos_pista", {})
    intentos[user.id] = intentos.get(user.id, 0) + 1

    if intentos[user.id] >= 3:
        # Tercer intento: confirmar automáticamente sin botón
        await update.message.reply_text(
            t(chat_key, "pista_auto_confirmada"),
            parse_mode="MarkdownV2"
        )
        # Simular confirmación directamente
        chat_id = update.effective_chat.id
        thread_id = get_thread_id(chat_key)
        turno_data.pop("pista_pendiente", None)
        intentos[user.id] = 0

        # Cancelar timer activo
        tarea = ctx.bot_data.pop(f"timer_{chat_key}", None)
        if tarea:
            tarea.cancel()

        turno_data["ya_dieron_pista"].add(user.id)
        siguiente_index = index + 1
        turno_data["index"] = siguiente_index

        # Mostrar pista en negrita en el chat
        try:
            await update.message.reply_text(
                f"💬 *{esc(nombre(user))}*: *{esc(texto)}*",
                parse_mode="MarkdownV2"
            )
        except Exception:
            pass

        if siguiente_index >= len(orden):
            ronda_pistas = turno_data.get("ronda_pistas", 1)
            jugadores_iniciales = turno_data.get("jugadores_iniciales", len(orden))

            if jugadores_iniciales == 3 and ronda_pistas == 1:
                ctx.bot_data.pop(f"turno_{chat_key}", None)
                jugadores_frescos = get_jugadores_activos(chat_key)
                vivos_ids = get_vivos(chat_key)
                vivos = [j for j in jugadores_frescos if j[0] in vivos_ids]
                nuevo_orden = list(vivos)
                random.shuffle(nuevo_orden)
                turno_lista = "\n".join(f"  {i+1}\\. {esc(j[1])}" for i, j in enumerate(nuevo_orden))
                ctx.bot_data[f"turno_{chat_key}"] = {
                    "orden": [j[0] for j in nuevo_orden],
                    "index": 0,
                    "ya_dieron_pista": set(),
                    "ronda_pistas": 2,
                    "jugadores_iniciales": jugadores_iniciales,
                    "intentos_pista": {}
                }
                await ctx.bot.send_message(chat_id, t(chat_key, "segunda_ronda").format(orden=turno_lista), parse_mode="MarkdownV2", message_thread_id=thread_id)
                primer = nuevo_orden[0]
                await _anunciar_turno(chat_key, primer[0], primer[1], chat_id, thread_id, ctx)
                return

            ctx.bot_data.pop(f"turno_{chat_key}", None)
            await ctx.bot.send_message(
                chat_id, t(chat_key, "todos_dieron_pista"), parse_mode="MarkdownV2",
                message_thread_id=thread_id,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(chat_key, "btn_abrir_votacion"), callback_data="abrir_votar")]])
            )
            return

        siguiente_id = orden[siguiente_index]
        jugadores_frescos = get_jugadores_activos(chat_key)
        nombre_siguiente = next((j[1] for j in jugadores_frescos if j[0] == siguiente_id), "?")
        await _anunciar_turno(chat_key, siguiente_id, nombre_siguiente, chat_id, thread_id, ctx)
        return

    await update.message.reply_text(
        t(chat_key, "confirmar_pista_msg").format(pista=esc(texto)),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )



async def btn_confirmar_adivinanza(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_key = get_chat_key(update)
    user = query.from_user

    partida = get_partida(chat_key)
    if not partida or partida[2] != "adivinando":
        await query.answer()
        return

    datos = ctx.bot_data.get(f"adivinando_{chat_key}")
    if not datos or user.id != datos["impostor_id"]:
        await query.answer()
        return

    texto = datos.get("intento")
    if not texto:
        await query.answer()
        return

    palabra = datos["palabra"]
    jugadores = datos["jugadores"]
    categoria = datos["categoria"]
    detalle_votos = datos["detalle_votos"]
    impostores = datos["impostores"]
    vivos_restantes_ids = datos["vivos_restantes_ids"]
    impostores_vivos = datos["impostores_vivos"]
    inocentes_vivos_ids = datos["inocentes_vivos_ids"]
    impostor_ids_set = datos["impostor_ids_set"]

    ctx.bot_data.pop(f"adivinando_{chat_key}", None)
    tarea_adiv = ctx.bot_data.pop(f"timer_adiv_{chat_key}", None)
    if tarea_adiv:
        tarea_adiv.cancel()
    await query.answer(t(chat_key, "pista_confirmada"))
    await query.message.delete()

    chat_id = query.message.chat.id
    thread_id = get_thread_id(chat_key)

    async def send(text):
        return await ctx.bot.send_message(chat_id, text, parse_mode="MarkdownV2", message_thread_id=thread_id)

    if normalizar(texto) == normalizar(palabra):
        msg = await send(t(chat_key, "adivino").format(nombre=esc(nombre(user)), palabra=esc(palabra)))
        await _fin_impostores_ganan(
            chat_key, ctx, partida, jugadores, impostores,
            None, palabra, categoria, detalle_votos, msg
        )
    else:
        msg = await send(t(chat_key, "incorrecto").format(nombre=esc(nombre(user)), texto=esc(texto.lower())))
        if not impostores_vivos:
            await _fin_grupo_gana(chat_key, ctx, jugadores, impostores, palabra, categoria, detalle_votos, msg)
            return
        inocentes_restantes = [v for v in vivos_restantes_ids if v not in impostor_ids_set]
        if len(inocentes_restantes) <= 1:
            await _fin_impostores_ganan(
                chat_key, ctx, partida, jugadores, impostores,
                None, palabra, categoria, detalle_votos, msg, razon="supervivencia"
            )
            return
        await _nueva_ronda_pistas(chat_key, ctx, jugadores, vivos_restantes_ids, impostor_ids_set, palabra, categoria, msg)


async def _fin_grupo_gana(chat_key, ctx, jugadores, impostores, palabra, categoria, detalle_votos, _unused=None, bonus=False):
    logger.info(f"[FIN_GRUPO] iniciando chat_key={chat_key} palabra={palabra}")
    try:
        tarea_actual = asyncio.current_task()
        tarea = ctx.bot_data.pop(f"timer_{chat_key}", None)
        if tarea and tarea is not tarea_actual: tarea.cancel()
        tarea_adiv = ctx.bot_data.pop(f"timer_adiv_{chat_key}", None)
        if tarea_adiv and tarea_adiv is not tarea_actual: tarea_adiv.cancel()

        impostor_ids_set = set(j[0] for j in impostores)
        for j in jugadores:
            if j[0] not in impostor_ids_set:
                sumar_victoria(chat_key, j[0])
                sumar_victoria_inocente(chat_key, j[0])
        for imp in impostores:
            sumar_derrota(chat_key, imp[0])
        logger.info(f"[FIN_GRUPO] puntos sumados")

        with get_conn() as conn:
            row = conn.execute("SELECT chat_id FROM partidas WHERE chat_key=?", (chat_key,)).fetchone()
            conn.execute("INSERT INTO historial (chat_key, ganador, palabra, categoria) VALUES (?,?,?,?)",
                         (chat_key, "grupo", palabra, categoria))
            conn.execute("UPDATE partidas SET estado=\'terminada\' WHERE chat_key=?", (chat_key,))
        logger.info(f"[FIN_GRUPO] DB actualizada, row={row}")

        chat_id = row[0] if row else int(chat_key.split("_")[0])
        thread_id = get_thread_id(chat_key)
        marcador = get_marcador_global(chat_key)
        logger.info(f"[FIN_GRUPO] chat_id={chat_id} marcador={len(marcador)} jugadores")

        nombres_impostores = ", ".join(f"*{esc(i[1])}*" for i in impostores)
        texto_final = t(chat_key, "grupo_gana").format(
            impostores=nombres_impostores, palabra=esc(palabra),
            cat=esc(categoria)
        )
        logger.info(f"[FIN_GRUPO] texto generado len={len(texto_final)}, enviando...")
        await asyncio.shield(ctx.bot.send_message(chat_id, texto_final, parse_mode="MarkdownV2", message_thread_id=thread_id))
        img_buf = generar_imagen_marcador(chat_key, marcador)
        if img_buf:
            await asyncio.shield(ctx.bot.send_photo(chat_id, photo=img_buf, message_thread_id=thread_id))
        logger.info(f"[FIN_GRUPO] mensaje enviado OK")
    except BaseException as e:
        logger.error(f"[FIN_GRUPO] ERROR tipo={type(e).__name__}: {e}", exc_info=True)
        try:
            with get_conn() as conn:
                row2 = conn.execute("SELECT chat_id FROM partidas WHERE chat_key=?", (chat_key,)).fetchone()
            chat_id2 = row2[0] if row2 else int(chat_key.split("_")[0])
            thread_id2 = get_thread_id(chat_key)
            fb = (f"🎉 ¡El grupo ganó!\n\n"
                  f"Impostores: {', '.join(i[1] for i in impostores)}\n"
                  f"Palabra: {palabra} ({categoria})\n\n"
                  f"Usa /playimpostor para otra ronda")
            await ctx.bot.send_message(chat_id2, fb, message_thread_id=thread_id2)
        except Exception as e2:
            logger.error(f"[FIN_GRUPO] fallback fallido: {e2}")


async def _fin_impostores_ganan(chat_key, ctx, partida, jugadores, impostores, eliminado, palabra, categoria, detalle_votos, _unused=None, razon=None):
    logger.info(f"[FIN_IMPOSTORES] iniciando chat_key={chat_key} palabra={palabra} razon={razon}")
    try:
        tarea_actual = asyncio.current_task()
        tarea = ctx.bot_data.pop(f"timer_{chat_key}", None)
        if tarea and tarea is not tarea_actual: tarea.cancel()
        tarea_adiv = ctx.bot_data.pop(f"timer_adiv_{chat_key}", None)
        if tarea_adiv and tarea_adiv is not tarea_actual: tarea_adiv.cancel()

        impostor_ids_set = set(j[0] for j in impostores)
        for imp in impostores:
            sumar_victoria(chat_key, imp[0])
            sumar_victoria_impostor(chat_key, imp[0])
        for j in jugadores:
            if j[0] not in impostor_ids_set:
                sumar_derrota(chat_key, j[0])
        logger.info(f"[FIN_IMPOSTORES] puntos sumados")

        with get_conn() as conn:
            row = conn.execute("SELECT chat_id FROM partidas WHERE chat_key=?", (chat_key,)).fetchone()
            conn.execute("INSERT INTO historial (chat_key, ganador, palabra, categoria) VALUES (?,?,?,?)",
                         (chat_key, "impostor", palabra, categoria))
            conn.execute("UPDATE partidas SET estado=\'terminada\' WHERE chat_key=?", (chat_key,))
        logger.info(f"[FIN_IMPOSTORES] DB actualizada, row={row}")

        chat_id = row[0] if row else int(chat_key.split("_")[0])
        thread_id = get_thread_id(chat_key)
        marcador = get_marcador_global(chat_key)
        logger.info(f"[FIN_IMPOSTORES] chat_id={chat_id} marcador={len(marcador)} jugadores")

        nombres_impostores = ", ".join(f"*{esc(i[1])}*" for i in impostores)

        if razon == "supervivencia":
            desc = t(chat_key, "desc_supervivencia")
        elif eliminado is None:
            desc = t(chat_key, "desc_adivino")
        else:
            desc = t(chat_key, "desc_error_voto").format(nombre=esc(eliminado[1]))

        texto_final = t(chat_key, "impostores_ganan").format(
            impostores=nombres_impostores, desc=desc,
            palabra=esc(palabra), cat=esc(categoria)
        )
        logger.info(f"[FIN_IMPOSTORES] texto generado len={len(texto_final)}, enviando...")
        await asyncio.shield(ctx.bot.send_message(chat_id, texto_final, parse_mode="MarkdownV2", message_thread_id=thread_id))
        img_buf = generar_imagen_marcador(chat_key, marcador)
        if img_buf:
            await asyncio.shield(ctx.bot.send_photo(chat_id, photo=img_buf, message_thread_id=thread_id))
        logger.info(f"[FIN_IMPOSTORES] mensaje enviado OK")
    except BaseException as e:
        logger.error(f"[FIN_IMPOSTORES] ERROR tipo={type(e).__name__}: {e}", exc_info=True)
        try:
            with get_conn() as conn:
                row2 = conn.execute("SELECT chat_id FROM partidas WHERE chat_key=?", (chat_key,)).fetchone()
            chat_id2 = row2[0] if row2 else int(chat_key.split("_")[0])
            thread_id2 = get_thread_id(chat_key)
            fb = (f"🕵️ ¡Los impostores ganaron!\n\n"
                  f"Eran: {', '.join(i[1] for i in impostores)}\n"
                  f"Palabra: {palabra} ({categoria})\n\n"
                  f"Usa /playimpostor para otra ronda")
            await ctx.bot.send_message(chat_id2, fb, message_thread_id=thread_id2)
        except Exception as e2:
            logger.error(f"[FIN_IMPOSTORES] fallback fallido: {e2}")


def limpiar_nombre_tabla(nombre):
    """Elimina solo emojis y caracteres de control, conserva unicode (coreano, árabe, etc.)"""
    import unicodedata
    resultado = ""
    for c in nombre:
        cat = unicodedata.category(c)
        # Solo excluir emojis (So) y caracteres de control (C*)
        # Conservar letras (L*), números (N*), puntuación (P*), espacios (Zs)
        if cat == "So" or cat.startswith("C"):
            continue
        resultado += c
    return resultado.strip()[:12] or nombre[:12]

def generar_imagen_marcador(chat_key, jugadores):
    """Genera un PNG con la tabla del marcador y devuelve bytes."""
    try:
        FONT_SIZE = 22
        font       = _get_font(FONT_SIZE)
        font_bold  = _get_font(FONT_SIZE, bold=True)
        font_title = _get_font(26, bold=True)
        logger.info(f"[MARCADOR] Unifont={os.path.exists(_FONT_UNIFONT)} CJK={os.path.exists(_FONT_CJK_REGULAR)} NotoSans={os.path.exists(_FONT_REGULAR)}")
        # Colores
        BG     = (30,  30,  46)
        HEADER = (49,  50,  68)
        ROW_A  = (40,  40,  58)
        ROW_B  = (35,  35,  52)
        TEXT   = (220, 220, 235)
        ACCENT = (137, 180, 250)
        GREEN  = (166, 227, 161)
        RED    = (243, 139, 168)
        GRAY   = (150, 150, 170)
        GOLD   = (255, 215,   0)
        SILVER = (192, 192, 192)
        BRONZE = (205, 127,  50)
        LINE   = (69,  71,  90)

        PAD   = 20
        ROW_H = 38
        COL_W = [40, 150, 50, 50, 65]   # #, Jugador, V, D, Bal
        COLS_ES = ["#", "Jugador", "V", "D", "Bal"]
        COLS_EN = ["#", "Player",  "V", "D", "Bal"]
        lang = get_idioma(chat_key)
        COLS = COLS_EN if lang == "en" else COLS_ES

        filas = []
        for j in jugadores:
            nombre_j = limpiar_nombre_tabla(j[1])
            v, d = j[2], j[3]
            bal = v - d
            bal_str = f"+{bal}" if bal > 0 else str(bal)
            filas.append((nombre_j, v, d, bal_str))

        total_w = PAD * 2 + sum(COL_W)
        title_h = 48
        total_h = PAD + title_h + ROW_H + ROW_H * len(filas) + PAD

        img  = Image.new("RGB", (total_w, total_h), BG)
        draw = ImageDraw.Draw(img)

        # Título
        titulo = "Leaderboard" if lang == "en" else "Marcador"
        draw.text((PAD, PAD // 2 + 2), f"  {titulo}", font=font_title, fill=GOLD)

        # Header
        y = PAD + title_h
        draw.rectangle([PAD, y, total_w - PAD, y + ROW_H], fill=HEADER)
        x = PAD + 8
        for col, w in zip(COLS, COL_W):
            draw.text((x, y + 8), col, font=font_bold, fill=ACCENT)
            x += w

        # Filas
        for idx, (nombre_j, v, d, bal) in enumerate(filas):
            y += ROW_H
            draw.rectangle([PAD, y, total_w - PAD, y + ROW_H - 1], fill=ROW_A if idx % 2 == 0 else ROW_B)
            draw.line([PAD, y + ROW_H - 1, total_w - PAD, y + ROW_H - 1], fill=LINE, width=1)

            pos = idx + 1
            x = PAD + 8

            # Número de posición con color
            pos_color = GOLD if pos == 1 else SILVER if pos == 2 else BRONZE if pos == 3 else GRAY
            draw.text((x, y + 8), str(pos), font=font_bold, fill=pos_color)
            x += COL_W[0]

            draw_text_smart(draw, (x, y + 8), nombre_j[:14], FONT_SIZE, TEXT)
            x += COL_W[1]

            draw.text((x, y + 8), str(v), font=font, fill=GREEN)
            x += COL_W[2]

            draw.text((x, y + 8), str(d), font=font, fill=RED)
            x += COL_W[3]

            bal_color = GREEN if bal.startswith("+") else RED if bal.startswith("-") else GRAY
            draw.text((x, y + 8), bal, font=font_bold, fill=bal_color)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf
    except Exception as e:
        logger.error(f"[generar_imagen_marcador] error: {e}")
        return None

def generar_imagen_roles(chat_key, jugadores):
    """Genera un PNG con la tabla de roles y devuelve bytes."""
    try:
        FONT_SIZE = 24
        font       = _get_font(FONT_SIZE)
        font_bold  = _get_font(FONT_SIZE, bold=True)
        font_title = _get_font(28, bold=True)

        BG        = (22,  22,  35)
        HEADER_BG = (42,  44,  66)
        ROW_A     = (32,  33,  50)
        ROW_B     = (28,  29,  45)
        ACCENT    = (130, 170, 255)
        TEXT      = (215, 215, 230)
        GOLD      = (255, 210,  50)
        GRAY      = (130, 130, 150)
        PURPLE    = (200, 140, 255)   # impostor
        TEAL      = (100, 220, 200)   # inocente
        GREEN     = (140, 220, 140)
        LINE      = (55,  57,  80)
        TITLE_BG  = (30,  30,  50)

        lang = get_idioma(chat_key)
        if lang == "en":
            COLS  = ["#", "Player",  "Imp", "W",  "Ino", "W" ]
            titulo = "ROLES"
        else:
            COLS  = ["#", "Jugador", "Imp", "W",  "Ino", "W" ]
            titulo = "ROLES"

        COL_W = [42, 155, 52, 48, 52, 48]

        PAD      = 24
        ROW_H    = 42
        title_h  = 56
        total_w  = PAD * 2 + sum(COL_W)
        total_h  = title_h + ROW_H + ROW_H * len(jugadores) + PAD

        img  = Image.new("RGB", (total_w, total_h), BG)
        draw = ImageDraw.Draw(img)

        # Título
        draw.rectangle([0, 0, total_w, title_h], fill=TITLE_BG)
        draw.text((PAD, 12), titulo, font=font_title, fill=PURPLE)
        draw.rectangle([0, title_h - 2, total_w, title_h], fill=PURPLE)

        # Subheader con leyenda
        y = title_h
        draw.rectangle([0, y, total_w, y + ROW_H], fill=HEADER_BG)
        x = PAD
        for i, (col, w) in enumerate(zip(COLS, COL_W)):
            # Colorear headers de impostor/inocente
            col_color = PURPLE if col in ("Imp",) else TEAL if col in ("Ino",) else ACCENT
            # Las W alternan color según su columna
            if col == "W":
                col_color = PURPLE if i == 3 else TEAL
            draw.text((x, y + 10), col, font=font_bold, fill=col_color)
            x += w
        draw.line([0, y + ROW_H - 1, total_w, y + ROW_H - 1], fill=LINE, width=1)

        # Filas
        for idx, j in enumerate(jugadores):
            y += ROW_H
            draw.rectangle([0, y, total_w, y + ROW_H], fill=ROW_A if idx % 2 == 0 else ROW_B)
            draw.line([0, y + ROW_H - 1, total_w, y + ROW_H - 1], fill=LINE, width=1)

            nom  = limpiar_nombre_tabla(j[0])
            imp  = j[1]   # veces impostor
            ino  = j[2]   # veces inocente
            wimp = j[3]   # victorias impostor
            wino = j[4]   # victorias inocente

            # % de victoria como impostor
            pct_imp = str(wimp)
            pct_ino = str(wino)

            pos = idx + 1
            x = PAD

            draw.text((x, y + 10), str(pos), font=font_bold, fill=GOLD if pos == 1 else GRAY)
            x += COL_W[0]

            draw_text_smart(draw, (x, y + 10), nom[:14], FONT_SIZE, TEXT)
            x += COL_W[1]

            draw.text((x, y + 10), str(imp), font=font_bold, fill=PURPLE)
            x += COL_W[2]

            draw.text((x, y + 10), pct_imp, font=font, fill=GREEN if wimp > 0 else GRAY)
            x += COL_W[3]

            draw.text((x, y + 10), str(ino), font=font_bold, fill=TEAL)
            x += COL_W[4]

            draw.text((x, y + 10), pct_ino, font=font, fill=GREEN if wino > 0 else GRAY)

        draw.rectangle([0, total_h - 3, total_w, total_h], fill=PURPLE)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf
    except Exception as e:
        logger.error(f"[generar_imagen_roles] error: {e}")
        return None

def formatear_tabla(chat_key, jugadores):
    MEDALLAS = {1: "🥇", 2: "🥈", 3: "🥉"}
    filas = []
    for j in jugadores:
        nombre_j = limpiar_nombre_tabla(j[1])
        v = j[2]
        d = j[3]
        balance = v - d
        bal_str = f"+{balance}" if balance > 0 else str(balance)
        filas.append((nombre_j, v, d, bal_str))

    col = t(chat_key, "col_jugador")
    max_nombre = 6
    encabezado = f"    {col:<{max_nombre}}  V    D   Bal"
    separador  = "─" * len(encabezado)
    lineas = [encabezado, separador]
    for i, (nombre_j, v, d, bal) in enumerate(filas, 1):
        prefijo = MEDALLAS.get(i, f"{i:<3} ")
        pad = " " if i in MEDALLAS else ""
        lineas.append(f"{prefijo}{pad}{nombre_j:<{max_nombre}}  {v:<4} {d:<4} {bal}")
    return "```\n" + "\n".join(lineas) + "\n```"


async def cmd_puntaje(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_key = get_chat_key(update)
    jugadores = get_marcador_global(chat_key)

    if not jugadores:
        await update.message.reply_text(
            t(chat_key, "sin_estadisticas"),
            parse_mode="MarkdownV2"
        )
        return

    img_buf = generar_imagen_marcador(chat_key, jugadores)
    if img_buf:
        await update.message.reply_photo(photo=img_buf)
    else:
        tabla = formatear_tabla(chat_key, jugadores)
        await update.message.reply_text(
            t(chat_key, "marcador").format(tabla=tabla),
            parse_mode="MarkdownV2"
        )


async def cmd_resetimpostor(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_key = get_chat_key(update)
    user = update.effective_user
    chat = update.effective_chat

    try:
        member = await chat.get_member(user.id)
        es_admin = member.status in ("administrator", "creator")
    except Exception:
        es_admin = False

    if not es_admin:
        await update.message.reply_text(t(chat_key, "solo_admin_reset"))
        return

    with get_conn() as conn:
        conn.execute(
            "UPDATE jugadores SET victorias=0, derrotas=0 WHERE chat_key=?",
            (chat_key,)
        )

    await update.message.reply_text(t(chat_key, "reset_ok"), parse_mode="MarkdownV2")


async def cmd_resetroles(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_key = get_chat_key(update)
    user = update.effective_user
    chat = update.effective_chat

    try:
        member = await chat.get_member(user.id)
        es_admin = member.status in ("administrator", "creator")
    except Exception:
        es_admin = False

    if not es_admin:
        await update.message.reply_text(t(chat_key, "solo_admin_reset"))
        return

    with get_conn() as conn:
        conn.execute(
            "UPDATE jugadores SET veces_impostor=0, veces_inocente=0, victorias_impostor=0, victorias_inocente=0 WHERE chat_key=?",
            (chat_key,)
        )

    await update.message.reply_text(t(chat_key, "resetroles_ok"), parse_mode="MarkdownV2")


async def cmd_cancelar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_key = get_chat_key(update)
    user = update.effective_user
    partida = get_partida(chat_key)

    if not partida or partida[2] == "terminada":
        await update.message.reply_text(t(chat_key, "sin_partida_activa"))
        return
    if partida[8] != user.id:
        await update.message.reply_text(t(chat_key, "solo_creador_cancelar"))
        return

    tarea = ctx.bot_data.pop(f"timer_{chat_key}", None)
    if tarea:
        tarea.cancel()
    tarea_adiv = ctx.bot_data.pop(f"timer_adiv_{chat_key}", None)
    if tarea_adiv:
        tarea_adiv.cancel()

    with get_conn() as conn:
        conn.execute("UPDATE partidas SET estado='terminada' WHERE chat_key=?", (chat_key,))
    await update.message.reply_text(t(chat_key, "cancelado"), parse_mode="MarkdownV2")


async def cmd_addword(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_key = get_chat_key(update)
    user = update.effective_user
    chat = update.effective_chat

    try:
        member = await chat.get_member(user.id)
        es_admin = member.status in ("administrator", "creator")
    except Exception:
        es_admin = False

    if not es_admin:
        await update.message.reply_text(t(chat_key, "addword_solo_admin"))
        return

    if not ctx.args:
        await update.message.reply_text(t(chat_key, "addword_uso"), parse_mode="MarkdownV2")
        return

    palabra = " ".join(ctx.args).strip()
    agregada = add_palabra_custom(chat_key, palabra)

    if agregada:
        await update.message.reply_text(
            t(chat_key, "addword_ok").format(palabra=esc(palabra)),
            parse_mode="MarkdownV2"
        )
    else:
        await update.message.reply_text(
            t(chat_key, "addword_ya_existe").format(palabra=esc(palabra)),
            parse_mode="MarkdownV2"
        )


async def cmd_removeword(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_key = get_chat_key(update)
    user = update.effective_user
    chat = update.effective_chat

    try:
        member = await chat.get_member(user.id)
        es_admin = member.status in ("administrator", "creator")
    except Exception:
        es_admin = False

    if not es_admin:
        await update.message.reply_text(t(chat_key, "removeword_solo_admin"))
        return

    if not ctx.args:
        await update.message.reply_text(t(chat_key, "removeword_uso"), parse_mode="MarkdownV2")
        return

    palabra = " ".join(ctx.args).strip()
    eliminada = remove_palabra_custom(chat_key, palabra)

    if eliminada:
        await update.message.reply_text(
            t(chat_key, "removeword_ok").format(palabra=esc(palabra)),
            parse_mode="MarkdownV2"
        )
    else:
        await update.message.reply_text(
            t(chat_key, "removeword_no_existe").format(palabra=esc(palabra)),
            parse_mode="MarkdownV2"
        )


async def cmd_words(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_key = get_chat_key(update)
    palabras = get_palabras_custom(chat_key)

    if not palabras:
        await update.message.reply_text(t(chat_key, "words_vacia"), parse_mode="MarkdownV2")
        return

    lista = "\n".join(f"  {i+1}\\. {esc(p)}" for i, p in enumerate(palabras))
    await update.message.reply_text(
        t(chat_key, "words_lista").format(n=len(palabras), lista=lista),
        parse_mode="MarkdownV2"
    )



async def cmd_roles(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_key = get_chat_key(update)
    with get_conn() as conn:
        jugadores = conn.execute(
            """SELECT username, veces_impostor, veces_inocente,
                      victorias_impostor, victorias_inocente
               FROM jugadores
               WHERE chat_key=? AND (veces_impostor > 0 OR veces_inocente > 0)
               ORDER BY (veces_impostor + veces_inocente) DESC""",
            (chat_key,)
        ).fetchall()

    if not jugadores:
        await update.message.reply_text(t(chat_key, "roles_sin_datos"), parse_mode="MarkdownV2")
        return

    img_buf = generar_imagen_roles(chat_key, jugadores)
    if img_buf:
        await update.message.reply_photo(photo=img_buf)
    else:
        # Fallback texto
        col = t(chat_key, "col_jugador")
        encabezado = f"#   {col:<6}  Imp  W   Ino  W"
        separador  = "─" * len(encabezado)
        lineas = [encabezado, separador]
        for i, j in enumerate(jugadores, 1):
            nom = limpiar_nombre_tabla(j[0])
            vi, ino, wvi, wino = j[1], j[2], j[3], j[4]
            lineas.append(f"{i:<3} {nom:<6}  {vi:<4} {wvi:<4} {ino:<4} {wino}")
        tabla = "```\n" + "\n".join(lineas) + "\n```"
        await update.message.reply_text(
            t(chat_key, "roles_tabla").format(tabla=tabla),
            parse_mode="MarkdownV2"
        )


async def cmd_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_key = get_chat_key(update)
    user = update.effective_user
    chat = update.effective_chat

    # Obtener todos los usuarios registrados en el grupo
    with get_conn() as conn:
        miembros = conn.execute(
            "SELECT user_id, username FROM jugadores WHERE chat_key=?",
            (chat_key,)
        ).fetchall()

    if not miembros:
        await update.message.reply_text("⚠️ No hay usuarios registrados en este grupo aún.")
        return

    # Obtener el mensaje personalizado (texto después del comando)
    texto_extra = ""
    if ctx.args:
        texto_extra = " ".join(ctx.args)

    # Construir menciones visibles por nombre
    nombres_visibles = " · ".join(
        "[" + uname + "](tg://user?id=" + str(uid) + ")"
        for uid, uname in miembros
    )

    msg = "📢 " + nombres_visibles
    if texto_extra:
        msg += "\n\n" + texto_extra

    await update.message.reply_text(msg, parse_mode="Markdown")


async def error_handler(update, ctx):
    error = ctx.error
    if isinstance(error, Conflict):
        logger.critical("⚠️ Conflicto de instancia. Saliendo...")
        os._exit(1)
    else:
        logger.error(f"Error: {error}")


async def set_commands(app):
    from telegram import BotCommand
    await app.bot.set_my_commands([
        BotCommand("playimpostor", "🎮 Create a new game"),
        BotCommand("join",         "✋ Join the current game"),
        BotCommand("vote",         "🗳️ Open voting (creator only)"),
        BotCommand("howtoplay",    "📖 How to play"),
        BotCommand("score",        "🏆 View scoreboard"),
        BotCommand("language",     "🌐 Change language"),
        BotCommand("resetimpostor","🔄 Reset scores (admins only)"),
        BotCommand("cancel",       "❌ Cancel current game (creator only)"),
    ])
    logger.info("✅ Comandos registrados en Telegram.")

def main():
    init_db()
    _init_fonts()
    app = Application.builder().token(TOKEN).post_init(set_commands).build()

    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("playimpostor", cmd_nueva))
    app.add_handler(CommandHandler("join",        cmd_unirse))
    app.add_handler(CommandHandler("vote",         cmd_votar))
    app.add_handler(CommandHandler("score",       cmd_puntaje))
    app.add_handler(CommandHandler("cancel",      cmd_cancelar))
    app.add_handler(CommandHandler("howtoplay",     cmd_como_jugar))
    app.add_handler(CommandHandler("resetimpostor", cmd_resetimpostor))
    app.add_handler(CommandHandler("resetroles",    cmd_resetroles))
    app.add_handler(CommandHandler("language",        cmd_idioma))
    app.add_handler(CommandHandler("all",               cmd_all))
    app.add_handler(CommandHandler("roles",             cmd_roles))
    app.add_handler(CommandHandler("addword",           cmd_addword))
    app.add_handler(CommandHandler("removeword",        cmd_removeword))
    app.add_handler(CommandHandler("words",             cmd_words))

    app.add_handler(CallbackQueryHandler(btn_unirse,          pattern="^unirse$"))
    app.add_handler(CallbackQueryHandler(btn_iniciar_partida, pattern="^iniciar_partida$"))
    app.add_handler(CallbackQueryHandler(btn_categoria,       pattern="^cat:"))
    app.add_handler(CallbackQueryHandler(btn_confirmar_pista,       pattern="^confirmar_pista:"))
    app.add_handler(CallbackQueryHandler(btn_confirmar_adivinanza,   pattern="^confirmar_adiv:"))
    app.add_handler(CallbackQueryHandler(btn_abrir_votar,     pattern="^abrir_votar$"))
    app.add_handler(CallbackQueryHandler(btn_voto,            pattern="^voto:"))
    app.add_handler(CallbackQueryHandler(btn_revoto,          pattern="^revoto:"))
    app.add_handler(CallbackQueryHandler(btn_idioma,          pattern="^idioma:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_adivinanza))
    app.add_error_handler(error_handler)

    logger.info("🤖 Bot iniciado...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
