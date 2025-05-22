import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()  # Carga las variables del archivo .env

MONGODB_URI = os.getenv("MONGODB_URI")

client = MongoClient(MONGODB_URI)
db = client["telegram_bot"]  # Puedes cambiar el nombre de la base

# Prueba la conexión
def test_connection():
    try:
        client.admin.command('ping')
        print("✅ Conectado a MongoDB Atlas correctamente.")
    except Exception as e:
        print("❌ Error al conectar a MongoDB:", e)
