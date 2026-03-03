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

# ── Configuración ──────────────────────────────────────────────
import os
TOKEN = os.environ.get("BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Palabras por categoría ─────────────────────────────────────
CATEGORIAS = {
    "🐾 Animales": [
        # Mamíferos salvajes
        "León", "Tigre", "Leopardo", "Guepardo", "Jaguar",
        "Elefante", "Jirafa", "Hipopótamo", "Rinoceronte", "Cebra",
        "Gorila", "Chimpancé", "Orangután", "Koala", "Canguro",
        "Panda", "Oso polar", "Oso grizzly", "Lobo", "Zorro",
        "Camello", "Bisonte", "Alce", "Ciervo", "Jabalí",

        # Mamíferos marinos y acuáticos
        "Delfín", "Ballena", "Orca", "Foca", "Manatí",
        "Nutria", "Castor", "Hipopótamo",

        # Reptiles y anfibios
        "Cocodrilo", "Caimán", "Iguana", "Camaleón", "Gecko",
        "Tortuga", "Serpiente", "Cobra", "Anaconda", "Dragón de Komodo",
        "Salamandra", "Rana toro",

        # Aves
        "Flamenco", "Pingüino", "Tucán", "Loro", "Cóndor",
        "Águila", "Búho", "Pavo real", "Pelícano", "Colibrí",
        "Avestruz", "Kiwi",

        # Marinos e invertebrados
        "Tiburón", "Pulpo", "Medusa", "Mantarraya", "Caballito de mar",
        "Estrella de mar", "Cangrejo", "Langosta", "Pez payaso",

        # Exóticos / curiosos
        "Murciélago", "Ornitorrinco", "Armadillo", "Pangolín", "Axolote",
        "Tarántula", "Escorpión", "Mantis religiosa",
    ],
    "⚽ Deportes": [
        # Deportes de equipo
        "Fútbol", "Baloncesto", "Voleibol", "Rugby", "Hockey sobre hielo",
        "Béisbol", "Waterpolo", "Handball", "Fútbol americano",
        "Cricket", "Polo", "Ultimate Frisbee",

        # Deportes de raqueta
        "Tenis", "Pádel", "Bádminton", "Squash", "Tenis de mesa",
       
        # Deportes de combate
        "Boxeo", "Judo", "Karate", "Taekwondo", "Esgrima",
        "Lucha libre", "Sumo", "Muay Thai", "Kendo",

        # Deportes acuáticos
        "Natación", "Surf", "Waterpolo", "Remo", "Kayak",
        "Vela", "Esquí acuático", "Buceo", "Triatlón", "Natación sincronizada",

        # Deportes de montaña y aventura
        "Escalada", "Esquí", "Snowboard", "Parapente", "Rappel",
        "Senderismo", "Ciclismo de montaña",

        # Atletismo y pista
        "Maratón", "Salto de altura", "Lanzamiento de jabalina", "Decatlón",

        # Otros
        "Golf", "Arquería", "Ciclismo", "Patinaje artístico", "Gimnasia",
        "Tiro con arco", "Equitación",
    ],
    "🌍 Lugares del mundo": [
        # Maravillas y monumentos
        "Machu Picchu", "Coliseo Romano", "Torre Eiffel", "Taj Mahal", "Gran Muralla China",
        "Stonehenge", "Angkor Wat", "Petra", "Cristo Redentor", "Pirámides de Giza",
        "Alhambra", "Sagrada Familia", "Big Ben", "Estatua de la Libertad", "Kremlin",

        # Ciudades icónicas
        "Times Square", "Tokio", "Venecia", "Dubái", "Bangkok",
        "Estambul", "Río de Janeiro", "Ciudad del Cabo", "Singapur", "Praga",
        "Buenos Aires", "Marrakech", "Amsterdam", "Nueva Orleans", "Kioto",

        # Naturaleza y geografía
        "Sahara", "Amazonas", "Patagonia", "Islandia", "Maldivas",
        "Gran Cañón", "Siberia", "Antártida", "Serengeti", "Fiordos Noruegos",
        "Gran Barrera de Coral", "Selva Negra", "Desierto de Atacama", "Valle de la Muerte", "Galápagos",

        # Ríos, lagos y mares
        "Lago Titicaca", "Mar Muerto", "Río Nilo", "Lago Baikal", "Cataratas del Niágara",
        "Cataratas Victoria", "Mar Mediterráneo", "Río Amazonas", "Mar Caribe",

        # Regiones y países míticos
        "La Toscana", "Bali", "Santorini", "Cappadocia", "Polinesia Francesa",
        "Tibet", "Laponia", "Zanzibar", "Maasai Mara", "Borneo",
    ],
    "📦 Objetos cotidianos": [
        # Hogar
        "Paraguas", "Espejo", "Percha", "Colador", "Embudo",
        "Tijeras", "Candado", "Lupa", "Brújula", "Termómetro",
        "Reloj", "Cuaderno", "Mesa", "Silla", "Lámpara",
        "Almohada", "Manta", "Cortina", "Jabonera", "Tapete",
        "Florero", "Portarretratos", "Cesto de ropa", "Tabla de planchar", "Escoba",

        # Cocina
        "Sartén", "Olla", "Cuchillo", "Tenedor", "Cuchara",
        "Rallador", "Abrebotellas", "Corcho", "Delantal", "Batidora",
        "Tostadora", "Microondas", "Mortero", "Pinzas de cocina", "Mandolina",

        # Escritorio y oficina
        "Calculadora", "Maletín", "Destornillador", "Grapadora", "Regla",
        "Sacapuntas", "Borrador", "Clip", "Carpeta", "Sello",
        "Archivador", "Pizarrón", "Rotulador", "Compás", "Resaltador",

        # Bolso y personal
        "Billetera", "Llavero", "Pañuelo", "Paraguas plegable", "Agenda",
        "Auriculares", "Cargador", "Termo", "Cantimplora", "Linterna",

        # Herramientas
        "Martillo", "Alicates", "Cinta métrica", "Nivel", "Sierra",
        "Taladro", "Llave inglesa", "Pincel", "Rodillo", "Escalera",
    ],
    "🎨 Colores": [
        "Turquesa", "Magenta", "Escarlata", "Índigo", "Negro",
        "Lavanda", "Carmesí", "Rosado", "Marfil", "Rojo",
        "Amarillo", "Violeta", "Dorado", "Plateado", "Coral", "Azul", "Blanco",
    ],
    "🌐 Países": [
        # Europa
        "Noruega", "Grecia", "Portugal", "Islandia", "Suecia",
        "Finlandia", "Dinamarca", "Polonia", "Hungría", "Rumania",
        "Croacia", "Serbia", "Austria", "Suiza", "Bélgica",
        "Países Bajos", "Irlanda", "Escocia", "Albania", "Montenegro",

        # América
        "Brasil", "Argentina", "Colombia", "Chile", "Perú",
        "México", "Canadá", "Cuba", "Venezuela", "Bolivia",
        "Ecuador", "Uruguay", "Paraguay", "Costa Rica", "Panamá",
        "Guatemala", "Honduras", "Jamaica", "República Dominicana", "Haití",

        # Asia
        "Japón", "Tailandia", "India", "China", "Corea del Sur", "Corea del Norte"
        "Vietnam", "Indonesia", "Filipinas", "Malasia", "Nepal",
        "Pakistán", "Bangladés", "Sri Lanka", "Myanmar", "Camboya",
        "Mongolia", "Kazajistán", "Uzbekistán", "Georgia", "Armenia",

        # África
        "Marruecos", "Sudáfrica", "Egipto",
        "Tanzania", "Ghana", "Senegal", "Nigeria", "Túnez",
        "Argelia", "Mozambique", "Madagascar", "Zimbabue", "Camerún",

        # Medio Oriente y Oceanía
        "Australia", "Nueva Zelanda",
        "Israel", "Irán", "Iraq", "Arabia Saudita",
    ],
    "🎌 Anime": [
        # Personajes icónicos
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

        # Series / títulos
        "Dragon Ball", "Naruto", "One Piece", "Bleach", "Attack on Titan",
        "Fullmetal Alchemist", "Death Note", "Hunter x Hunter", "Demon Slayer", "My Hero Academia",
        "Neon Genesis Evangelion", "Cowboy Bebop", "Sword Art Online", "Tokyo Ghoul", "Fairy Tail",
        "One Punch Man", "Jujutsu Kaisen", "Chainsaw Man", "Spy x Family", "Re:Zero",
        "Steins;Gate", "Code Geass", "No Game No Life", "Overlord", "Black Clover",
        "Vinland Saga", "Mob Psycho 100", "Violet Evergarden", "Your Lie in April", "Clannad",

        # Estudios y conceptos
        "Studio Ghibli", "Shonen Jump", "Isekai", "Tsundere", "Shōnen",
        "Seinen", "Mecha", "Openning", "Filler", "Mangaka",
    ],
    "⚽ Futbolistas": [
        # Leyendas históricas
        "Pelé", "Diego Maradona", "Johan Cruyff", "Franz Beckenbauer", "Ronaldo Nazário",
        "Zinedine Zidane", "Ronaldinho", "Roberto Carlos", "Cafu", "Paolo Maldini",
        "Franco Baresi", "Marco van Basten", "Ruud Gullit", "George Best", "Bobby Charlton",
        "Michel Platini", "Eusébio", "Garrincha", "Lev Yashin", "Ferenc Puskás",

        # Generación 2000-2010
        "Thierry Henry", "Andrés Iniesta", "Xavi Hernández", "Steven Gerrard", "Frank Lampard",
        "Wayne Rooney", "Fernando Torres", "David Villa", "Kaká", "Samuel Eto'o",
        "Didier Drogba", "Gianluigi Buffon", "Carles Puyol", "John Terry", "Ashley Cole",

        # Era moderna
        "Lionel Messi", "Cristiano Ronaldo", "Neymar", "Luka Modric", "Sergio Ramos",
        "Luis Suárez", "Zlatan Ibrahimović", "Arjen Robben", "Franck Ribéry", "Iker Casillas",
        "Manuel Neuer", "Sergio Busquets", "David Silva", "Cesc Fàbregas", "Mesut Özil",

        # Actuales
        "Kylian Mbappé", "Erling Haaland", "Vinicius Jr", "Pedri", "Gavi",
        "Rodri", "Jude Bellingham", "Phil Foden", "Bukayo Saka", "Jamal Musiala",
        "Federico Valverde", "Rafael Leão", "Victor Osimhen", "Mohamed Salah", "Sadio Mané",
        "Kevin De Bruyne", "Harry Kane", "Marcus Rashford", "Trent Alexander-Arnold", "Alphonso Davies",
    ],
    "🎤 K-Pop": [
        # Grupos de chicos (4ta generación)
        "Stray Kids", "ATEEZ", "TXT", "ENHYPEN", "NCT Dream",
        "TREASURE", "THE BOYZ", "MONSTA X", "VICTON", "BTOB",
        "P1Harmony", "TEMPEST", "ZEROBASEONE", "BOYNEXTDOOR", "RIIZE",

        # Grupos de chicos (3ra generación)
        "BTS", "EXO", "GOT7", "SEVENTEEN", "NCT 127",
        "SHINee", "BIGBANG", "2PM", "INFINITE", "VIXX",
        "WINNER", "iKON", "ASTRO", "DAY6", "HIGHLIGHT",

        # Grupos de chicas (4ta generación)
        "BLACKPINK", "TWICE", "aespa", "IVE", "NewJeans",
        "ITZY", "NMIXX", "LE SSERAFIM", "MAMAMOO", "Red Velvet",
        "Kep1er", "STAYC", "EVERGLOW", "WEEEKLY", "tripleS", "BABYMONSTER",

        # Grupos de chicas (3ra generación)
        "Girls Generation", "f(x)", "2NE1", "Wonder Girls", "T-ARA",
        "SISTAR", "4MINUTE", "AOA", "APINK", "EXID",

        # Soloistas masculinos
        "G-Dragon", "Taeyang", "Daesung", "Seungri", "T.O.P",
        "PSY", "Rain", "Se7en", "Zico", "Jay Park",
        "Dean", "Crush", "Dynamic Duo", "Epik High", "Loco",

        # BTS (todos)
        "RM", "Jin", "Suga", "J-Hope", "Jimin",
        "V", "Jungkook",

        # EXO (más populares)
        "Baekhyun", "Chanyeol", "D.O", "Kai", "Sehun",
        "Suho", "Xiumin", "Chen", "Lay",

        # SEVENTEEN (más populares)
        "Woozi", "Mingyu", "Vernon", "Hoshi", "Jeonghan",
        "S.Coups", "The8", "Dino",

        # Stray Kids (todos)
        "Bang Chan", "Lee Know", "Changbin", "Hyunjin", "Han",
        "Felix", "Seungmin", "I.N",

        # ATEEZ (todos)
        "Hongjoong", "Seonghwa", "Yunho", "Yeosang", "San",
        "Mingi", "Wooyoung", "Jongho",

        # SHINee (todos)
        "Onew", "Key", "Minho", "Taemin",

        # Soloistas femeninas
        "IU", "Sunmi", "HyunA", "Chungha", "Heize",
        "Jessi", "Somi", "Gain", "BoA", "CL",

        # BLACKPINK (todas)
        "Jennie", "Lisa", "Rosé", "Jisoo",

        # TWICE (todas)
        "Nayeon", "Jeongyeon", "Momo", "Sana", "Jihyo",
        "Mina", "Dahyun", "Chaeyoung", "Tzuyu",

        # aespa (todas)
        "Karina", "Giselle", "Winter", "Ningning",

        # IVE (todas)
        "Yujin", "Gaeul", "Rei", "Wonyoung", "Liz", "Leeseo",

        # NewJeans (todas)
        "Minji", "Hanni", "Danielle", "Haerin", "Hyein",

        # Red Velvet (todas)
        "Irene", "Seulgi", "Wendy", "Joy", "Yeri",

        # ITZY (todas)
        "Yeji", "Lia", "Ryujin", "Chaeryeong", "Yuna",

        # LE SSERAFIM (todas)
        "Sakura", "Chaewon", "Yunjin", "Kazuha", "Eunchae",

        # Girls Generation (todas)
        "Taeyeon", "Tiffany", "Yoona", "Yuri", "Sooyoung",
        "Hyoyeon", "Sunny", "Seohyun",

        # MAMAMOO (todas)
        "Solar", "Moonbyul", "Wheein", "Hwasa",

        # NMIXX (todas)
        "Lily", "Haewon", "Sullyoon", "Jinni", "Bae",
        "Jiwoo", "Kyujin",

        # STAYC (todas)
        "Sumin", "Sieun", "ISA", "Seeun", "Yoon", "J",

        # Kep1er (todas)
        "Yujin", "Mashiro", "Chaehyun", "Hikaru", "Huening Bahiyyih",
        "Dayeon", "Xiaoting", "Yeseo", "Youngeun",

        # EVERGLOW (todas)
        "Aisha", "Sihyeon", "Mia", "Onda", "E:U", "Yiren",

        # (G)I-DLE (todas)
        "Miyeon", "Minnie", "Soojin", "Soyeon", "Yuqi", "Shuhua",

        # EXID (todas)
        "Solji", "LE", "Hani", "Hyelin", "Jeonghwa",

        # APINK (todas)
        "Chorong", "Bomi", "Eunji", "Namjoo", "Hayoung",

        # tripleS (más populares)
        "Kotone", "Seoyeon", "Hyerin", "Jiwoo", "Chaeyeon",
        "Soomin", "Nara", "Dahyun",

        # WEEEKLY (todas)
        "Jihan", "Monday", "Soeun", "Jaehee", "Zoa", "Heeyeon", "Dayeon",
        
        # BABYMONSTER (todas)
        "Ruka", "Pharita", "Asa", "Rami", "Ahyeon",
        "Rora", "Chiquita",

        # VIVIZ (todas)
        "SinB", "Eunha", "Umji",
    ],
    "🍽️ Comidas del mundo": [
        # Pastas y arroces
        "Pizza", "Pasta Carbonara", "Lasaña", "Risotto", "Paella",
        "Sushi", "Ramen", "Arroz frito", "Bibimbap",

        # Carnes y proteínas
        "Hamburguesa", "Hot Dog", "Asado argentino", "Peking Duck", "Shawarma",
        "Kebab", "Tacos", "Barbacoa", "Churrasco", "Cordero al horno",

        # Sopas y caldos
        "Tom Yum", "Gazpacho", "Borscht", "Caldo de pollo",
        "Miso", "Minestrone", "Goulash", "Ceviche",

        # Panes y bocadillos
        "Croissant", "Bagel", "Pretzel", "Falafel", "Empanada",
        "Arepa", "Tortilla", "Naan", "Baguette", "Pita",

        # Platos típicos
        "Curry", "Hummus", "Moussaka", "Couscous", "Kimchi",
        "Tempura", "Dim Sum", "Gyoza", "Burrito", "Enchilada",
        "Ceviche", "Tiramisu", "Crêpe", "Waffle", "Empanada",

        # Postres y dulces
        "Cheesecake", "Macarons", "Baklava", "Mochi", "Churros",
        "Crème Brûlée", "Brownie", "Donut", "Cannoli", "Profiteroles",

        # Desayunos icónicos
        "Pancakes", "Eggs Benedict", "Granola", "Acai Bowl", "Shakshuka",

        # Snacks y street food
        "Nachos", "Spring Rolls", "Samosa", "Poutine", "Arepas",
        "Fish and Chips", "Currywurst", "Takoyaki", "Elote", "Pupusas",
    ],
    "🌟 Famosos": [
        # Actores de Hollywood
        "Tom Hanks", "Meryl Streep", "Leonardo DiCaprio", "Scarlett Johansson", "Denzel Washington",
        "Brad Pitt", "Angelina Jolie", "Johnny Depp", "Natalie Portman", "Cate Blanchett",
        "Robert Downey Jr", "Chris Evans", "Margot Robbie", "Ryan Reynolds", "Dwayne Johnson",
        "Will Smith", "Morgan Freeman", "Samuel L. Jackson", "Jennifer Lawrence", "Emma Stone",

        # Directores y creadores
        "Steven Spielberg", "Christopher Nolan", "Quentin Tarantino", "Martin Scorsese", "Tim Burton",

        # Músicos globales
        "Michael Jackson", "Madonna", "Beyoncé", "Taylor Swift", "Rihanna",
        "Eminem", "Drake", "Bad Bunny", "J Balvin", "Shakira",
        "Ed Sheeran", "Adele", "Lady Gaga", "Justin Bieber", "Billie Eilish",
        "The Weeknd", "Kanye West", "Jay-Z", "Ariana Grande", "Dua Lipa",

        # Influencers y streamers
        "MrBeast", "PewDiePie", "Ibai", "Auronplay", "TheGrefg",
        "Ninja", "Pokimane", "xQc", "Rubius", "Vegetta777",

        # Empresarios y figuras públicas
        "Elon Musk", "Jeff Bezos", "Mark Zuckerberg", "Steve Jobs", "Bill Gates",
    ],
    "🎬 Películas & Series": [
        # Películas clásicas
        "El Padrino", "Titanic", "Schindler's List", "Pulp Fiction", "Forrest Gump",
        "El Rey León", "Matrix", "Gladiador", "Interstellar", "Inception",
        "El Señor de los Anillos", "Star Wars", "Indiana Jones", "Jurassic Park", "Alien",
        "Terminator", "RoboCop", "Blade Runner", "2001 Odisea en el espacio", "Psicosis",

        # Películas modernas
        "Avatar", "Avengers Endgame", "Spider-Man", "Batman", "Superman",
        "Black Panther", "Iron Man", "Doctor Strange", "Joker", "Oppenheimer",
        "Barbie", "Top Gun", "John Wick", "Everything Everywhere", "Get Out",

        # Series icónicas
        "Breaking Bad", "Game of Thrones", "The Wire", "Los Soprano", "The Office",
        "Friends", "Seinfeld", "Lost", "24", "House of Cards",
        "Stranger Things", "Black Mirror", "Peaky Blinders", "Narcos", "Dexter",
        "The Crown", "Chernobyl", "Squid Game", "Dark", "Severance",

        # Animadas
        "Los Simpsons", "South Park", "Futurama", "Rick y Morty", "Bob's Burgers",
        "Avatar La Leyenda de Aang", "Arcane", "Bojack Horseman", "Gravity Falls", "Steven Universe",

        # Personajes icónicos
        "Walter White", "Tony Soprano", "Daenerys Targaryen", "Jon Snow", "Tyrion Lannister",
        "Hannibal Lecter", "James Bond", "Indiana Jones", "Ellen Ripley", "El Guasón",
    ],
    "💼 Profesiones": [
        # Salud
        "Médico", "Enfermero", "Cirujano", "Psicólogo", "Dentista",
        "Veterinario", "Farmacéutico", "Fisioterapeuta", "Paramédico", "Nutricionista",

        # Tecnología
        "Programador", "Diseñador web", "Ingeniero de software", "Hacker ético", "Analista de datos",
        "Inteligencia artificial", "Administrador de redes", "Desarrollador móvil", "DevOps", "CTO",

        # Arte y entretenimiento
        "Actor", "Director de cine", "Músico", "Fotógrafo", "Ilustrador",
        "Escritor", "Periodista", "Diseñador gráfico", "Animador", "Productor musical",

        # Educación y ciencia
        "Maestro", "Profesor universitario", "Científico", "Arqueólogo", "Astrónomo",
        "Biólogo marino", "Geólogo", "Antropólogo", "Historiador", "Filósofo",

        # Servicios y oficios
        "Chef", "Bombero", "Policía", "Abogado", "Juez",
        "Arquitecto", "Piloto", "Astronauta", "Detective", "Diplomático",
        "Mecánico", "Electricista", "Carpintero", "Plomero", "Soldador",

        # Deportes y aventura
        "Futbolista", "Atleta olímpico", "Entrenador personal", "Árbitro", "Escalador profesional",
        "Buzo", "Piloto de carreras", "Jinete", "Surfista profesional", "Boxeador",
    ],
}


ANTHROPIC_CLIENT = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

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
        return "1\\. Piensa en sus características principales\n2\\. Recuerda dónde o cómo se usa"



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
        "`/jugarimpostor` — Crear una partida\n"
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
        f"🎮 *{esc(nombre(user))} creó una nueva partida del juego Impostor\\!*\n\n"
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
        await reply_fn("⚠️ No hay ninguna partida abierta. Usa /jugarimpostor para crear una.")
        return

    upsert_jugador(chat_id, user.id, nombre(user))
    jugadores = get_jugadores(chat_id)
    lista = "\n".join(f"  {i+1}\\. {esc(j[1])}" for i, j in enumerate(jugadores))

    creador_id = partida[6]
    keyboard = []
    if len(jugadores) >= 3:
        keyboard = [[InlineKeyboardButton("🚀 ¡Iniciar partida!", callback_data="iniciar_partida")]]

    await reply_fn(
        f"✅ *{esc(nombre(user))} se unió\\!*\n\n"
        f"*Jugadores* \\({len(jugadores)}\\):\n{lista}\n\n"
        + ("_El creador puede iniciar cuando quiera\\._" if len(jugadores) >= 3 else f"_Faltan {3 - len(jugadores)} jugadores más para poder iniciar\\._"),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
    )

async def btn_iniciar_partida(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    user = update.effective_user

    partida = get_partida(chat_id)
    if not partida or partida[1] != "esperando":
        await query.answer("No hay partida en espera.", show_alert=True)
        return
    if partida[6] != user.id:
        await query.answer("⚠️ Solo el creador puede iniciar la partida.", show_alert=True)
        return

    jugadores = get_jugadores(chat_id)
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

async def cmd_iniciar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    partida = get_partida(chat_id)

    if not partida or partida[1] != "esperando":
        await update.message.reply_text("⚠️ No hay partida en espera. Usa /jugarimpostor.")
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
    keyboard.append([InlineKeyboardButton("🎲 ¡Sorpréndeme! (Random)", callback_data="cat:RANDOM")])
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

    if categoria == "RANDOM":
        categoria = random.choice(list(CATEGORIAS.keys()))

    palabra = random.choice(CATEGORIAS[categoria])
    jugadores = get_jugadores(chat_id)
    impostor = random.choice(jugadores)

    with get_conn() as conn:
        conn.execute(
            "UPDATE partidas SET estado='jugando', categoria=?, palabra=?, impostor_id=? WHERE chat_id=?",
            (categoria, palabra, impostor[0], chat_id)
        )

    texto_cat_confirmacion = "🎲 *¡Categoría sorpresa\\!*" if query.data == "cat:RANDOM" else f"✅ Categoría: *{esc(categoria)}*"

    await query.edit_message_text(
        f"{texto_cat_confirmacion}\n\n📩 Enviando palabras en privado\\.\\.\\.",
        parse_mode="MarkdownV2"
    )

    # Generar pistas con IA (una sola llamada, se reutilizan para todos)
    pistas_raw = generar_pistas(palabra, categoria)
    pistas = esc(pistas_raw)

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
                    f"💡 *Cómo puedes describirla:*\n{pistas}\n\n"
                    "_Da pistas sin decir la palabra directamente\\. ¡Encuentra al impostor\\!_ 🕵️"
                )
            await ctx.bot.send_message(uid, msg, parse_mode="MarkdownV2")
        except Exception:
            fallidos.append(uname)

    orden = list(jugadores)
    random.shuffle(orden)
    turno_lista = "\n".join(
        f"  {i+1}\\. {esc(j[1])}" for i, j in enumerate(orden)
    )

    aviso = ""
    if fallidos:
        aviso = (
            "\n\n⚠️ No pude enviar mensaje a: "
            + ", ".join(esc(f) for f in fallidos)
            + "\n_Deben iniciar conversación con el bot primero_"
        )

    texto_cat_grupo = "🎲 *¡Categoría sorpresa\\!*" if query.data == "cat:RANDOM" else f"Categoría: *{esc(categoria)}*"

    await ctx.bot.send_message(
        chat_id,
        f"🎮 *¡La partida comienza\\!*\n\n"
        f"{texto_cat_grupo}\n\n"
        f"*🎲 Orden de pistas \\(elegido al azar\\):*\n{turno_lista}\n\n"
        f"Cada uno da *una pista* sobre la palabra sin decirla directamente\\.\n"
        f"Cuando todos hayan dado su pista, usen /votar 🗳️"
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
    impostor_id = partida[4]
    impostor = next((j for j in jugadores if j[0] == impostor_id), None)
    eliminado = next((j for j in jugadores if j[0] == eliminado_id), None)
    palabra = partida[3]
    categoria = partida[2]

    nombre_map = {j[0]: j[1] for j in jugadores}
    detalle_votos = "\n".join(
        f"  • {esc(nombre_map.get(v_from, '?'))} → {esc(nombre_map.get(v_to, '?'))}"
        for v_from, v_to in votos.items()
    )

    if eliminado_id != impostor_id:
        # El grupo votó mal → impostor gana directo
        await _fin_impostor_gana(chat_id, ctx, partida, jugadores, impostor, eliminado, palabra, categoria, detalle_votos, message)
        return

    # ✅ El grupo identificó al impostor → darle oportunidad de adivinar
    with get_conn() as conn:
        conn.execute(
            "UPDATE partidas SET estado='adivinando' WHERE chat_id=?", (chat_id,)
        )

    # Guardar contexto para usar en el message handler
    ctx.bot_data[f"adivinando_{chat_id}"] = {
        "impostor_id": impostor_id,
        "palabra": palabra,
        "categoria": categoria,
        "jugadores": jugadores,
        "detalle_votos": detalle_votos,
        "partida": partida,
    }

    await message.reply_text(
        f"🎯 *¡El grupo votó por {esc(impostor[1])}\\!*\n\n"
        f"🕵️ *{esc(impostor[1])}*, ¡esta es tu última oportunidad\\!\n\n"
        f"Si adivinas la palabra secreta, *¡ganarás la ronda\\!*\n\n"
        f"📝 Escribe tu respuesta ahora en el chat\\.\n"
        f"_Categoría: {esc(categoria)}_",
        parse_mode="MarkdownV2"
    )

async def _fin_grupo_gana(chat_id, ctx, jugadores, impostor, palabra, categoria, detalle_votos, message, bonus=False):
    for j in jugadores:
        if j[0] != impostor[0]:
            sumar_puntos(chat_id, j[0], 2)

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO historial (chat_id, ganador, palabra, categoria) VALUES (?,?,?,?)",
            (chat_id, "grupo", palabra, categoria)
        )
        conn.execute("UPDATE partidas SET estado='terminada' WHERE chat_id=?", (chat_id,))

    jugadores_act = get_jugadores(chat_id)
    lineas = []
    for i, j in enumerate(jugadores_act):
        medal = '🥇' if i==0 else '🥈' if i==1 else '🥉' if i==2 else f'{i+1}\\.'
        lineas.append(f"  {medal} {esc(j[1])}: *{j[2]} pts*")
    puntaje = "\n".join(lineas)

    await message.reply_text(
        f"🎉 *¡El grupo ganó\\!*\n\n"
        f"¡Encontraron al impostor *{esc(impostor[1])}* y no pudo adivinar la palabra\\!\n\n"
        f"🔑 La palabra era: *{esc(palabra)}* \\({esc(categoria)}\\)\n\n"
        f"*Votos:*\n{detalle_votos}\n\n"
        f"*🏆 Puntaje:*\n{puntaje}\n\n"
        "_Usa /jugarimpostor para jugar otra ronda_",
        parse_mode="MarkdownV2"
    )


async def _fin_impostor_gana(chat_id, ctx, partida, jugadores, impostor, eliminado, palabra, categoria, detalle_votos, message):
    # Quitar puntos al grupo si los tenían esta ronda (no se puede revertir fácilmente, se restan 2)
    for j in jugadores:
        if j[0] != impostor[0]:
            with get_conn() as conn:
                conn.execute(
                    "UPDATE jugadores SET puntos = MAX(0, puntos - 2) WHERE chat_id=? AND user_id=?",
                    (chat_id, j[0])
                )
    sumar_puntos(chat_id, impostor[0], 3)

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO historial (chat_id, ganador, palabra, categoria) VALUES (?,?,?,?)",
            (chat_id, "impostor", palabra, categoria)
        )
        conn.execute("UPDATE partidas SET estado='terminada' WHERE chat_id=?", (chat_id,))

    jugadores_act = get_jugadores(chat_id)
    lineas = []
    for i, j in enumerate(jugadores_act):
        medal = '🥇' if i==0 else '🥈' if i==1 else '🥉' if i==2 else f'{i+1}\\.'
        lineas.append(f"  {medal} {esc(j[1])}: *{j[2]} pts*")
    puntaje = "\n".join(lineas)

    desc = (
        f"*{esc(impostor[1])}* era el impostor y no fue descubierto\\! \\+3 pts 🏆\n"
        f"Votaron incorrectamente por *{esc(eliminado[1])}*"
        if eliminado and eliminado[0] != impostor[0]
        else f"*{esc(impostor[1])}* adivinó la palabra correcta\\! \\+3 pts 🏆"
    )

    await message.reply_text(
        f"🕵️ *¡El impostor ganó\\!*\n\n"
        f"{desc}\n\n"
        f"🔑 La palabra era: *{esc(palabra)}* \\({esc(categoria)}\\)\n\n"
        f"*Votos:*\n{detalle_votos}\n\n"
        f"*🏆 Puntaje:*\n{puntaje}\n\n"
        "_Usa /jugarimpostor para jugar otra ronda_",
        parse_mode="MarkdownV2"
    )

async def cmd_puntaje(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    jugadores = get_jugadores(chat_id)

    if not jugadores:
        await update.message.reply_text("📊 No hay puntajes aún\\. ¡Juega una partida primero\\!", parse_mode="MarkdownV2")
        return

    lineas = []
    for i, j in enumerate(jugadores):
        medal = '🥇' if i==0 else '🥈' if i==1 else '🥉' if i==2 else f'{i+1}\\.'
        lineas.append(f"  {medal} {esc(j[1])}: *{j[2]} pts*")
    tabla = "\n".join(lineas)
    
    await update.message.reply_text(
        f"🏆 *Puntaje del grupo:*\n\n{tabla}",
        parse_mode="MarkdownV2"
    )

async def handle_adivinanza(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    texto = update.message.text.strip().lower()

    datos = ctx.bot_data.get(f"adivinando_{chat_id}")
    if not datos:
        return

    partida = get_partida(chat_id)
    if not partida or partida[1] != "adivinando":
        return

    # Solo responde el impostor
    if user.id != datos["impostor_id"]:
        return

    palabra = datos["palabra"]
    jugadores = datos["jugadores"]
    categoria = datos["categoria"]
    detalle_votos = datos["detalle_votos"]
    impostor = next((j for j in jugadores if j[0] == user.id), None)

    # Limpiar el estado
    ctx.bot_data.pop(f"adivinando_{chat_id}", None)

    if texto == palabra.lower():
        # ✅ Adivinó → impostor gana
        await update.message.reply_text(
            f"🎯 *¡{esc(nombre(user))} adivinó la palabra\\!*\n\n"
            f"La palabra era *{esc(palabra)}* y la escribió correctamente\\. ¡El impostor gana\\! 🕵️",
            parse_mode="MarkdownV2"
        )
        await _fin_impostor_gana(
            chat_id, ctx, partida, jugadores, impostor, None,
            palabra, categoria, detalle_votos, update.message
        )
    else:
        # ❌ Falló → grupo gana
        await update.message.reply_text(
            f"❌ *{esc(nombre(user))}* escribió *{esc(texto)}*\\.\\.\\. ¡Incorrecto\\!\n\n"
            f"La palabra era *{esc(palabra)}*\\. ¡El grupo gana\\! 🎉",
            parse_mode="MarkdownV2"
        )
        await _fin_grupo_gana(
            chat_id, ctx, jugadores, impostor,
            palabra, categoria, detalle_votos, update.message
        )

async def cmd_cancelar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    with get_conn() as conn:
        conn.execute("UPDATE partidas SET estado='terminada' WHERE chat_id=?", (chat_id,))
    await update.message.reply_text("❌ Partida cancelada\\. Usa /jugarimpostor para empezar otra\\.", parse_mode="MarkdownV2")

async def error_handler(update, ctx):
    error = ctx.error
    if isinstance(error, Conflict):
        logger.critical("⚠️ Conflicto de instancia. Saliendo con sys.exit...")
        os._exit(1)  # Fuerza cierre total del proceso
    else:
        logger.error(f"Error: {error}")


# ── Main ───────────────────────────────────────────────────────
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("jugarimpostor", cmd_nueva))
    app.add_handler(CommandHandler("unirse",   cmd_unirse))
    app.add_handler(CommandHandler("iniciar", cmd_iniciar))
    app.add_handler(CommandHandler("votar",    cmd_votar))
    app.add_handler(CommandHandler("puntaje",  cmd_puntaje))
    app.add_handler(CommandHandler("cancelar", cmd_cancelar))

    app.add_handler(CallbackQueryHandler(btn_unirse,    pattern="^unirse$"))
    app.add_handler(CallbackQueryHandler(btn_iniciar_partida, pattern="^iniciar_partida$"))
    app.add_handler(CallbackQueryHandler(btn_categoria, pattern="^cat:"))
    app.add_handler(CallbackQueryHandler(btn_voto,      pattern="^voto:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_adivinanza))
    app.add_error_handler(error_handler)
    
    logger.info("🤖 Bot iniciado...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
