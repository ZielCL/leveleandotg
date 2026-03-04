"""
🕵️ Bot del Impostor para Telegram
Juego donde todos reciben la misma palabra excepto el impostor.
"""

import logging
import random
import sqlite3
import anthropic
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Conflict
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

import os
TOKEN = os.environ.get("BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

CATEGORIAS = {
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
    "🎤 K-Pop (idols/grupos": [
        "Stray Kids", "ATEEZ", "TXT", "ENHYPEN", "NCT Dream",
        "TREASURE", "THE BOYZ", "MONSTA X", "VICTON", "BTOB",
        "P1Harmony", "TEMPEST", "ZEROBASEONE", "BOYNEXTDOOR", "RIIZE",
        "BTS", "EXO", "GOT7", "SEVENTEEN", "NCT 127",
        "SHINee", "BIGBANG", "2PM", "INFINITE", "VIXX",
        "WINNER", "iKON", "ASTRO", "DAY6", "HIGHLIGHT",
        "BLACKPINK", "TWICE", "aespa", "IVE", "NewJeans",
        "ITZY", "NMIXX", "LE SSERAFIM", "MAMAMOO", "Red Velvet",
        "Kep1er", "STAYC", "EVERGLOW", "WEEEKLY", "tripleS", "BABYMONSTER",
        "Girls Generation", "f(x)", "2NE1", "Wonder Girls", "T-ARA",
        "SISTAR", "4MINUTE", "AOA", "APINK", "EXID",
        "G-Dragon", "Taeyang", "Daesung", "T.O.P",
        "PSY", "Rain", "Se7en", "Zico", "Jay Park",
        "Dean", "Crush", "Epik High",
        "RM", "Jin", "Suga", "J-Hope", "Jimin", "V", "Jungkook",
        "Baekhyun", "Chanyeol", "D.O", "Kai", "Sehun",
        "Suho", "Xiumin", "Chen", "Lay",
        "Woozi", "Mingyu", "Vernon", "Hoshi", "Jeonghan",
        "S.Coups", "The8", "Dino",
        "Bang Chan", "Lee Know", "Changbin", "Hyunjin", "Han",
        "Felix", "Seungmin", "I.N",
        "Hongjoong", "Seonghwa", "Yunho", "Yeosang", "San",
        "Mingi", "Wooyoung", "Jongho",
        "Onew", "Key", "Minho", "Taemin",
        "IU", "Sunmi", "HyunA", "Chungha", "Heize",
        "Jessi", "Somi", "Gain", "BoA", "CL",
        "Jennie", "Lisa", "Rosé", "Jisoo",
        "Nayeon", "Jeongyeon", "Momo", "Sana", "Jihyo",
        "Mina", "Dahyun", "Chaeyoung", "Tzuyu",
        "Karina", "Giselle", "Winter", "Ningning",
        "Yujin", "Gaeul", "Rei", "Wonyoung", "Liz", "Leeseo",
        "Minji", "Hanni", "Danielle", "Haerin", "Hyein",
        "Irene", "Seulgi", "Wendy", "Joy", "Yeri",
        "Yeji", "Lia", "Ryujin", "Chaeryeong", "Yuna",
        "Sakura", "Chaewon", "Yunjin", "Kazuha", "Eunchae",
        "Taeyeon", "Tiffany", "Yoona", "Yuri", "Sooyoung",
        "Hyoyeon", "Sunny", "Seohyun",
        "Solar", "Moonbyul", "Wheein", "Hwasa",
        "Lily", "Haewon", "Sullyoon", "Bae", "Jiwoo", "Kyujin",
        "Sumin", "Sieun", "ISA", "Seeun", "Yoon", "J",
        "Mashiro", "Chaehyun", "Hikaru", "Dayeon", "Xiaoting", "Yeseo", "Youngeun",
        "Aisha", "Sihyeon", "Mia", "Onda", "Yiren",
        "Miyeon", "Minnie", "Soojin", "Soyeon", "Yuqi", "Shuhua",
        "Solji", "LE", "Hani", "Hyelin", "Jeonghwa",
        "Chorong", "Bomi", "Eunji", "Namjoo", "Hayoung",
        "SinB", "Eunha", "Umji",
        "Ruka", "Pharita", "Asa", "Rami", "Ahyeon", "Rora", "Chiquita",
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
}

ANTHROPIC_CLIENT = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

def normalizar(texto: str) -> str:
    """Elimina tildes, diéresis y convierte a minúsculas para comparación flexible."""
    import unicodedata
    texto = texto.lower().strip()
    # Descomponer caracteres y eliminar marcas de acento
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto


def generar_pistas(palabra: str, categoria: str) -> str:
    try:
        response = ANTHROPIC_CLIENT.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": (
                    f"Genera exactamente 2 pistas para describir '{palabra}' (categoría: {categoria}) "
                    f"en el juego del impostor. Las pistas deben:\n"
                    f"- Ayudar a describir la palabra SIN decirla directamente ni usar palabras muy obvias\n"
                    f"- Ser cortas, de máximo 10 palabras cada una\n"
                    f"- Estar numeradas como 1. y 2.\n"
                    f"Responde SOLO con las 2 pistas, sin explicaciones."
                )
            }]
        )
        return response.content[0].text.strip()
    except Exception:
        return "1. Piensa en sus características principales\n2. Recuerda dónde o cómo se usa"


# ── Base de datos ──────────────────────────────────────────────
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
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_key    TEXT,
            user_id     INTEGER,
            username    TEXT,
            victorias   INTEGER DEFAULT 0,
            derrotas    INTEGER DEFAULT 0,
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
    """)
    conn.commit()
    conn.close()

def get_conn():
    return sqlite3.connect(DB_PATH)

# partida: (chat_key, chat_id, estado, categoria, palabra, impostor_ids, vivos, ronda, creador_id)
#           [0]       [1]      [2]     [3]        [4]     [5]            [6]    [7]    [8]

def get_partida(chat_key):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM partidas WHERE chat_key=?", (chat_key,)).fetchone()

def get_jugadores_activos(chat_key):
    """Jugadores de la partida actual: [(user_id, username), ...]"""
    with get_conn() as conn:
        return conn.execute(
            "SELECT user_id, username FROM partida_jugadores WHERE chat_key=?", (chat_key,)
        ).fetchall()

def get_marcador(chat_key):
    """Marcador de los jugadores activos via JOIN: [(user_id, username, victorias, derrotas), ...]"""
    with get_conn() as conn:
        return conn.execute(
            """SELECT j.user_id, j.username, j.victorias, j.derrotas
               FROM jugadores j
               INNER JOIN partida_jugadores pj ON j.chat_key = pj.chat_key AND j.user_id = pj.user_id
               WHERE j.chat_key=? ORDER BY (j.victorias - j.derrotas) DESC, j.victorias DESC""",
            (chat_key,)
        ).fetchall()

def get_marcador_global(chat_key):
    """Marcador de todos los que han jugado alguna vez"""
    with get_conn() as conn:
        return conn.execute(
            "SELECT user_id, username, victorias, derrotas FROM jugadores WHERE chat_key=? ORDER BY (victorias - derrotas) DESC, victorias DESC",
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

def nombre(user):
    return user.first_name or user.username or str(user.id)

def esc(text):
    chars = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in chars else c for c in str(text))

def get_chat_key(update):
    chat = update.effective_chat
    chat_id = chat.id
    if getattr(chat, "is_forum", False) and update.effective_message:
        thread_id = update.effective_message.message_thread_id
        return f"{chat_id}_{thread_id}" if thread_id else str(chat_id)
    return str(chat_id)

def calcular_num_impostores(num_jugadores):
    if num_jugadores <= 4:
        return 1
    elif num_jugadores <= 6:
        return random.randint(1, 3)
    else:
        return random.randint(2, 3)


# ══════════════════════════════════════════════════════════════
# COMANDOS
# ══════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🕵️ *Bienvenido al Bot del Impostor\\!*\n\n"
        "El juego es simple:\n"
        "• Todos reciben la *misma palabra secreta*\n"
        "• Excepto el/los *impostores*, que no la saben\n"
        "• Den pistas sin decirla directamente 🎭\n"
        "• El grupo vota para eliminar jugadores por rondas\n\n"
        "*Comandos:*\n"
        "`/jugarimpostor` — Crear una partida\n"
        "`/votar` — Abrir votación \\(solo el creador\\)\n"
        "`/comojugar` — Cómo se juega\n"
        "`/puntaje` — Ver marcador\n"
        "`/cancelar` — Cancelar partida",
        parse_mode="MarkdownV2"
    )


async def cmd_como_jugar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🕵️ *¿Cómo se juega El Impostor?*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "*📋 Objetivo*\n"
        "El grupo debe eliminar a todos los impostores\\. "
        "Los impostores deben pasar desapercibidos o adivinar la palabra secreta\\.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "*🎮 Pasos del juego*\n\n"
        "*0\\. Iniciar el bot en privado*\n"
        "Debes ingresar a @impostortg_bot y apretar el boton de la parte inferior que dice `Iniciar`, luego en comandos usa `/comojugar`para aprender sobre el bot\\.\n\n"
        "*1\\. Crear la partida*\n"
        "Alguien usa `/jugarimpostor` y los demás se unen con `/unirse` o el botón\\.\n\n"
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
        "`/jugarimpostor` — Crear partida\n"
        "`/unirse` — Unirse a la partida\n"
        "`/votar` — Abrir votación \\(creador\\)\n"
        "`/puntaje` — Ver marcador\n"
        "`/resetimpostor` — Resetear puntajes\n"
        "`/cancelar` — Cancelar partida",
        parse_mode="MarkdownV2"
    )


async def cmd_nueva(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_key = get_chat_key(update)
    chat_id = update.effective_chat.id
    user = update.effective_user

    partida = get_partida(chat_key)
    if partida and partida[2] not in ("terminada",):
        await update.message.reply_text("⚠️ Ya hay una partida activa. Usa /cancelar primero.")
        return

    limpiar_jugadores_activos(chat_key)

    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO partidas (chat_key, chat_id, estado, creador_id, ronda) VALUES (?,?,?,?,1)",
            (chat_key, chat_id, "esperando", user.id)
        )

    upsert_jugador(chat_key, user.id, nombre(user))
    agregar_jugador_activo(chat_key, user.id, nombre(user))

    keyboard = [[InlineKeyboardButton("✋ Unirse a la partida", callback_data="unirse")]]
    await update.message.reply_text(
        f"🎮 *{esc(nombre(user))} creó una nueva partida del juego Impostor\\!*\n\n"
        "Pulsen el botón o usen /unirse para sumarse\\.\n"
        "Cuando estén listos, el creador pulsa *¡Iniciar partida\\!*",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def cmd_unirse(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _unirse(get_chat_key(update), update.effective_user, update.message.reply_text)

async def btn_unirse(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _unirse(get_chat_key(update), update.effective_user, update.callback_query.message.reply_text)

async def _unirse(chat_key, user, reply_fn):
    partida = get_partida(chat_key)
    if not partida:
        await reply_fn("⚠️ No hay ninguna partida abierta. Usa /jugarimpostor para crear una.")
        return
    if partida[2] != "esperando":
        await reply_fn("⚠️ La partida ya está en curso, no puedes unirte ahora.")
        return

    activos = get_jugadores_activos(chat_key)
    if user.id in [j[0] for j in activos]:
        await reply_fn("⚠️ Ya estás en la partida.")
        return

    upsert_jugador(chat_key, user.id, nombre(user))
    agregar_jugador_activo(chat_key, user.id, nombre(user))
    activos = get_jugadores_activos(chat_key)

    lista = "\n".join(f"  {i+1}\\. {esc(j[1])}" for i, j in enumerate(activos))
    keyboard = []
    if len(activos) >= 3:
        keyboard = [[InlineKeyboardButton("🚀 ¡Iniciar partida!", callback_data="iniciar_partida")]]

    await reply_fn(
        f"✅ *{esc(nombre(user))} se unió\\!*\n\n"
        f"*Jugadores* \\({len(activos)}\\):\n{lista}\n\n"
        + ("_El creador puede iniciar cuando quiera\\._" if len(activos) >= 3 else f"_Faltan {3 - len(activos)} jugadores más para poder iniciar\\._"),
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
        await query.answer("No hay partida en espera.", show_alert=True)
        return
    if partida[8] != user.id:
        await query.answer("⚠️ Solo el creador puede iniciar la partida.", show_alert=True)
        return

    jugadores = get_jugadores_activos(chat_key)
    if len(jugadores) < 3:
        await query.answer(f"⚠️ Necesitas al menos 3 jugadores. Ahora hay {len(jugadores)}.", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(cat, callback_data=f"cat:{cat}")]
        for cat in CATEGORIAS
    ]
    keyboard.append([InlineKeyboardButton("🎲 ¡Sorpréndeme! (Random)", callback_data="cat:RANDOM")])
    await query.message.reply_text(
        "🗂️ *Elige una categoría:*",
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
        await query.answer("Solo el creador puede elegir la categoría.", show_alert=True)
        return

    # ── Definir categoría y textos ANTES de usarlos ──
    categoria_raw = query.data.split(":", 1)[1]
    es_random = (categoria_raw == "RANDOM")
    categoria = random.choice(list(CATEGORIAS.keys())) if es_random else categoria_raw
    texto_cat_grupo = "🎲 *¡Categoría sorpresa\\!*" if es_random else f"Categoría: *{esc(categoria)}*"
    texto_cat_confirmacion = "🎲 *¡Categoría sorpresa\\!*" if es_random else f"✅ Categoría: *{esc(categoria)}*"

    palabra = random.choice(CATEGORIAS[categoria])
    jugadores = get_jugadores_activos(chat_key)  # [(user_id, username)]
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

    await query.edit_message_text(
        f"{texto_cat_confirmacion}\n\n📩 Enviando palabras en privado\\.\\.\\.",
        parse_mode="MarkdownV2"
    )

    pistas_raw = generar_pistas(palabra, categoria)
    pistas = "\n".join(esc(linea) for linea in pistas_raw.splitlines())

    fallidos = []
    for uid, uname in jugadores:
        try:
            if uid in impostor_ids_set:
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
                    f"💡 *Cómo puedes describirla:*\n{pistas}\n\n"
                    "_Da pistas sin decir la palabra directamente\\. ¡Encuentra al impostor\\!_ 🕵️"
                )
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
        "jugadores_iniciales": len(jugadores)
    }

    aviso = ""
    if fallidos:
        aviso = (
            "\n\n⚠️ No pude enviar mensaje a: "
            + ", ".join(esc(f) for f in fallidos)
            + "\n_Deben iniciar conversación con el bot primero_"
        )

    aviso_rondas = (
        "Esta partida se juega en *2 rondas* de pistas antes de votar\\. ¡Atención\\! 👀"
        if len(jugadores) == 3 else
        "Cuando todos hayan dado su pista, el creador abre la votación 🗳️"
    )

    await ctx.bot.send_message(
        chat_id,
        f"🎮 *¡La partida comienza\\!*\n\n"
        f"{texto_cat_grupo}\n\n"
        f"*🎲 Orden de pistas \\(elegido al azar\\):*\n{turno_lista}\n\n"
        f"Cada uno da *una pista* sobre la palabra sin decirla directamente\\.\n"
        f"{aviso_rondas}"
        + aviso,
        parse_mode="MarkdownV2"
    )

    primer = orden[0]
    await ctx.bot.send_message(
        chat_id,
        f"👆 *¡Es el turno de* [{esc(primer[1])}](tg://user?id={primer[0]})\\!\n"
        f"Escribe tu pista en el chat\\.",
        parse_mode="MarkdownV2"
    )


async def _abrir_votacion(chat_key, ctx, message):
    """Lógica compartida entre btn_abrir_votar y cmd_votar."""
    vivos_ids = get_vivos(chat_key)
    jugadores = get_jugadores_activos(chat_key)
    vivos = [j for j in jugadores if j[0] in vivos_ids]

    keyboard = [
        [InlineKeyboardButton(f"🗳️ {j[1]}", callback_data=f"voto:{j[0]}")]
        for j in vivos
    ]
    ctx.bot_data[f"votos_{chat_key}"] = {}

    await message.reply_text(
        f"🗳️ *¿Quién es el impostor\\?*\n\n"
        f"_Jugadores vivos \\({len(vivos)}\\) — solo ellos votan:_",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def btn_abrir_votar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_key = get_chat_key(update)
    user = update.effective_user

    partida = get_partida(chat_key)
    if not partida or partida[2] != "jugando":
        await query.answer("No hay partida en curso.", show_alert=True)
        return
    if partida[8] != user.id:
        await query.answer("⚠️ Solo el creador puede abrir la votación.", show_alert=True)
        return

    await query.answer()
    await _abrir_votacion(chat_key, ctx, query.message)


async def cmd_votar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_key = get_chat_key(update)
    partida = get_partida(chat_key)
    user = update.effective_user

    if not partida or partida[2] != "jugando":
        await update.message.reply_text("⚠️ No hay partida en curso.")
        return
    if partida[8] != user.id:
        await update.message.reply_text("⚠️ Solo el creador puede abrir la votación.")
        return

    await _abrir_votacion(chat_key, ctx, update.message)


async def btn_voto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_key = get_chat_key(update)
    voter_id = query.from_user.id

    partida = get_partida(chat_key)
    if not partida or partida[2] != "jugando":
        await query.answer("La votación ya cerró.", show_alert=True)
        return

    vivos_ids = get_vivos(chat_key)
    if voter_id not in vivos_ids:
        await query.answer("No puedes votar: estás eliminado o no eres parte de esta partida.", show_alert=True)
        return

    jugadores = get_jugadores_activos(chat_key)
    vivos = [j for j in jugadores if j[0] in vivos_ids]

    votado_id = int(query.data.split(":")[1])
    votos = ctx.bot_data.setdefault(f"votos_{chat_key}", {})

    if voter_id in votos:
        await query.answer("Ya votaste.", show_alert=True)
        return

    votos[voter_id] = votado_id
    await query.answer("✅ ¡Voto registrado!")

    faltantes = len(vivos) - len(votos)
    await query.message.reply_text(
        f"✅ *{esc(query.from_user.first_name)}* votó\\. "
        + (f"Faltan *{faltantes}* votos\\." if faltantes > 0 else ""),
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
        await query.answer("La votación ya cerró.", show_alert=True)
        return

    vivos_ids = get_vivos(chat_key)
    if voter_id not in vivos_ids:
        await query.answer("No puedes votar: estás eliminado o no eres parte de esta partida.", show_alert=True)
        return

    datos = ctx.bot_data.get(f"revotacion_{chat_key}")
    if not datos:
        await query.answer("No hay revotación activa.", show_alert=True)
        return

    votado_id = int(query.data.split(":")[1])
    if votado_id not in datos["candidatos"]:
        await query.answer("Voto inválido.", show_alert=True)
        return

    votos = ctx.bot_data.setdefault(f"votos_{chat_key}", {})
    if voter_id in votos:
        await query.answer("Ya votaste.", show_alert=True)
        return

    votos[voter_id] = votado_id
    await query.answer("✅ ¡Voto registrado!")

    vivos = datos["vivos"]
    faltantes = len(vivos) - len(votos)
    await query.message.reply_text(
        f"✅ *{esc(query.from_user.first_name)}* votó en la revotación\\. "
        + (f"Faltan *{faltantes}* votos\\." if faltantes > 0 else ""),
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
            # Segundo empate → nadie eliminado, nueva ronda
            await query.message.reply_text(
                "⚖️ *¡Segundo empate\\!*\n\n"
                "Nadie es eliminado en esta ronda\\. ¡El juego continúa\\!\n\n"
                "El creador abre la votación cuando estén listos\\.",
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗳️ ¡Abrir votación!", callback_data="abrir_votar")]])
            )
            return

        vivos_ids_actual = get_vivos(chat_key)
        vivos_actual = [j for j in jugadores if j[0] in vivos_ids_actual]
        await resolver_votacion(chat_key, ctx, partida, jugadores, vivos_actual, votos, query.message)


async def resolver_votacion(chat_key, ctx, partida, jugadores, vivos, votos, message):
    """jugadores y vivos son listas de (user_id, username)"""
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
            f"⚖️ *¡Empate\\!*\n\n"
            f"{nombres_empatados} tienen *{max_votos} votos* cada uno\\.\n\n"
            f"🔁 *Revotación* — Solo entre los empatados:\n"
            f"_Jugadores vivos, voten de nuevo:_",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ── Sin empate: procesar eliminación ──
    eliminado_id = empatados[0]
    impostor_ids_set = set(int(i) for i in partida[5].split(","))
    impostores = [j for j in jugadores if j[0] in impostor_ids_set]
    eliminado = next((j for j in vivos if j[0] == eliminado_id), None)
    palabra = partida[4]
    categoria = partida[3]

    nombre_map = {j[0]: j[1] for j in jugadores}
    detalle_votos = "\n".join(
        f"  • {esc(nombre_map.get(v_from, '?'))} → {esc(nombre_map.get(v_to, '?'))}"
        for v_from, v_to in votos.items()
    )

    es_impostor = eliminado_id in impostor_ids_set
    etiqueta = "🕵️ ¡Era impostor\\!" if es_impostor else "✅ Era inocente\\."

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
            f"👑 *{esc(nombre_nuevo)}* es el nuevo creador y puede abrir la votación\\.",
            parse_mode="MarkdownV2"
        )

    await message.reply_text(
        f"🗳️ *Resultado de la votación:*\n\n"
        f"El grupo votó por *{esc(eliminado[1])}*\n"
        f"{etiqueta}\n\n"
        f"*Votos:*\n{detalle_votos}",
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
            "jugadores": jugadores,
            "vivos_restantes_ids": vivos_restantes_ids,
            "impostores_vivos": impostores_vivos,
            "inocentes_vivos_ids": inocentes_vivos_ids,
            "detalle_votos": detalle_votos,
            "partida": partida,
            "impostores": impostores,
        }

        await message.reply_text(
            f"🎯 *¡Última oportunidad, {esc(eliminado[1])}\\!*\n\n"
            f"Si adivinas la palabra secreta *¡tú y todos los impostores ganarán\\!*\n\n"
            f"📝 Escribe la palabra ahora en el chat\\.\n"
            f"_Categoría: {esc(categoria)}_",
            parse_mode="MarkdownV2"
        )
        return

    # ── Inocente votado ──
    if not impostores_vivos:
        await _fin_grupo_gana(chat_key, ctx, jugadores, impostores, palabra, categoria, detalle_votos, message)
        return

    inocentes_restantes = [v for v in vivos_restantes_ids if v not in impostor_ids_set]
    if len(inocentes_restantes) <= 1:
        await _fin_impostores_ganan(
            chat_key, ctx, partida, jugadores, impostores,
            None, palabra, categoria, detalle_votos, message, razon="supervivencia"
        )
        return

    await _nueva_ronda_pistas(chat_key, ctx, jugadores, vivos_restantes_ids, impostor_ids_set, palabra, categoria, message)


async def _nueva_ronda_pistas(chat_key, ctx, jugadores, vivos_ids, impostor_ids_set, palabra, categoria, message):
    """jugadores es lista de (user_id, username)"""
    vivos = [j for j in jugadores if j[0] in vivos_ids]
    orden = list(vivos)
    random.shuffle(orden)
    turno_lista = "\n".join(f"  {i+1}\\. {esc(j[1])}" for i, j in enumerate(orden))


    ctx.bot_data[f"turno_{chat_key}"] = {
        "orden": [j[0] for j in orden],
        "index": 0,
        "ya_dieron_pista": set(),
        "ronda_pistas": 2,
        "jugadores_iniciales": len(jugadores)
    }

    with get_conn() as conn:
        conn.execute("UPDATE partidas SET estado='jugando' WHERE chat_key=?", (chat_key,))

    await message.reply_text(
        f"🔄 *¡Nueva ronda de pistas\\!*\n\n"
        f"👥 Jugadores vivos: *{len(vivos)}*\n\n"
        f"*🎲 Nuevo orden de pistas:*\n{turno_lista}\n\n"
        f"Cada uno da *una pista* sobre la palabra\\.\n"
        f"Cuando terminen, el creador abre la votación 🗳️",
        parse_mode="MarkdownV2"
    )

    primer = orden[0]
    await message.reply_text(
        f"👆 *¡Es el turno de* [{esc(primer[1])}](tg://user?id={primer[0]})\\!\n"
        f"Escribe tu pista en el chat\\.",
        parse_mode="MarkdownV2"
    )


async def btn_confirmar_pista(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_key = get_chat_key(update)
    user = query.from_user

    turno_data = ctx.bot_data.get(f"turno_{chat_key}")
    if not turno_data:
        await query.answer("No hay turno activo.", show_alert=True)
        return

    orden = turno_data["orden"]
    index = turno_data["index"]

    if user.id != orden[index]:
        await query.answer("⚠️ No es tu turno.", show_alert=True)
        return

    await query.answer("✅ ¡Pista confirmada!")
    await query.message.delete()

    turno_data["ya_dieron_pista"].add(user.id)
    siguiente_index = index + 1
    turno_data["index"] = siguiente_index
    chat_id = query.message.chat.id

    if siguiente_index >= len(orden):
        ronda_pistas = turno_data.get("ronda_pistas", 1)
        jugadores_iniciales = turno_data.get("jugadores_iniciales", len(orden))

        # Con 3 jugadores iniciales, la primera ronda no habilita votación
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
                "jugadores_iniciales": jugadores_iniciales
            }

            await ctx.bot.send_message(
                chat_id,
                f"🔄 *¡Segunda ronda de pistas\\!*\n\n"
                f"Ahora sí, después de esta ronda se abrirá la votación\\.\n\n"
                f"*🎲 Nuevo orden:*\n{turno_lista}",
                parse_mode="MarkdownV2"
            )
            primer = nuevo_orden[0]
            await ctx.bot.send_message(
                chat_id,
                f"👆 *¡Es el turno de* [{esc(primer[1])}](tg://user?id={primer[0]})\\!\n"
                f"Escribe tu pista en el chat\\.",
                parse_mode="MarkdownV2"
            )
            return

        ctx.bot_data.pop(f"turno_{chat_key}", None)
        keyboard_votar = [[InlineKeyboardButton("🗳️ ¡Abrir votación!", callback_data="abrir_votar")]]
        await ctx.bot.send_message(
            chat_id,
            "✅ *¡Todos dieron su pista\\!*\n\n"
            "El creador puede abrir la votación 🗳️",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(keyboard_votar)
        )
        return

    siguiente_id = orden[siguiente_index]
    jugadores = get_jugadores_activos(chat_key)
    nombre_siguiente = next((j[1] for j in jugadores if j[0] == siguiente_id), "?")

    await ctx.bot.send_message(
        chat_id,
        f"👆 *¡Es el turno de* [{esc(nombre_siguiente)}](tg://user?id={siguiente_id})\\!\n"
        f"Escribe tu pista en el chat\\.",
        parse_mode="MarkdownV2"
    )


async def handle_adivinanza(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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

        ctx.bot_data.pop(f"adivinando_{chat_key}", None)

        if normalizar(texto) == normalizar(palabra):
            await update.message.reply_text(
                f"🎯 *¡{esc(nombre(user))} adivinó la palabra\\!*\n\n"
                f"La palabra era *{esc(palabra)}*\\. ¡Los impostores ganan\\! 🕵️",
                parse_mode="MarkdownV2"
            )
            await _fin_impostores_ganan(
                chat_key, ctx, partida, jugadores, impostores,
                None, palabra, categoria, detalle_votos, update.message
            )
        else:
            await update.message.reply_text(
                f"❌ *{esc(nombre(user))}* escribió *{esc(texto.lower())}*\\.\\.\\. ¡Incorrecto\\!\n\n"
                f"*{esc(nombre(user))}* queda eliminado definitivamente\\.",
                parse_mode="MarkdownV2"
            )
            if not impostores_vivos:
                await _fin_grupo_gana(chat_key, ctx, jugadores, impostores, palabra, categoria, detalle_votos, update.message)
                return
            inocentes_restantes = [v for v in vivos_restantes_ids if v not in impostor_ids_set]
            if len(inocentes_restantes) <= 1:
                await _fin_impostores_ganan(
                    chat_key, ctx, partida, jugadores, impostores,
                    None, palabra, categoria, detalle_votos, update.message, razon="supervivencia"
                )
                return
            await _nueva_ronda_pistas(chat_key, ctx, jugadores, vivos_restantes_ids, impostor_ids_set, palabra, categoria, update.message)
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

    keyboard = [[InlineKeyboardButton(
        "✅ Confirmar esta como mi pista",
        callback_data=f"confirmar_pista:{user.id}"
    )]]
    await update.message.reply_text(
        f"¿Confirmas *{esc(texto)}* como tu pista\\?",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _fin_grupo_gana(chat_key, ctx, jugadores, impostores, palabra, categoria, detalle_votos, message, bonus=False):
    """jugadores es lista de (user_id, username)"""
    impostor_ids_set = set(j[0] for j in impostores)
    for j in jugadores:
        if j[0] not in impostor_ids_set:
            sumar_victoria(chat_key, j[0])
    for imp in impostores:
        sumar_derrota(chat_key, imp[0])

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO historial (chat_key, ganador, palabra, categoria) VALUES (?,?,?,?)",
            (chat_key, "grupo", palabra, categoria)
        )
        conn.execute("UPDATE partidas SET estado='terminada' WHERE chat_key=?", (chat_key,))

    marcador = get_marcador(chat_key)
    tabla = formatear_tabla(marcador)
    nombres_impostores = ", ".join(f"*{esc(i[1])}*" for i in impostores)

    await message.reply_text(
        f"🎉 *¡El grupo ganó\\!*\n\n"
        f"Los impostores eran: {nombres_impostores}\n"
        f"¡Fueron eliminados sin adivinar la palabra\\!\n\n"
        f"🔑 La palabra era: *{esc(palabra)}* \\({esc(categoria)}\\)\n\n"
        f"*🏆 Marcador:*\n{tabla}\n\n"
        "_Usa /jugarimpostor para otra ronda_",
        parse_mode="MarkdownV2"
    )


async def _fin_impostores_ganan(chat_key, ctx, partida, jugadores, impostores, eliminado, palabra, categoria, detalle_votos, message, razon=None):
    """jugadores es lista de (user_id, username)"""
    impostor_ids_set = set(j[0] for j in impostores)
    for imp in impostores:
        sumar_victoria(chat_key, imp[0])
    for j in jugadores:
        if j[0] not in impostor_ids_set:
            sumar_derrota(chat_key, j[0])

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO historial (chat_key, ganador, palabra, categoria) VALUES (?,?,?,?)",
            (chat_key, "impostor", palabra, categoria)
        )
        conn.execute("UPDATE partidas SET estado='terminada' WHERE chat_key=?", (chat_key,))

    marcador = get_marcador(chat_key)
    tabla = formatear_tabla(marcador)
    nombres_impostores = ", ".join(f"*{esc(i[1])}*" for i in impostores)

    if razon == "supervivencia":
        desc = "Los impostores sobrevivieron hasta quedar solos con un inocente\\."
    elif eliminado is None:
        desc = "Un impostor adivinó la palabra correcta\\."
    else:
        desc = f"Votaron incorrectamente por *{esc(eliminado[1])}*\\."

    await message.reply_text(
        f"🕵️ *¡Los impostores ganaron\\!*\n\n"
        f"Eran: {nombres_impostores}\n"
        f"{desc}\n\n"
        f"🔑 La palabra era: *{esc(palabra)}* \\({esc(categoria)}\\)\n\n"
        f"*🏆 Marcador:*\n{tabla}\n\n"
        "_Usa /jugarimpostor para otra ronda_",
        parse_mode="MarkdownV2"
    )


def formatear_tabla(jugadores):
    """jugadores: [(user_id, username, victorias, derrotas), ...]
    Devuelve string con tabla monoespaciada lista para MarkdownV2 (dentro de bloque código)."""
    filas = []
    for j in jugadores:
        nombre_j = j[1][:14]  # máx 14 chars para no romper el ancho
        v = j[2]
        d = j[3]
        balance = v - d
        bal_str = f"+{balance}" if balance > 0 else str(balance)
        filas.append((nombre_j, v, d, bal_str))

    # Anchos de columna
    max_nombre = max(len(f[0]) for f in filas)
    encabezado = f"#   {'Jugador':<{max_nombre}}  V    D   Bal"
    separador  = "─" * len(encabezado)
    lineas = [encabezado, separador]
    for i, (nombre_j, v, d, bal) in enumerate(filas, 1):
        lineas.append(f"{i:<3} {nombre_j:<{max_nombre}}  {v:<4} {d:<4} {bal}")
    return "```\n" + "\n".join(lineas) + "\n```"


async def cmd_puntaje(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_key = get_chat_key(update)
    jugadores = get_marcador_global(chat_key)

    if not jugadores:
        await update.message.reply_text(
            "📊 No hay estadísticas aún\\. ¡Juega primero\\!",
            parse_mode="MarkdownV2"
        )
        return

    tabla = formatear_tabla(jugadores)
    await update.message.reply_text(
        f"🏆 *Marcador del grupo:*\n\n{tabla}",
        parse_mode="MarkdownV2"
    )


async def cmd_resetimpostor(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_key = get_chat_key(update)
    user = update.effective_user
    chat = update.effective_chat

    # Verificar que el usuario es admin del grupo
    try:
        member = await chat.get_member(user.id)
        es_admin = member.status in ("administrator", "creator")
    except Exception:
        es_admin = False

    if not es_admin:
        await update.message.reply_text("⚠️ Solo los administradores del grupo pueden resetear los puntajes.")
        return

    with get_conn() as conn:
        conn.execute(
            "UPDATE jugadores SET victorias=0, derrotas=0 WHERE chat_key=?",
            (chat_key,)
        )

    await update.message.reply_text(
        "🔄 *Puntajes reseteados\\.*\n\n"
        "Todas las victorias y derrotas vuelven a cero\\. ¡A empezar de nuevo\\! 🎮",
        parse_mode="MarkdownV2"
    )


async def cmd_cancelar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_key = get_chat_key(update)
    user = update.effective_user
    partida = get_partida(chat_key)

    if not partida or partida[2] == "terminada":
        await update.message.reply_text("⚠️ No hay ninguna partida activa.")
        return
    if partida[8] != user.id:
        await update.message.reply_text("⚠️ Solo el creador puede cancelar la partida.")
        return

    with get_conn() as conn:
        conn.execute("UPDATE partidas SET estado='terminada' WHERE chat_key=?", (chat_key,))
    await update.message.reply_text(
        "❌ Partida cancelada\\. Usa /jugarimpostor para empezar otra\\.",
        parse_mode="MarkdownV2"
    )


async def error_handler(update, ctx):
    error = ctx.error
    if isinstance(error, Conflict):
        logger.critical("⚠️ Conflicto de instancia. Saliendo...")
        os._exit(1)
    else:
        logger.error(f"Error: {error}")


def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("jugarimpostor", cmd_nueva))
    app.add_handler(CommandHandler("unirse",        cmd_unirse))
    app.add_handler(CommandHandler("votar",         cmd_votar))
    app.add_handler(CommandHandler("puntaje",       cmd_puntaje))
    app.add_handler(CommandHandler("cancelar",      cmd_cancelar))
    app.add_handler(CommandHandler("comojugar",     cmd_como_jugar))
    app.add_handler(CommandHandler("resetimpostor", cmd_resetimpostor))

    app.add_handler(CallbackQueryHandler(btn_unirse,          pattern="^unirse$"))
    app.add_handler(CallbackQueryHandler(btn_iniciar_partida, pattern="^iniciar_partida$"))
    app.add_handler(CallbackQueryHandler(btn_categoria,       pattern="^cat:"))
    app.add_handler(CallbackQueryHandler(btn_confirmar_pista, pattern="^confirmar_pista:"))
    app.add_handler(CallbackQueryHandler(btn_abrir_votar,     pattern="^abrir_votar$"))
    app.add_handler(CallbackQueryHandler(btn_voto,            pattern="^voto:"))
    app.add_handler(CallbackQueryHandler(btn_revoto,          pattern="^revoto:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_adivinanza))
    app.add_error_handler(error_handler)

    logger.info("🤖 Bot iniciado...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
