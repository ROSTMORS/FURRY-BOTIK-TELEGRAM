"""
Telegram RP-бот v2.0
Использует aiogram 3.x и SQLite.
Изменения v2: фикс инвентаря, упоминания пользователей, админ-команды,
              расширенный /quiz (20+ вопросов, лимит 10/день),
              расширенный /shop (12 предметов), новые эффекты.
"""

import asyncio
import logging
import math
import os
import random
import re
import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

# ─────────────────────────── НАСТРОЙКА ────────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ДИАГНОСТИКА
print(f"DEBUG: BOT_TOKEN = {BOT_TOKEN}")
print(f"DEBUG: All env keys = {list(os.environ.keys())}")
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN is None! Check Railway Variables")

# !! Укажи сюда свои Telegram user_id через запятую !!
_admin_env = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: list[int] = [int(x.strip()) for x in _admin_env.split(",") if x.strip().isdigit()]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

DB_FILE = "database.db"

# ─────────────────────────── БАЗА ДАННЫХ ──────────────────────────

def get_conn():
    return sqlite3.connect(DB_FILE)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id   INTEGER PRIMARY KEY,
            username  TEXT,
            balance   INTEGER DEFAULT 100,
            xp        INTEGER DEFAULT 0,
            level     INTEGER DEFAULT 1,
            daily_ts  INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS marriages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user1_id     INTEGER UNIQUE,
            user2_id     INTEGER UNIQUE,
            married_since INTEGER
        );

        -- Инвентарь: amount теперь корректно уменьшается до удаления строки
        CREATE TABLE IF NOT EXISTS inventory (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            item_id INTEGER,
            amount  INTEGER DEFAULT 1,
            UNIQUE(user_id, item_id)
        );

        CREATE TABLE IF NOT EXISTS pending_duels (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            challenger  INTEGER,
            target      INTEGER,
            amount      INTEGER,
            chat_id     INTEGER,
            message_id  INTEGER,
            ts          INTEGER
        );

        CREATE TABLE IF NOT EXISTS pending_marriages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            proposer    INTEGER,
            target      INTEGER,
            chat_id     INTEGER,
            message_id  INTEGER,
            ts          INTEGER
        );

        -- Логи действий администраторов
        CREATE TABLE IF NOT EXISTS admin_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id  INTEGER,
            action    TEXT,
            target_id INTEGER,
            details   TEXT,
            ts        INTEGER
        );

        -- Лимиты квиза: не более 10 вопросов в день (сброс по UTC-дате)
        CREATE TABLE IF NOT EXISTS quiz_attempts (
            user_id           INTEGER PRIMARY KEY,
            questions_today   INTEGER DEFAULT 0,
            last_quiz_date    TEXT DEFAULT ''
        );

        -- Активные пассивные эффекты предметов (напр. Клевер, Шляпа)
        CREATE TABLE IF NOT EXISTS item_effects (
            user_id     INTEGER PRIMARY KEY,
            lucky_slots INTEGER DEFAULT 0,
            magic_hat   INTEGER DEFAULT 0,
            hat_last_ts INTEGER DEFAULT 0,
            dragon_egg  INTEGER DEFAULT 0,
            dragon_ts   INTEGER DEFAULT 0
        );
    """)
    conn.commit()
    conn.close()

# ─────────────────── ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ──────────────────────

def ensure_user(user_id: int, username: str = ""):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username or ""))
    if username:
        c.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
    conn.commit()
    conn.close()

def get_user(user_id: int) -> Optional[dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, username, balance, xp, level, daily_ts FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return dict(zip(["user_id", "username", "balance", "xp", "level", "daily_ts"], row))
    return None

def calc_level(xp: int) -> int:
    return int(math.floor(math.sqrt(xp / 100))) + 1

def xp_for_level(level: int) -> int:
    return (level - 1) ** 2 * 100

def add_xp(user_id: int, amount: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT xp FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return
    new_xp = row[0] + amount
    new_level = calc_level(new_xp)
    c.execute("UPDATE users SET xp=?, level=? WHERE user_id=?", (new_xp, new_level, user_id))
    conn.commit()
    conn.close()

def add_balance(user_id: int, amount: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

def get_username_by_id(user_id: int) -> str:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else str(user_id)

def get_marriage(user_id: int) -> Optional[dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT user1_id, user2_id, married_since FROM marriages WHERE user1_id=? OR user2_id=?",
        (user_id, user_id),
    )
    row = c.fetchone()
    conn.close()
    if row:
        return {"user1_id": row[0], "user2_id": row[1], "married_since": row[2]}
    return None

def get_partner_id(user_id: int) -> Optional[int]:
    m = get_marriage(user_id)
    if not m:
        return None
    return m["user2_id"] if m["user1_id"] == user_id else m["user1_id"]

def mention(name: str, user_id: int) -> str:
    """Создать Markdown-упоминание пользователя по ID."""
    safe = name.replace("[", "\\[").replace("]", "\\]")
    return f"[{safe}](tg://user?id={user_id})"

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def log_admin_action(admin_id: int, action: str, target_id: int, details: str = ""):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO admin_log (admin_id, action, target_id, details, ts) VALUES (?, ?, ?, ?, ?)",
        (admin_id, action, target_id, details, int(time.time())),
    )
    conn.commit()
    conn.close()

def find_user_by_username(username: str) -> Optional[int]:
    """Найти user_id по username (без @)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE username=?", (username.lstrip("@"),))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

# ──────────────────── ЛИМИТ ВИКТОРИНЫ ─────────────────────────────

QUIZ_DAILY_LIMIT = 10

def get_quiz_today(user_id: int) -> int:
    """Сколько вопросов пользователь уже ответил сегодня (UTC)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT questions_today, last_quiz_date FROM quiz_attempts WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row or row[1] != today:
        return 0
    return row[0]

def increment_quiz_count(user_id: int):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT questions_today, last_quiz_date FROM quiz_attempts WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        c.execute(
            "INSERT INTO quiz_attempts (user_id, questions_today, last_quiz_date) VALUES (?, 1, ?)",
            (user_id, today),
        )
    elif row[1] != today:
        c.execute(
            "UPDATE quiz_attempts SET questions_today=1, last_quiz_date=? WHERE user_id=?",
            (today, user_id),
        )
    else:
        c.execute(
            "UPDATE quiz_attempts SET questions_today=questions_today+1 WHERE user_id=?",
            (user_id,),
        )
    conn.commit()
    conn.close()

# ─────────────────────────── МАГАЗИН ──────────────────────────────

SHOP_ITEMS = {
    1:  {"name": "🍎 Яблоко",              "price": 5,    "desc": "Приятный перекус. +настроение"},
    2:  {"name": "🌹 Роза",                "price": 20,   "desc": "Подари кому-то (+5 XP получателю)"},
    3:  {"name": "🎁 Подарок",             "price": 50,   "desc": "Рандомный сюрприз: 10-100 монет"},
    4:  {"name": "🧸 Плюшевый мишка",     "price": 100,  "desc": "+10 XP при покупке"},
    5:  {"name": "💊 Зелье здоровья",      "price": 30,   "desc": "+15 XP при использовании"},
    6:  {"name": "🎫 Лотерейный билет",    "price": 25,   "desc": "30% шанс выиграть 100 монет"},
    7:  {"name": "📜 Свиток опыта",        "price": 100,  "desc": "+50 XP при использовании"},
    8:  {"name": "🍀 Четырёхлистный клевер","price": 150, "desc": "+10% удачи в /slots (пассивно)"},
    9:  {"name": "🔮 Хрустальный шар",     "price": 500,  "desc": "Случайное предсказание"},
    10: {"name": "🎩 Магическая шляпа",    "price": 1000, "desc": "Рандомный предмет раз в 24ч"},
    11: {"name": "🐉 Яйцо дракона",        "price": 2500, "desc": "Вылупляется через 7 дней → редкий приз"},
    12: {"name": "👑 Корона",              "price": 5000, "desc": "+50 XP, статус «Властелин» в топе"},
}

PREDICTIONS = [
    "Сегодня удача на твоей стороне ⭐",
    "Опасайся незнакомцев с кубиками 🎲",
    "Скоро тебя ждёт неожиданный подарок 🎁",
    "Звёзды говорят: пора делать /daily 🌟",
    "Большой выигрыш совсем близко 💰",
    "Кто-то тайно тебя обожает 💕",
    "Не ходи сегодня на дуэль — удача не твоя ⚔️",
    "Отличный день для брака 💍",
    "Берегись пинков от незнакомцев 😡",
    "Твой уровень скоро вырастет 📈",
]

# ─────────────────── РП-ДЕЙСТВИЯ ──────────────────────────────────

RP_ACTIONS = {
    "обнять":          ("обнимает",           "🤗", ["крепко и нежно", "с теплотой", "по-настоящему", "так, что не хочется отпускать"]),
    "обнял":           ("обнимает",           "🤗", ["крепко", "с улыбкой", "нежно", "тепло"]),
    "обнимаю":         ("обнимает",           "🤗", ["ласково", "крепко", "с любовью", "от всей души"]),
    "поцеловать":      ("целует",             "😘", ["нежно", "в щёчку", "страстно", "слегка"]),
    "целую":           ("целует",             "😘", ["мимолётно", "с улыбкой", "нежно", "тепло"]),
    "чмок":            ("целует",             "😘", ["в лобик", "в щёчку", "быстро", "со звуком «чмок»"]),
    "погладить":       ("гладит",             "🥰", ["по голове", "нежно", "заботливо", "с умилением"]),
    "глажу":           ("гладит",             "🥰", ["аккуратно", "с теплотой", "медленно", "ласково"]),
    "поглажу":         ("гладит",             "🥰", ["нежно", "бережно", "с заботой", "успокаивающе"]),
    "пнуть":           ("пинает",             "😡", ["от всей души", "с размахом", "метко", "сильно"]),
    "пинаю":           ("пинает",             "😡", ["со злостью", "без предупреждения", "точно", "резко"]),
    "пнул":            ("пинает",             "😡", ["и убегает", "без сожаления", "прицельно", "грубо"]),
    "ударить":         ("бьёт",               "👊", ["кулаком", "с хрустом", "несильно", "звонко"]),
    "бью":             ("бьёт",               "👊", ["прямо", "с разворота", "резко", "неожиданно"]),
    "ударю":           ("бьёт",               "👊", ["предупредительно", "слегка", "с силой", "прицельно"]),
    "похвалить":       ("хвалит",             "🌟", ["от всего сердца", "с гордостью", "искренне", "с восхищением"]),
    "хвалю":           ("хвалит",             "🌟", ["заслуженно", "с улыбкой", "тепло", "щедро"]),
    "укусить":         ("кусает",             "🦷", ["слегка", "игриво", "не больно", "внезапно"]),
    "кусаю":           ("кусает",             "🦷", ["осторожно", "игриво", "нежно", "шутливо"]),
    "почесать":        ("чешет",              "🐱", ["за ушком", "по спинке", "приятно", "с удовольствием"]),
    "чешу":            ("чешет",              "🐱", ["бережно", "нежно", "умело", "с заботой"]),
    "облизать":        ("облизывает",         "👅", ["игриво", "неожиданно", "по-собачьи", "с энтузиазмом"]),
    "лижу":            ("облизывает",         "👅", ["как будто так и надо", "с хлюпом", "нагло", "игриво"]),
    "пожать руку":     ("жмёт руку",          "🤝", ["крепко", "дружески", "с уважением", "деловито"]),
    "дать пять":       ("даёт пять",          "🖐️", ["звонко", "с силой", "радостно", "не промахиваясь"]),
    "прижать":         ("прижимает",          "🤗", ["к себе", "нежно", "защитно", "крепко"]),
    "прижимаю":        ("прижимает",          "🤗", ["тепло", "с заботой", "крепко", "нежно"]),
    "покормить":       ("кормит",             "🍕", ["с ложечки", "вкусняшкой", "заботливо", "щедро"]),
    "кормлю":          ("кормит",             "🍕", ["с удовольствием", "старательно", "с любовью", "вкусно"]),
    "напоить":         ("поит",               "🍵", ["горячим чаем", "с заботой", "нежно", "вовремя"]),
    "пою":             ("поит",               "🍵", ["с теплотой", "заботливо", "щедро", "вкусно"]),
    "угостить":        ("угощает",            "🍬", ["конфеткой", "с улыбкой", "щедро", "вкусненьким"]),
    "угощаю":          ("угощает",            "🍬", ["от всей души", "сладким", "с радостью", "вкусно"]),
    "спасти":          ("спасает",            "🦸", ["в последний момент", "героически", "смело", "не раздумывая"]),
    "спасаю":          ("спасает",            "🦸", ["решительно", "бесстрашно", "вовремя", "с гордостью"]),
    "успокоить":       ("успокаивает",        "💙", ["мягко", "нежно", "с заботой", "терпеливо"]),
    "успокаиваю":      ("успокаивает",        "💙", ["ласково", "с теплотой", "медленно", "по-доброму"]),
    "потанцевать с":   ("танцует с",          "💃", ["грациозно", "весело", "задорно", "не наступая на ноги"]),
    "танцую с":        ("танцует с",          "💃", ["с ритмом", "легко", "с улыбкой", "зажигательно"]),
    "обнять со спины": ("обнимает со спины",  "🫂", ["нежно", "неожиданно", "тепло", "защитно"]),
    "покусать":        ("кусает",             "🧛", ["вампирски", "в шею", "игриво", "слегка"]),
    "пощёчина":        ("даёт пощёчину",      "✋", ["звонко", "неожиданно", "хлёстко", "заслуженно"]),
    "подушить":        ("душит в объятиях (шутливо)", "🫂💀", ["от любви", "крепко-крепко", "не отпускает", "игриво"]),
    "задушить":        ("душит",              "😤", ["злобно", "без предупреждения", "сердито", "решительно"]),
    "почесать за ушком": ("чешет за ушком",   "🐱", ["нежно", "с умилением", "заботливо", "приятно"]),
    "подмигнуть":      ("подмигивает",        "😉", ["загадочно", "игриво", "лукаво", "с улыбкой"]),
    "помахать":        ("машет рукой",        "👋", ["весело", "приветливо", "на прощание", "с улыбкой"]),
    "пошлёпать":       ("шлёпает",            "🖐️", ["слегка", "игриво", "звонко", "с ухмылкой"]),
    "взъерошить":      ("взъерошивает волосы","🤪", ["игриво", "нежно", "безбожно", "с хохотом"]),
    "поправить шапку": ("поправляет шапку",   "🧢", ["заботливо", "нежно", "с улыбкой", "аккуратно"]),
    "защитить":        ("защищает",           "🛡️", ["смело", "без колебаний", "решительно", "с гордостью"]),
    "пожалеть":        ("жалеет",             "🤗", ["с теплотой", "по-доброму", "искренне", "с объятием"]),
    "похитить":        ("похищает",           "🚗", ["в ночи", "стремительно", "шутливо", "с хохотом"]),
}

RP_ALIAS: dict[str, str] = {k.lower(): k for k in RP_ACTIONS}

def build_rp_pattern():
    keywords = sorted(RP_ALIAS.keys(), key=len, reverse=True)
    escaped = [re.escape(k) for k in keywords]
    return re.compile(r"^(" + "|".join(escaped) + r")\s*(@\S+)?\s*$", re.IGNORECASE)

RP_PATTERN = build_rp_pattern()

# ────────────────────────── ВИКТОРИНА ─────────────────────────────

QUIZ_QUESTIONS = [
    {"q": "Столица Франции?",                                    "o": ["Берлин", "Мадрид", "Париж", "Рим"],               "a": 2},
    {"q": "Сколько планет в Солнечной системе?",                 "o": ["7", "8", "9", "10"],                              "a": 1},
    {"q": "Что означает HTML?",                                   "o": ["HyperText Markup Language", "HyperTool Markup Language", "High Text Model Language", "Home Tool Markup Language"], "a": 0},
    {"q": "Самая высокая гора в мире?",                           "o": ["К2", "Килиманджаро", "Эверест", "Монблан"],       "a": 2},
    {"q": "Сколько байт в 1 килобайте (традиционно)?",           "o": ["512", "1000", "1024", "2048"],                    "a": 2},
    {"q": "Сколько дней в високосном году?",                      "o": ["365", "366", "364", "367"],                       "a": 1},
    {"q": "Кто написал «Войну и мир»?",                           "o": ["Достоевский", "Толстой", "Чехов", "Пушкин"],      "a": 1},
    {"q": "Самый распространённый газ в атмосфере Земли?",        "o": ["Кислород", "Углекислый газ", "Азот", "Аргон"],    "a": 2},
    {"q": "Столица Японии?",                                      "o": ["Пекин", "Сеул", "Токио", "Осака"],               "a": 2},
    {"q": "Сколько цветов в радуге?",                             "o": ["6", "7", "8", "5"],                               "a": 1},
    {"q": "Какой язык программирования создал Гвидо ван Россум?", "o": ["Java", "Ruby", "Python", "C++"],                 "a": 2},
    {"q": "Скорость света в вакууме (приближённо)?",              "o": ["300 км/с", "3000 км/с", "300 000 км/с", "30 000 км/с"], "a": 2},
    {"q": "В каком году Юрий Гагарин полетел в космос?",          "o": ["1957", "1959", "1961", "1965"],                   "a": 2},
    {"q": "Самая длинная река в мире?",                           "o": ["Амазонка", "Нил", "Янцзы", "Миссисипи"],         "a": 1},
    {"q": "Сколько костей в теле взрослого человека?",            "o": ["186", "206", "226", "246"],                       "a": 1},
    {"q": "Кто написал «Мастера и Маргариту»?",                   "o": ["Толстой", "Горький", "Булгаков", "Пастернак"],    "a": 2},
    {"q": "Какой элемент имеет символ Au?",                       "o": ["Серебро", "Медь", "Алюминий", "Золото"],         "a": 3},
    {"q": "Сколько сторон у правильного гексагона?",              "o": ["5", "6", "7", "8"],                               "a": 1},
    {"q": "В каком городе находится Эйфелева башня?",             "o": ["Лондон", "Берлин", "Париж", "Рим"],              "a": 2},
    {"q": "Кто изобрёл телефон?",                                 "o": ["Эдисон", "Тесла", "Белл", "Морзе"],              "a": 2},
    {"q": "Столица Австралии?",                                   "o": ["Сидней", "Мельбурн", "Канберра", "Брисбен"],     "a": 2},
    {"q": "Сколько нот в музыкальной гамме?",                     "o": ["5", "6", "7", "8"],                               "a": 2},
    {"q": "Какой цвет получится при смешении синего и жёлтого?",  "o": ["Фиолетовый", "Зелёный", "Оранжевый", "Коричневый"], "a": 1},
    {"q": "Самый большой океан на Земле?",                        "o": ["Атлантический", "Индийский", "Северный Ледовитый", "Тихий"], "a": 3},
    {"q": "Сколько минут в сутках?",                              "o": ["1200", "1440", "1380", "1320"],                   "a": 1},
]

# ─────────────────────────── /START ───────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    text = (
        "👋 Привет\\! Я — многофункциональный РП\\-бот\\!\n\n"
        "🎭 *РП\\-действия* — ответь на сообщение командой: _обнять_, _поцеловать_, _погладить_\\.\\.\\.\n"
        "🏆 *Уровни и XP* — /level, /leaderboard\n"
        "🎲 *Игры* — /dice, /d20, /coin, /rps, /slots, /duel, /quiz\n"
        "💰 *Экономика* — /balance, /daily, /give, /shop, /buy, /inventory\n"
        "💍 *Браки* — «Предложить брак @user», /marry, /divorce\n\n"
        "📋 Полный список: /help"
    )
    await message.answer(text, parse_mode="MarkdownV2")

# ─────────────────────────── /HELP ────────────────────────────────

@router.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "📋 <b>Список команд</b>\n\n"
        "<b>РП-действия</b> (ответьте на сообщение):\n"
        "обнять, поцеловать, погладить, пнуть, ударить, похвалить,\n"
        "укусить, почесать, облизать, пожать руку, дать пять,\n"
        "прижать, покормить, напоить, угостить, спасти, успокоить,\n"
        "потанцевать с, обнять со спины, покусать, пощёчина, подушить,\n"
        "задушить, почесать за ушком, подмигнуть, помахать, пошлёпать,\n"
        "взъерошить, поправить шапку, защитить, пожалеть, похитить\n\n"
        "<b>🏆 Уровни</b>\n"
        "/level — ваш уровень и XP\n"
        "/leaderboard — топ-10 (по уровню / деньгам / бракам)\n\n"
        "<b>🎲 Игры</b>\n"
        "/dice — кубик 1-6\n"
        "/d20 — кубик 1-20\n"
        "/coin — орёл/решка\n"
        "/rps камень|ножницы|бумага — игра с ботом\n"
        "/slots [сумма] — слоты (мин. 10 монет)\n"
        "/duel @user [сумма] — дуэль\n"
        "/quiz — викторина (до 10 вопросов в день)\n\n"
        "<b>💰 Экономика</b>\n"
        "/balance или /money — баланс\n"
        "/daily — ежедневный бонус (+100 монет, +10 XP)\n"
        "/give @user [сумма] — перевод монет\n"
        "/shop — магазин (12 предметов)\n"
        "/buy [номер] — купить предмет\n"
        "/inventory — инвентарь\n"
        "/use [номер] — использовать предмет\n\n"
        "<b>💍 Браки</b>\n"
        "Предложить брак @user — предложение\n"
        "/marry — информация о браке\n"
        "/divorce — развод\n"
        "/top_marriages — топ долгих браков\n"
    )
    await message.answer(text, parse_mode="HTML")

# ─────────────────────────── /LEVEL ───────────────────────────────

@router.message(Command("level"))
async def cmd_level(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    u = get_user(message.from_user.id)
    level = calc_level(u["xp"])
    xp_needed = xp_for_level(level + 1) - u["xp"]
    await message.answer(
        f"🏆 <b>{message.from_user.full_name}</b>\n"
        f"Уровень: <b>{level}</b>\n"
        f"XP: <b>{u['xp']}</b>\n"
        f"До следующего уровня: <b>{xp_needed} XP</b>",
        parse_mode="HTML",
    )

# ─────────────────────── /LEADERBOARD ─────────────────────────────

def make_leaderboard_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🏆 По уровню",  callback_data="lb_xp"),
        InlineKeyboardButton(text="💰 По деньгам", callback_data="lb_money"),
        InlineKeyboardButton(text="💍 По бракам",  callback_data="lb_marriages"),
    ]])

@router.message(Command("leaderboard"))
async def cmd_leaderboard(message: Message):
    await _send_leaderboard(message, "lb_xp")

async def _send_leaderboard(target, mode: str):
    conn = get_conn()
    c = conn.cursor()
    # Проверяем наличие предмета Корона (item_id=12) для статуса "Властелин"
    if mode == "lb_xp":
        c.execute("SELECT user_id, username, xp, level FROM users ORDER BY xp DESC LIMIT 10")
        rows = c.fetchall()
        lines = ["🏆 <b>Топ по уровню:</b>"]
        for i, (uid, name, xp, lvl) in enumerate(rows, 1):
            crown = _has_item(uid, 12)
            prefix = "👑 " if crown else ""
            lines.append(f"{i}. {prefix}{name or '???'} — Ур.{lvl} ({xp} XP)")
    elif mode == "lb_money":
        c.execute("SELECT user_id, username, balance FROM users ORDER BY balance DESC LIMIT 10")
        rows = c.fetchall()
        lines = ["💰 <b>Топ по монетам:</b>"]
        for i, (uid, name, bal) in enumerate(rows, 1):
            crown = _has_item(uid, 12)
            prefix = "👑 " if crown else ""
            lines.append(f"{i}. {prefix}{name or '???'} — {bal} 🪙")
    else:
        c.execute(
            "SELECT u1.username, u2.username, m.married_since "
            "FROM marriages m "
            "JOIN users u1 ON u1.user_id=m.user1_id "
            "JOIN users u2 ON u2.user_id=m.user2_id "
            "ORDER BY m.married_since ASC LIMIT 10"
        )
        rows = c.fetchall()
        lines = ["💍 <b>Топ самых долгих браков:</b>"]
        for i, (n1, n2, ts) in enumerate(rows, 1):
            days = (int(time.time()) - ts) // 86400
            lines.append(f"{i}. {n1 or '???'} & {n2 or '???'} — {days} дн.")
    conn.close()
    text = "\n".join(lines)
    kb = make_leaderboard_kb()
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=kb)

def _has_item(user_id: int, item_id: int) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT amount FROM inventory WHERE user_id=? AND item_id=? AND amount>0", (user_id, item_id))
    row = c.fetchone()
    conn.close()
    return bool(row)

@router.callback_query(F.data.in_({"lb_xp", "lb_money", "lb_marriages"}))
async def cb_leaderboard(call: CallbackQuery):
    await call.answer()
    await _send_leaderboard(call, call.data)

# ───────────────────────── МИНИ-ИГРЫ ──────────────────────────────

@router.message(Command("dice"))
async def cmd_dice(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    await message.answer(f"🎲 Выпало: <b>{random.randint(1, 6)}</b>!", parse_mode="HTML")

@router.message(Command("d20"))
async def cmd_d20(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    r = random.randint(1, 20)
    suffix = " 🌟 <b>КРИТ!</b>" if r == 20 else (" 💀 <b>ПРОВАЛ!</b>" if r == 1 else "")
    await message.answer(f"🎲 D20: <b>{r}</b>{suffix}", parse_mode="HTML")

@router.message(Command("coin"))
async def cmd_coin(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    result = random.choice(["🦅 Орёл", "✍️ Решка"])
    await message.answer(f"🪙 <b>{result}</b>!", parse_mode="HTML")

@router.message(Command("rps"))
async def cmd_rps(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or args[1].lower() not in ("камень", "ножницы", "бумага"):
        await message.answer("✋ Использование: /rps [камень|ножницы|бумага]")
        return
    choices = ["камень", "ножницы", "бумага"]
    emojis = {"камень": "🪨", "ножницы": "✂️", "бумага": "📄"}
    wins = {"камень": "ножницы", "ножницы": "бумага", "бумага": "камень"}
    user_choice = args[1].lower()
    bot_choice = random.choice(choices)
    if user_choice == bot_choice:
        result, extra = "🤝 Ничья!", "+5 XP, +5 🪙"
        add_xp(message.from_user.id, 5); add_balance(message.from_user.id, 5)
    elif wins[user_choice] == bot_choice:
        result, extra = "🎉 Вы победили!", "+15 XP, +20 🪙"
        add_xp(message.from_user.id, 15); add_balance(message.from_user.id, 20)
    else:
        result, extra = "😔 Бот победил!", ""
    await message.answer(
        f"Вы: {emojis[user_choice]} {user_choice}\nБот: {emojis[bot_choice]} {bot_choice}\n\n<b>{result}</b> {extra}",
        parse_mode="HTML",
    )

@router.message(Command("slots"))
async def cmd_slots(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("🎰 Использование: /slots [сумма] (мин. 10)")
        return
    bet = int(args[1])
    if bet < 10:
        await message.answer("❌ Минимальная ставка — 10 монет.")
        return
    u = get_user(message.from_user.id)
    if u["balance"] < bet:
        await message.answer("❌ Недостаточно монет!")
        return

    # Проверяем бонус клевера (+10% удачи)
    lucky = _has_item(message.from_user.id, 8)
    symbols = ["🍒", "🍋", "🍊", "🍇", "⭐", "🔔"]
    s1, s2, s3 = random.choice(symbols), random.choice(symbols), random.choice(symbols)
    add_balance(message.from_user.id, -bet)

    win = False
    if s1 == s2 == s3:
        win = True
    elif lucky and random.random() < 0.10:
        # +10% шанс превратить почти-победу в победу
        s3 = s1
        win = s1 == s2 == s3

    if win:
        prize = bet * 2
        add_balance(message.from_user.id, prize)
        add_xp(message.from_user.id, 15)
        result = f"🎉 ДЖЕКПОТ! Выигрыш: <b>{prize}</b> монет! +15 XP"
    else:
        result = f"😔 Не повезло. Потеряно: <b>{bet}</b> монет."
    await message.answer(f"🎰 | {s1} | {s2} | {s3} |\n\n{result}", parse_mode="HTML")

@router.message(Command("duel"))
async def cmd_duel(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    args = message.text.split()
    if len(args) < 3 or not args[1].startswith("@") or not args[2].isdigit():
        await message.answer("⚔️ Использование: /duel @username [сумма]")
        return
    amount = int(args[2])
    if amount <= 0:
        await message.answer("❌ Сумма должна быть > 0.")
        return
    challenger = get_user(message.from_user.id)
    if challenger["balance"] < amount:
        await message.answer("❌ Недостаточно монет.")
        return
    target_id = find_user_by_username(args[1])
    if not target_id:
        await message.answer("❌ Пользователь не найден в базе.")
        return
    if target_id == message.from_user.id:
        await message.answer("❌ Нельзя дуэлировать с собой.")
        return
    target_user = get_user(target_id)
    if target_user["balance"] < amount:
        await message.answer(f"❌ У {mention(target_user['username'], target_id)} недостаточно монет.", parse_mode="Markdown")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⚔️ Принять",    callback_data=f"duel_accept_{message.from_user.id}_{target_id}_{amount}"),
        InlineKeyboardButton(text="🏳️ Отказаться", callback_data=f"duel_decline_{message.from_user.id}"),
    ]])
    await message.answer(
        f"⚔️ {mention(message.from_user.full_name, message.from_user.id)} вызывает "
        f"{mention(target_user['username'] or str(target_id), target_id)} на дуэль\\!\n"
        f"Ставка: *{amount}* монет 🪙\n\n"
        f"{mention(target_user['username'] or str(target_id), target_id)}, принимаешь вызов?",
        parse_mode="MarkdownV2",
        reply_markup=kb,
    )

@router.callback_query(F.data.startswith("duel_accept_"))
async def cb_duel_accept(call: CallbackQuery):
    _, _, challenger_id, target_id, amount = call.data.split("_")
    challenger_id, target_id, amount = int(challenger_id), int(target_id), int(amount)
    if call.from_user.id != target_id:
        await call.answer("Это не ваша дуэль!", show_alert=True)
        return
    c_user = get_user(challenger_id)
    t_user = get_user(target_id)
    if c_user["balance"] < amount or t_user["balance"] < amount:
        await call.message.edit_text("❌ Недостаточно монет у одного из участников. Дуэль отменена.", reply_markup=None)
        return
    c_roll, t_roll = random.randint(1, 6), random.randint(1, 6)
    c_name = get_username_by_id(challenger_id)
    t_name = get_username_by_id(target_id)
    if c_roll == t_roll:
        await call.message.edit_text(
            f"🎲 {mention(c_name, challenger_id)}: {c_roll} vs {mention(t_name, target_id)}: {t_roll}\n🤝 Ничья\\! Монеты возвращены\\.",
            parse_mode="MarkdownV2", reply_markup=None,
        )
    else:
        if c_roll > t_roll:
            winner_id, loser_id, winner_name = challenger_id, target_id, c_name
        else:
            winner_id, loser_id, winner_name = target_id, challenger_id, t_name
        add_balance(loser_id, -amount)
        add_balance(winner_id, amount)
        add_xp(winner_id, 15)
        await call.message.edit_text(
            f"⚔️ Дуэль завершена\\!\n"
            f"🎲 {mention(c_name, challenger_id)}: {c_roll}\n"
            f"🎲 {mention(t_name, target_id)}: {t_roll}\n\n"
            f"🏆 Победил {mention(winner_name, winner_id)}\\! \\+{amount} монет, \\+15 XP",
            parse_mode="MarkdownV2", reply_markup=None,
        )
    await call.answer()

@router.callback_query(F.data.startswith("duel_decline_"))
async def cb_duel_decline(call: CallbackQuery):
    challenger_id = int(call.data.split("_")[2])
    c_name = get_username_by_id(challenger_id)
    await call.message.edit_text(
        f"🏳️ {mention(call.from_user.full_name, call.from_user.id)} отказался от дуэли с {mention(c_name, challenger_id)}\\.",
        parse_mode="MarkdownV2", reply_markup=None,
    )
    await call.answer()

@router.message(Command("quiz"))
async def cmd_quiz(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    # Проверка лимита
    today_count = get_quiz_today(message.from_user.id)
    if today_count >= QUIZ_DAILY_LIMIT:
        await message.answer("🛑 Ты сегодня уже ответил(а) на 10 вопросов! Возвращайся завтра. 📅")
        return
    q = random.choice(QUIZ_QUESTIONS)
    buttons = [
        [InlineKeyboardButton(
            text=opt,
            callback_data=f"quiz_{i}_{q['a']}_{message.from_user.id}",
        )]
        for i, opt in enumerate(q["o"])
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    remaining = QUIZ_DAILY_LIMIT - today_count
    await message.answer(
        f"❓ <b>Вопрос:</b> {q['q']}\n\n<i>Осталось попыток сегодня: {remaining - 1}</i>",
        parse_mode="HTML",
        reply_markup=kb,
    )

@router.callback_query(F.data.startswith("quiz_"))
async def cb_quiz(call: CallbackQuery):
    parts = call.data.split("_")
    chosen, correct, owner_id = int(parts[1]), int(parts[2]), int(parts[3])
    if call.from_user.id != owner_id:
        await call.answer("Это не ваша викторина!", show_alert=True)
        return
    increment_quiz_count(owner_id)
    if chosen == correct:
        add_balance(owner_id, 50)
        add_xp(owner_id, 15)
        await call.message.edit_text("✅ Правильно! +50 монет, +15 XP 🎉", reply_markup=None)
    else:
        await call.message.edit_text("❌ Неверно! Попыток потрачено. Попробуй /quiz снова.", reply_markup=None)
    await call.answer()

# ─────────────────────────── ЭКОНОМИКА ────────────────────────────

@router.message(Command(commands=["balance", "money"]))
async def cmd_balance(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    u = get_user(message.from_user.id)
    await message.answer(
        f"💰 <b>{message.from_user.full_name}</b>\nБаланс: <b>{u['balance']}</b> 🪙",
        parse_mode="HTML",
    )

@router.message(Command("daily"))
async def cmd_daily(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    u = get_user(message.from_user.id)
    now = int(time.time())
    if now - u["daily_ts"] < 86400:
        remaining = 86400 - (now - u["daily_ts"])
        h, m = divmod(remaining // 60, 60)
        await message.answer(f"⏳ Следующий бонус через: <b>{h}ч {m}м</b>", parse_mode="HTML")
        return
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET balance=balance+100, daily_ts=? WHERE user_id=?", (now, message.from_user.id))
    conn.commit()
    conn.close()
    add_xp(message.from_user.id, 10)
    await message.answer("🎁 Ежедневный бонус: <b>+100 монет, +10 XP</b>!", parse_mode="HTML")

@router.message(Command("give"))
async def cmd_give(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    args = message.text.split()
    if len(args) < 3 or not args[1].startswith("@") or not args[2].isdigit():
        await message.answer("💸 Использование: /give @username [сумма]")
        return
    amount = int(args[2])
    if amount <= 0:
        await message.answer("❌ Сумма должна быть > 0.")
        return
    sender = get_user(message.from_user.id)
    if sender["balance"] < amount:
        await message.answer("❌ Недостаточно монет!")
        return
    target_id = find_user_by_username(args[1])
    if not target_id:
        await message.answer("❌ Пользователь не найден.")
        return
    if target_id == message.from_user.id:
        await message.answer("❌ Нельзя переводить самому себе.")
        return
    target_user = get_user(target_id)
    add_balance(message.from_user.id, -amount)
    add_balance(target_id, amount)
    await message.answer(
        f"✅ Вы перевели <b>{amount} 🪙</b> пользователю {mention(target_user['username'] or str(target_id), target_id)}!",
        parse_mode="HTML",
    )

@router.message(Command("shop"))
async def cmd_shop(message: Message):
    lines = ["🛒 <b>Магазин</b>\n"]
    for num, item in SHOP_ITEMS.items():
        lines.append(f"{num}. {item['name']} — <b>{item['price']} 🪙</b>\n   <i>{item['desc']}</i>")
    lines.append("\nКупить: /buy [номер]")
    await message.answer("\n".join(lines), parse_mode="HTML")

def _add_to_inventory(user_id: int, item_id: int):
    """Добавить 1 единицу предмета в инвентарь (upsert)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO inventory (user_id, item_id, amount) VALUES (?, ?, 1) "
        "ON CONFLICT(user_id, item_id) DO UPDATE SET amount = amount + 1",
        (user_id, item_id),
    )
    conn.commit()
    conn.close()

def _remove_from_inventory(user_id: int, item_id: int) -> bool:
    """
    Уменьшить количество предмета на 1.
    Если количество стало 0 — удалить строку.
    Возвращает True если предмет был и операция успешна.
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT amount FROM inventory WHERE user_id=? AND item_id=?", (user_id, item_id))
    row = c.fetchone()
    if not row or row[0] <= 0:
        conn.close()
        return False
    if row[0] == 1:
        c.execute("DELETE FROM inventory WHERE user_id=? AND item_id=?", (user_id, item_id))
    else:
        c.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id=? AND item_id=?", (user_id, item_id))
    conn.commit()
    conn.close()
    return True

@router.message(Command("buy"))
async def cmd_buy(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("🛒 Использование: /buy [номер]")
        return
    item_id = int(args[1])
    if item_id not in SHOP_ITEMS:
        await message.answer("❌ Нет такого предмета. Смотри /shop.")
        return
    item = SHOP_ITEMS[item_id]
    u = get_user(message.from_user.id)
    if u["balance"] < item["price"]:
        await message.answer(f"❌ Нужно {item['price']} 🪙, у вас {u['balance']} 🪙.")
        return
    add_balance(message.from_user.id, -item["price"])
    _add_to_inventory(message.from_user.id, item_id)

    bonus = ""
    # Мгновенные бонусы при покупке
    if item_id == 4:
        add_xp(message.from_user.id, 10); bonus = " +10 XP!"
    elif item_id == 12:
        add_xp(message.from_user.id, 50); bonus = " +50 XP! Статус «👑 Властелин» активен."
    elif item_id == 11:
        # Сохраняем время покупки яйца дракона
        conn = get_conn(); c = conn.cursor()
        c.execute(
            "INSERT INTO item_effects (user_id, dragon_egg, dragon_ts) VALUES (?, 1, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET dragon_egg=1, dragon_ts=?",
            (message.from_user.id, int(time.time()), int(time.time())),
        )
        conn.commit(); conn.close()
        bonus = " Яйцо вылупится через 7 дней!"
    elif item_id == 10:
        # Активируем магическую шляпу
        conn = get_conn(); c = conn.cursor()
        c.execute(
            "INSERT INTO item_effects (user_id, magic_hat) VALUES (?, 1) "
            "ON CONFLICT(user_id) DO UPDATE SET magic_hat=1",
            (message.from_user.id,),
        )
        conn.commit(); conn.close()
        bonus = " Теперь используй /hat каждые 24ч!"

    await message.answer(f"✅ Куплено: {item['name']}!{bonus}", parse_mode="HTML")

@router.message(Command("inventory"))
async def cmd_inventory(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT item_id, amount FROM inventory WHERE user_id=? AND amount>0", (message.from_user.id,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        await message.answer("🎒 Инвентарь пуст.")
        return
    lines = ["🎒 <b>Инвентарь</b>:\n"]
    for item_id, amount in rows:
        item = SHOP_ITEMS.get(item_id)
        if item:
            lines.append(f"{item_id}. {item['name']} × {amount}")
    lines.append("\nИспользовать: /use [номер]")
    await message.answer("\n".join(lines), parse_mode="HTML")

# БАГ-ФИКС: /use теперь корректно уменьшает количество и удаляет строку при 0
@router.message(Command(commands=["use", "use_item"]))
async def cmd_use(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("🎒 Использование: /use [номер]")
        return
    item_id = int(args[1])

    # Сначала проверяем наличие, потом применяем эффект
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT amount FROM inventory WHERE user_id=? AND item_id=?", (message.from_user.id, item_id))
    row = c.fetchone()
    conn.close()

    if not row or row[0] <= 0:
        await message.answer("❌ У вас нет такого предмета.")
        return

    # Применяем эффект (до удаления, чтобы можно было реагировать на ошибки)
    response = await _apply_item_effect(message, item_id)
    if response is None:
        return  # эффект требует reply и его нет

    # Уменьшаем количество / удаляем предмет
    _remove_from_inventory(message.from_user.id, item_id)
    await message.answer(response, parse_mode="HTML")

async def _apply_item_effect(message: Message, item_id: int) -> Optional[str]:
    """Применить эффект предмета. Возвращает текст ответа или None при ошибке."""
    uid = message.from_user.id
    if item_id == 1:
        return "🍎 Вы съели яблоко. Хруск! Настроение +100%"
    elif item_id == 2:
        if not message.reply_to_message:
            await message.answer("🌹 Ответьте на сообщение того, кому хотите подарить розу.")
            return None
        target = message.reply_to_message.from_user
        ensure_user(target.id, target.username or target.full_name)
        add_xp(target.id, 5)
        return f"🌹 Вы подарили розу {mention(target.full_name, target.id)}! (+5 XP им)"
    elif item_id == 3:
        gift = random.randint(10, 100)
        add_balance(uid, gift)
        return f"🎁 Открыт подарок! Внутри <b>{gift} монет</b>! 🎉"
    elif item_id == 4:
        return "🧸 Вы обнимаете плюшевого мишку. Так уютно~"
    elif item_id == 5:
        add_xp(uid, 15)
        return "💊 Выпито зелье здоровья. +15 XP! Чувствуешь себя лучше."
    elif item_id == 6:
        if random.random() < 0.30:
            add_balance(uid, 100)
            return "🎫 Лотерея: 🎉 <b>Победа!</b> +100 монет!"
        else:
            return "🎫 Лотерея: 😔 Не повезло. Удачи в следующий раз."
    elif item_id == 7:
        add_xp(uid, 50)
        return "📜 Свиток опыта использован. +50 XP! ✨"
    elif item_id == 8:
        # Активируем пассивный эффект клевера
        conn = get_conn(); c = conn.cursor()
        c.execute(
            "INSERT INTO item_effects (user_id, lucky_slots) VALUES (?, 1) "
            "ON CONFLICT(user_id) DO UPDATE SET lucky_slots=1",
            (uid,),
        )
        conn.commit(); conn.close()
        return "🍀 Четырёхлистный клевер активирован! Удача в /slots +10%."
    elif item_id == 9:
        pred = random.choice(PREDICTIONS)
        return f"🔮 Хрустальный шар говорит:\n<i>«{pred}»</i>"
    elif item_id == 10:
        return "🎩 Магическая шляпа уже работает пассивно. Используй /hat для получения предмета."
    elif item_id == 11:
        # Проверяем вылупление
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT dragon_ts FROM item_effects WHERE user_id=?", (uid,))
        row = c.fetchone()
        conn.close()
        if row and (int(time.time()) - row[0]) >= 7 * 86400:
            prizes = [3, 6, 7, 9]
            prize_id = random.choice(prizes)
            _add_to_inventory(uid, prize_id)
            prize_name = SHOP_ITEMS[prize_id]["name"]
            return f"🐉 Яйцо вылупилось! Дракончик принёс тебе: <b>{prize_name}</b>! 🎉"
        elif row:
            days_left = 7 - (int(time.time()) - row[0]) // 86400
            return f"🥚 Яйцо ещё не вылупилось. Осталось ~{days_left} дн."
        else:
            return "🥚 Нет активного яйца дракона."
    elif item_id == 12:
        return "👑 Корона уже надета! Ваш статус «Властелин» виден в /leaderboard."
    return "❓ Неизвестный предмет."

# Команда /hat — получить рандомный предмет от Магической шляпы
@router.message(Command("hat"))
async def cmd_hat(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    if not _has_item(message.from_user.id, 10):
        await message.answer("🎩 У вас нет Магической шляпы. Купите в /shop!")
        return
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT hat_last_ts FROM item_effects WHERE user_id=?", (message.from_user.id,))
    row = c.fetchone()
    now = int(time.time())
    if row and (now - row[0]) < 86400:
        remaining = 86400 - (now - row[0])
        h, m = divmod(remaining // 60, 60)
        conn.close()
        await message.answer(f"🎩 Шляпа уже использована. Следующий предмет через {h}ч {m}м.")
        return
    gift_id = random.choice(list(SHOP_ITEMS.keys())[:-3])  # не самые дорогие
    _add_to_inventory(message.from_user.id, gift_id)
    c.execute(
        "INSERT INTO item_effects (user_id, hat_last_ts) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET hat_last_ts=?",
        (message.from_user.id, now, now),
    )
    conn.commit()
    conn.close()
    await message.answer(
        f"🎩 Шляпа достала из себя: <b>{SHOP_ITEMS[gift_id]['name']}</b>!",
        parse_mode="HTML",
    )

# ─────────────────────────── БРАКИ ────────────────────────────────

@router.message(F.text.regexp(r"(?i)^предложить\s+брак\s+@(\S+)"))
async def cmd_propose(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    match = re.match(r"(?i)^предложить\s+брак\s+@(\S+)", message.text)
    target_username = match.group(1)
    if get_marriage(message.from_user.id):
        await message.answer("❌ Вы уже состоите в браке!")
        return
    target_id = find_user_by_username(target_username)
    if not target_id:
        await message.answer("❌ Пользователь не найден.")
        return
    if target_id == message.from_user.id:
        await message.answer("❌ Нельзя жениться на себе.")
        return
    if get_marriage(target_id):
        await message.answer(f"❌ @{target_username} уже состоит в браке.")
        return
    t_user = get_user(target_id)
    t_name = t_user["username"] or str(target_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❤️ Согласиться", callback_data=f"marry_yes_{message.from_user.id}_{target_id}"),
        InlineKeyboardButton(text="💔 Отказаться",  callback_data=f"marry_no_{message.from_user.id}"),
    ]])
    await message.answer(
        f"💍 {mention(message.from_user.full_name, message.from_user.id)} делает предложение "
        f"{mention(t_name, target_id)}\\!\n\n"
        f"{mention(t_name, target_id)}, ты согласен\\(на\\)?",
        parse_mode="MarkdownV2",
        reply_markup=kb,
    )

@router.callback_query(F.data.startswith("marry_yes_"))
async def cb_marry_yes(call: CallbackQuery):
    _, _, proposer_id, target_id = call.data.split("_")
    proposer_id, target_id = int(proposer_id), int(target_id)
    if call.from_user.id != target_id:
        await call.answer("Это предложение не вам!", show_alert=True)
        return
    if get_marriage(proposer_id) or get_marriage(target_id):
        await call.message.edit_text("❌ Один из участников уже в браке.", reply_markup=None)
        return
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO marriages (user1_id, user2_id, married_since) VALUES (?, ?, ?)",
        (proposer_id, target_id, int(time.time())),
    )
    conn.commit(); conn.close()
    add_xp(proposer_id, 100); add_xp(target_id, 100)
    p_name = get_username_by_id(proposer_id)
    t_name = get_username_by_id(target_id)
    await call.message.edit_text(
        f"💍🎉 {mention(p_name, proposer_id)} и {mention(t_name, target_id)} теперь женаты\\!\n"
        f"Поздравляем\\! Оба получают \\+100 XP\\! 🥂",
        parse_mode="MarkdownV2", reply_markup=None,
    )
    await call.answer()

@router.callback_query(F.data.startswith("marry_no_"))
async def cb_marry_no(call: CallbackQuery):
    proposer_id = int(call.data.split("_")[2])
    p_name = get_username_by_id(proposer_id)
    await call.message.edit_text(
        f"💔 {mention(call.from_user.full_name, call.from_user.id)} отказал\\(а\\) "
        f"{mention(p_name, proposer_id)}\\.\\.\\.",
        parse_mode="MarkdownV2", reply_markup=None,
    )
    await call.answer()

@router.message(Command("marry"))
async def cmd_marry_info(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    m = get_marriage(message.from_user.id)
    if not m:
        await message.answer("💔 Вы не состоите в браке.")
        return
    partner_id = m["user2_id"] if m["user1_id"] == message.from_user.id else m["user1_id"]
    partner_name = get_username_by_id(partner_id)
    days = (int(time.time()) - m["married_since"]) // 86400
    await message.answer(
    f'💍 Вы женаты с <a href="tg://user?id={partner_id}">{partner_name}</a>\n'
    f'Дней вместе: <b>{days}</b>',
    parse_mode="HTML",
)

@router.message(Command("divorce"))
async def cmd_divorce(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    if not get_marriage(message.from_user.id):
        await message.answer("💔 Вы не состоите в браке.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да, развестись", callback_data=f"divorce_confirm_{message.from_user.id}"),
        InlineKeyboardButton(text="❌ Отмена",          callback_data="divorce_cancel"),
    ]])
    await message.answer("⚠️ Уверены, что хотите развестись?", reply_markup=kb)

@router.callback_query(F.data.startswith("divorce_confirm_"))
async def cb_divorce_confirm(call: CallbackQuery):
    user_id = int(call.data.split("_")[2])
    if call.from_user.id != user_id:
        await call.answer("Это не ваш запрос!", show_alert=True)
        return
    conn = get_conn(); c = conn.cursor()
    c.execute("DELETE FROM marriages WHERE user1_id=? OR user2_id=?", (user_id, user_id))
    conn.commit(); conn.close()
    await call.message.edit_text("💔 Развод оформлен. Грустно...", reply_markup=None)
    await call.answer()

@router.callback_query(F.data == "divorce_cancel")
async def cb_divorce_cancel(call: CallbackQuery):
    await call.message.edit_text("✅ Отменено. Живите счастливо! 💕", reply_markup=None)
    await call.answer()

@router.message(Command("top_marriages"))
async def cmd_top_marriages(message: Message):
    conn = get_conn(); c = conn.cursor()
    c.execute(
        "SELECT u1.username, u1.user_id, u2.username, u2.user_id, m.married_since "
        "FROM marriages m "
        "JOIN users u1 ON u1.user_id=m.user1_id "
        "JOIN users u2 ON u2.user_id=m.user2_id "
        "ORDER BY m.married_since ASC LIMIT 10"
    )
    rows = c.fetchall(); conn.close()
    if not rows:
        await message.answer("💍 Браков ещё нет!")
        return
    lines = ["💍 <b>Топ долгих браков:</b>\n"]
    for i, (n1, id1, n2, id2, ts) in enumerate(rows, 1):
        days = (int(time.time()) - ts) // 86400
        lines.append(f"{i}. {n1 or '???'} & {n2 or '???'} — {days} дн.")
    await message.answer("\n".join(lines), parse_mode="HTML")

# ─────────────────────────── АДМИН-КОМАНДЫ ────────────────────────

def admin_only(func):
    """Декоратор: только для администраторов."""
    async def wrapper(message: Message):
        if not is_admin(message.from_user.id):
            await message.answer("🚫 Нет доступа.")
            return
        await func(message)
    wrapper.__name__ = func.__name__
    return wrapper

@router.message(Command("add_money"))
@admin_only
async def cmd_add_money(message: Message):
    args = message.text.split()
    if len(args) < 3 or not args[2].lstrip("-").isdigit():
        await message.answer("Использование: /add_money @username [сумма]")
        return
    target_id = find_user_by_username(args[1])
    if not target_id:
        await message.answer("❌ Пользователь не найден.")
        return
    amount = int(args[2])
    add_balance(target_id, amount)
    log_admin_action(message.from_user.id, "add_money", target_id, str(amount))
    await message.answer(f"✅ Баланс {args[1]} изменён на {amount:+} 🪙")

@router.message(Command("remove_money"))
@admin_only
async def cmd_remove_money(message: Message):
    args = message.text.split()
    if len(args) < 3 or not args[2].isdigit():
        await message.answer("Использование: /remove_money @username [сумма]")
        return
    target_id = find_user_by_username(args[1])
    if not target_id:
        await message.answer("❌ Пользователь не найден.")
        return
    amount = int(args[2])
    add_balance(target_id, -amount)
    log_admin_action(message.from_user.id, "remove_money", target_id, f"-{amount}")
    await message.answer(f"✅ Снято {amount} 🪙 с {args[1]}")

@router.message(Command("add_xp"))
@admin_only
async def cmd_add_xp(message: Message):
    args = message.text.split()
    if len(args) < 3 or not args[2].isdigit():
        await message.answer("Использование: /add_xp @username [количество]")
        return
    target_id = find_user_by_username(args[1])
    if not target_id:
        await message.answer("❌ Пользователь не найден.")
        return
    amount = int(args[2])
    add_xp(target_id, amount)
    log_admin_action(message.from_user.id, "add_xp", target_id, str(amount))
    await message.answer(f"✅ +{amount} XP начислено {args[1]}")

@router.message(Command("reset_inventory"))
@admin_only
async def cmd_reset_inventory(message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /reset_inventory @username")
        return
    target_id = find_user_by_username(args[1])
    if not target_id:
        await message.answer("❌ Пользователь не найден.")
        return
    conn = get_conn(); c = conn.cursor()
    c.execute("DELETE FROM inventory WHERE user_id=?", (target_id,))
    conn.commit(); conn.close()
    log_admin_action(message.from_user.id, "reset_inventory", target_id)
    await message.answer(f"✅ Инвентарь {args[1]} очищен.")

@router.message(Command("reset_daily"))
@admin_only
async def cmd_reset_daily(message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /reset_daily @username")
        return
    target_id = find_user_by_username(args[1])
    if not target_id:
        await message.answer("❌ Пользователь не найден.")
        return
    conn = get_conn(); c = conn.cursor()
    c.execute("UPDATE users SET daily_ts=0 WHERE user_id=?", (target_id,))
    conn.commit(); conn.close()
    log_admin_action(message.from_user.id, "reset_daily", target_id)
    await message.answer(f"✅ Ежедневный бонус {args[1]} сброшен.")

@router.message(Command("broadcast"))
@admin_only
async def cmd_broadcast(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /broadcast [текст сообщения]")
        return
    text = args[1]
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    all_users = [row[0] for row in c.fetchall()]
    conn.close()

    sent, failed = 0, 0
    for uid in all_users:
        try:
            await bot.send_message(uid, f"📢 <b>Сообщение от администратора:</b>\n\n{text}", parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)  # антиспам пауза
        except Exception:
            failed += 1
    log_admin_action(message.from_user.id, "broadcast", 0, f"sent={sent}, failed={failed}")
    await message.answer(f"📢 Рассылка завершена. Отправлено: {sent}, ошибок: {failed}.")

# ─────────────────────────── РП-ХЭНДЛЕР ──────────────────────────

@router.message(F.text)
async def rp_handler(message: Message):
    if not message.text:
        return
    m = RP_PATTERN.match(message.text.strip())
    if not m:
        return

    if message.reply_to_message is None:
        await message.reply("💬 Чтобы совершить действие, ответьте на сообщение нужного пользователя!")
        return

    keyword = m.group(1).lower()
    canonical = RP_ALIAS.get(keyword)
    if not canonical:
        return

    verb, emoji, phrases = RP_ACTIONS[canonical]
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    target = message.reply_to_message.from_user
    ensure_user(target.id, target.username or target.full_name)

    actor_name = message.from_user.full_name
    actor_id   = message.from_user.id
    target_name = target.full_name
    target_id   = target.id
    phrase = random.choice(phrases)

    # Проверка на брак для "обнять"
    partner_id = get_partner_id(actor_id)
    is_spouse  = partner_id == target_id

    if canonical in ("обнять", "обнял", "обнимаю") and is_spouse:
        xp_gain = 10
        text = (
            f"❤️ {mention(actor_name, actor_id)} нежно обнимает своего\\(ю\\) супруг\\(у\\) "
            f"{mention(target_name, target_id)} с особой теплотой\\! ❤️"
        )
        parse = "MarkdownV2"
    else:
        xp_gain = 5
        text = (
            f"{mention(actor_name, actor_id)} {verb} {mention(target_name, target_id)} "
            f"{phrase} {emoji}"
        )
        parse = "Markdown"

    add_xp(actor_id, xp_gain)
    await message.answer(text, parse_mode=parse)

# ──────────────────────────── ЗАПУСК ──────────────────────────────

async def main():
    init_db()
    if not ADMIN_IDS:
        logger.warning("⚠️  ADMIN_IDS не заданы! Добавь свой ID в .env: ADMIN_IDS=123456789")
    logger.info("Бот запускается...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
