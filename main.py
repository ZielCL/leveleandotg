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
xp_collection       = db.xp_usuarios           # acumulado total
monthly_xp          = db.xp_mensual            # xp del mes actual
config_collection   = db.temas_configurados
alerts_collection   = db.level_alerts
stats_collection    = db.user_stats             # meses pasados y top3 count

# ─── Helpers ──────────────────────────────────────────────────────
def xp_para_subir(nivel: int) -> int:
    return 100 + 7 * (nivel - 1)

def make_key(chat_id: int, user_id: int) -> str:
    return f"{chat_id}_{user_id}"

async def rollover_month(chat_id:int):
    """
    Al cambiar de mes: actualizar stats de top3, reset xp mensual, incrementar contador.
    """
    # identificar top3 del mes pasado
    cursor = monthly_xp.find({"_id": {"$regex": f"^{chat_id}_"}}).sort("xp", -1).limit(3)
    top3 = await cursor.to_list(3)
    # contar meses
    cfg = await config_collection.find_one({"_id": chat_id}) or {}
    meses = cfg.get("meses_pasados", 0) + 1
    # actualizar stats y config
    for rank, doc in enumerate(top3, start=1):
        uid = doc["_id"].split("_",1)[1]
        await stats_collection.update_one(
            {"_id": f"{chat_id}_{uid}"},
            {"$inc": {"top3_count": 1}}, upsert=True
        )
    await config_collection.update_one(
        {"_id": chat_id},
        {"$set": {"last_month": datetime.utcnow().month, "meses_pasados": meses}}
    )
    # reset mensual
    await monthly_xp.delete_many({"_id": {"$regex": f"^{chat_id}_"}})

async def ensure_monthly_state(chat_id:int):
    now = datetime.utcnow()
    cfg = await config_collection.find_one({"_id": chat_id})
    if not cfg or cfg.get("last_month") != now.month:
        await rollover_month(chat_id)

async def send_top(bot, chat_id:int, page:int, collec):
    prefix = f"{chat_id}_"
    total  = await collec.count_documents({"_id": {"$regex": f"^{prefix}"}})
    pages  = max(1, math.ceil(total/10))
    page   = max(1, min(page, pages))
    cursor = collec.find({"_id": {"$regex": f"^{prefix}"}}).sort("xp", -1)
    docs   = await cursor.skip((page-1)*10).limit(10).to_list(10)
    text = f"🏆 XP Ranking (pág {page}/{pages}):\n"
    for i,doc in enumerate(docs,start=(page-1)*10+1):
        uid = int(doc["_id"].split("_",1)[1])
        try:
            name = (await bot.get_chat_member(chat_id, uid)).user.full_name
        except:
            name = f"User {uid}"
        text += f"{i}. {name} — Nivel {doc['nivel']}, {doc['xp']} XP\n"
    btns=[]
    if page>1: btns.append(InlineKeyboardButton("◀️", f"top_{page-1}_{collec.name}"))
    if page<pages: btns.append(InlineKeyboardButton("▶️", f"top_{page+1}_{collec.name}"))
    return text, InlineKeyboardMarkup([btns]) if btns else None

# ─── Startup ──────────────────────────────────────────────────────
async def on_startup(app):
    logger.info("✅ Bot arrancando")
    await client.admin.command("ping")
    logger.info("✅ MongoDB ok")
    await app.bot.delete_webhook(drop_pending_updates=True)
    cmds=[
        BotCommand("start","Configurar bot"),
        BotCommand("levsettema","Define hilo alertas"),
        BotCommand("levalerta","Define premio por nivel"),
        BotCommand("levalertalist","Lista alertas"),
        BotCommand("levperfil","Muestra tu perfil"),
        BotCommand("levtop","Ranking mes"),
        BotCommand("levtopacumulado","Ranking total"),
        BotCommand("levcomandos","Lista comandos"),
    ]
    await app.bot.set_my_commands(cmds)

# ─── Handlers ────────────────────────────────────────────────────
async def levtopacumulado(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    chat=update.effective_chat
    await ensure_monthly_state(chat.id)
    text,kb=await send_top(ctx.bot,chat.id,1,xp_collection)
    await update.message.reply_text(text,reply_markup=kb,parse_mode="HTML")

async def levtop(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    chat=update.effective_chat
    await ensure_monthly_state(chat.id)
    text,kb=await send_top(ctx.bot,chat.id,1,monthly_xp)
    await update.message.reply_text(text,reply_markup=kb,parse_mode="HTML")

async def top_callback(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    data=update.callback_query.data.split("_")
    _,page,collection_name=data
    collec = xp_collection if collection_name=="xp_usuarios" else monthly_xp
    text,kb=await send_top(ctx.bot,update.effective_chat.id,int(page),collec)
    await update.callback_query.edit_message_text(text,reply_markup=kb,parse_mode="HTML")

async def levperfil(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    chat,user=update.effective_chat,update.effective_user
    await ensure_monthly_state(chat.id)
    key=make_key(chat.id,user.id)
    rec=await monthly_xp.find_one({"_id":key}) or {}
    xp, lvl = rec.get("xp",0), rec.get("nivel",1)
    # posición mensual
    pref=f"{chat.id}_"
    higher=await monthly_xp.count_documents({"_id":{"$regex":f"^{pref}"},"xp":{"$gt":xp}})
    pos_mes,total_mes=higher+1,await monthly_xp.count_documents({"_id":{"$regex":f"^{pref}"}})
    falta=xp_para_subir(lvl)-xp
    # stats acumulado
    rec2=await xp_collection.find_one({"_id":key}) or {}
    xp2, lvl2 = rec2.get("xp",0), rec2.get("nivel",1)
    higher2=await xp_collection.count_documents({"_id":{"$regex":f"^{pref}"},"xp":{"$gt":xp2}})
    pos_tot,total_tot=higher2+1,await xp_collection.count_documents({"_id":{"$regex":f"^{pref}"}})
    # stats top3 y meses
    stats=await stats_collection.find_one({"_id":key}) or {}
    top3c=stats.get("top3_count",0)
    cfg=await config_collection.find_one({"_id":chat.id}) or {}
    meses=cfg.get("meses_pasados",0)
    # mensaje
    text=(f"{user.full_name}:\n"
          f"• Nivel: {lvl}  \n"
          f"• Posición: {pos_mes}/{total_mes}\n\n"
          f"• XP: {xp}\n"
          f"• XP para siguiente nivel: {falta}\n")
    btn=InlineKeyboardButton("➡️ Acumulado",callback_data="perfil_acum")
    await update.message.reply_text(text,reply_markup=InlineKeyboardMarkup([[btn]]),parse_mode="HTML")

async def perfil_callback(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    chat,user=update.effective_chat,update.effective_user
    key=make_key(chat.id,user.id)
    rec=await xp_collection.find_one({"_id":key}) or {}
    xp, lvl = rec.get("xp",0), rec.get("nivel",1)
    pref=f"{chat.id}_"
    higher=await xp_collection.count_documents({"_id":{"$regex":f"^{pref}"},"xp":{"$gt":xp}})
    pos, total = higher+1, await xp_collection.count_documents({"_id":{"$regex":f"^{pref}"}})
    stats=await stats_collection.find_one({"_id":key}) or {}
    top3c=stats.get("top3_count",0)
    cfg=await config_collection.find_one({"_id":chat.id}) or {}
    meses=cfg.get("meses_pasados",0)
    text=(f"Nivel acumulado: {lvl}\n"
          f"Posición acumulada: {pos}/{total}\n"
          f"Veces en top 3: {top3c}/{meses}\n")
    btn=InlineKeyboardButton("⬅️ Mes actual",callback_data="perfil_mes")
    await update.callback_query.edit_message_text(text,reply_markup=InlineKeyboardMarkup([[btn]]),parse_mode="HTML")

# registrando handlers
def main():
    app=ApplicationBuilder().token(BOT_TOKEN).post_init(on_startup).build()
    app.add_handler(CommandHandler("levtop",levtop))
    app.add_handler(CommandHandler("levtopacumulado",levtopacumulado))
    app.add_handler(CallbackQueryHandler(top_callback,pattern=r"^top_"))
    app.add_handler(CommandHandler("levperfil",levperfil))
    app.add_handler(CallbackQueryHandler(perfil_callback,pattern=r"^perfil_"))
    # ... otros handlers ya definidos ...
    app.run_polling()

if __name__=="__main__":
    main()
