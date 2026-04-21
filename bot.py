"""
Telegram RP-бот v3.0
Использует aiogram 3.x и SQLite.
v2: фикс инвентаря, упоминания пользователей, админ-команды,
    расширенный /quiz (20+ вопросов, лимит 10/день),
    расширенный /shop (12 предметов), новые эффекты.
v3: ДОБАВЛЕНО (без изменения существующего):
    - Достижения (12 ачивок) + /achievements + /achievement
    - Фурри-ранги (по уровню) + /rank + кнопка в /leaderboard
    - Кастомные РП-команды + /create_rp + /my_rp + /delete_rp + /top_rp
    - Статистика + /stats + /top_activity + /top_rp_actions
    - Случайный бонус дня + /daily_bonus + /bonus_info
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
import shutil
from datetime import datetime

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

DB_FILE = "/app/data/database.db"

# ─────────────────────────── БАЗА ДАННЫХ ──────────────────────────

def get_conn():
    return sqlite3.connect(DB_FILE)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    # ── СУЩЕСТВУЮЩИЕ ТАБЛИЦЫ (НЕ МЕНЯТЬ) ──
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

    # ── НОВЫЕ ТАБЛИЦЫ v3 ──
    c.executescript("""
        -- Достижения пользователей
        CREATE TABLE IF NOT EXISTS achievements (
            user_id        INTEGER,
            achievement_id INTEGER,
            earned_at      INTEGER,
            PRIMARY KEY (user_id, achievement_id)
        );

        -- Кастомные РП-команды
        CREATE TABLE IF NOT EXISTS custom_rp (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER,
            keyword    TEXT,
            response   TEXT,
            uses_count INTEGER DEFAULT 0,
            created_at INTEGER,
            UNIQUE(user_id, keyword)
        );

               -- Статистика пользователей
        CREATE TABLE IF NOT EXISTS user_stats (
            user_id             INTEGER PRIMARY KEY,
            total_rp_actions    INTEGER DEFAULT 0,
            total_games_played  INTEGER DEFAULT 0,
            total_duels_won     INTEGER DEFAULT 0,
            total_money_given   INTEGER DEFAULT 0,
            total_quiz_correct  INTEGER DEFAULT 0,
            first_seen          INTEGER DEFAULT 0,
            last_seen           INTEGER DEFAULT 0
        );
        
        -- ELO рейтинг для дуэлей
        CREATE TABLE IF NOT EXISTS elo_ratings (
            user_id INTEGER PRIMARY KEY,
            rating INTEGER DEFAULT 1000,
            games_played INTEGER DEFAULT 0,
            games_won INTEGER DEFAULT 0
        );
        
        -- Лог случайного бонуса дня
        CREATE TABLE IF NOT EXISTS daily_bonus_log (
            user_id    INTEGER,
            bonus_date TEXT,
            bonus_type TEXT,
            PRIMARY KEY (user_id, bonus_date)
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
    # Предмет для достижения ID 12 (Истинный фурри)
    13: {"name": "🦊 Лисий хвост",         "price": 0,    "desc": "Редкий предмет. Награда за достижение."},
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

# ═══════════════════════════════════════════════════════════════════
# ─────────────────── НОВЫЙ ФУНКЦИОНАЛ v3 ──────────────────────────
# ═══════════════════════════════════════════════════════════════════

# ─────────────────── ФУРРИ-РАНГИ ──────────────────────────────────

# Список рангов: (мин. уровень, название, эмодзи)
FURRY_RANKS = [
    (1,  "Детёныш",          "🐾"),
    (4,  "Следопыт",         "🐾✨"),
    (8,  "Лапка",            "🐾⭐"),
    (12, "Хвостатый",        "🦊"),
    (16, "Клыкастый",        "🐺"),
    (20, "Хранитель стаи",   "🌙"),
    (25, "Легенда пустыни",  "🌵🦎"),
    (30, "Дух предков",      "🌟🦊"),
]

def get_rank(level: int) -> tuple[str, str]:
    """Получить (название, эмодзи) ранга для данного уровня."""
    current = FURRY_RANKS[0]
    for min_lvl, name, emoji in FURRY_RANKS:
        if level >= min_lvl:
            current = (name, emoji)
        else:
            break
    return current

def get_next_rank(level: int) -> Optional[tuple[int, str, str]]:
    """Получить (нужный уровень, название, эмодзи) следующего ранга или None."""
    for min_lvl, name, emoji in FURRY_RANKS:
        if min_lvl > level:
            return (min_lvl, name, emoji)
    return None

# ─────────────────── ДОСТИЖЕНИЯ ───────────────────────────────────

ACHIEVEMENTS = {
    1:  {"name": "Душа компании",      "desc": "Совершить 100 РП-действий",           "reward": "500 монет",       "icon": "🎭"},
    2:  {"name": "Семьянин",           "desc": "Прожить в браке 30 дней",             "reward": "1000 монет",      "icon": "💑"},
    3:  {"name": "Счастливчик",        "desc": "Выиграть 10 дуэлей подряд",           "reward": "2000 монет",      "icon": "🍀"},
    4:  {"name": "Эрудит",             "desc": "Ответить верно на 50 вопросов",       "reward": "150 XP",          "icon": "🎓"},
    5:  {"name": "Властелин драконов", "desc": "Купить Яйцо дракона и вылупить",      "reward": "редкий предмет",  "icon": "🐉"},
    6:  {"name": "Богатей",            "desc": "Накопить 10 000 монет",               "reward": "статус в /top",   "icon": "💰"},
    7:  {"name": "Щедрая душа",        "desc": "Подарить другим 5000 монет",          "reward": "500 монет",       "icon": "🎁"},
    8:  {"name": "Азартный игрок",     "desc": "Сыграть 100 раз в игры",             "reward": "300 монет",       "icon": "🎰"},
    9:  {"name": "Любимчик фортуны",   "desc": "Выиграть в /slots 3 раза подряд",    "reward": "500 монет",       "icon": "🌟"},
    10: {"name": "Силач",              "desc": "Выиграть 25 дуэлей",                 "reward": "400 монет",       "icon": "⚔️"},
    11: {"name": "Мастер РП",          "desc": "Создать 5 кастомных РП-команд",       "reward": "200 монет",       "icon": "✍️"},
    12: {"name": "Истинный фурри",     "desc": "Достичь 20-го уровня",               "reward": "1000 монет + Лисий хвост", "icon": "🦊"},
}

def has_achievement(user_id: int, ach_id: int) -> bool:
    """Проверить, получено ли достижение."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT 1 FROM achievements WHERE user_id=? AND achievement_id=?", (user_id, ach_id))
    row = c.fetchone()
    conn.close()
    return bool(row)

def grant_achievement(user_id: int, ach_id: int) -> bool:
    """
    Выдать достижение, если не выдано.
    Возвращает True, если выдано впервые (для уведомления).
    """
    if has_achievement(user_id, ach_id):
        return False
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute(
            "INSERT OR IGNORE INTO achievements (user_id, achievement_id, earned_at) VALUES (?, ?, ?)",
            (user_id, ach_id, int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()

    # Выдать награду
    ach = ACHIEVEMENTS[ach_id]
    if ach_id == 1:
        add_balance(user_id, 500)
    elif ach_id == 2:
        add_balance(user_id, 1000)
    elif ach_id == 3:
        add_balance(user_id, 2000)
    elif ach_id == 4:
        add_xp(user_id, 150)
    elif ach_id == 5:
        _add_to_inventory(user_id, random.choice([3, 6, 7, 9]))
    elif ach_id == 6:
        pass  # статус, без монет
    elif ach_id == 7:
        add_balance(user_id, 500)
    elif ach_id == 8:
        add_balance(user_id, 300)
    elif ach_id == 9:
        add_balance(user_id, 500)
    elif ach_id == 10:
        add_balance(user_id, 400)
    elif ach_id == 11:
        add_balance(user_id, 200)
    elif ach_id == 12:
        add_balance(user_id, 1000)
        _add_to_inventory(user_id, 13)  # Лисий хвост
    return True

async def check_achievements(user_id: int, message: Message):
    """
    Проверить все условия достижений для пользователя и выдать при выполнении.
    Отправляет сообщение в чат при получении нового достижения.
    """
    u = get_user(user_id)
    if not u:
        return

    stats = get_user_stats(user_id)
    newly_earned = []

    # ID 1: Душа компании — 100 РП-действий
    if not has_achievement(user_id, 1) and stats["total_rp_actions"] >= 100:
        if grant_achievement(user_id, 1):
            newly_earned.append(1)

    # ID 2: Семьянин — 30 дней в браке
    if not has_achievement(user_id, 2):
        m = get_marriage(user_id)
        if m:
            days_married = (int(time.time()) - m["married_since"]) // 86400
            if days_married >= 30:
                if grant_achievement(user_id, 2):
                    newly_earned.append(2)

    # ID 4: Эрудит — 50 правильных ответов в квизе
    if not has_achievement(user_id, 4) and stats["total_quiz_correct"] >= 50:
        if grant_achievement(user_id, 4):
            newly_earned.append(4)

    # ID 6: Богатей — баланс >= 10 000
    if not has_achievement(user_id, 6) and u["balance"] >= 10000:
        if grant_achievement(user_id, 6):
            newly_earned.append(6)

    # ID 7: Щедрая душа — отдано >= 5000 монет
    if not has_achievement(user_id, 7) and stats["total_money_given"] >= 5000:
        if grant_achievement(user_id, 7):
            newly_earned.append(7)

    # ID 8: Азартный игрок — 100 игр
    if not has_achievement(user_id, 8) and stats["total_games_played"] >= 100:
        if grant_achievement(user_id, 8):
            newly_earned.append(8)

    # ID 10: Силач — 25 побед в дуэлях
    if not has_achievement(user_id, 10) and stats["total_duels_won"] >= 25:
        if grant_achievement(user_id, 10):
            newly_earned.append(10)

    # ID 11: Мастер РП — 5 кастомных команд
    if not has_achievement(user_id, 11):
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM custom_rp WHERE user_id=?", (user_id,))
        cnt = c.fetchone()[0]; conn.close()
        if cnt >= 5:
            if grant_achievement(user_id, 11):
                newly_earned.append(11)

    # ID 12: Истинный фурри — уровень >= 20
    if not has_achievement(user_id, 12) and u["level"] >= 20:
        if grant_achievement(user_id, 12):
            newly_earned.append(12)

    # Отправляем уведомления о новых достижениях
    for ach_id in newly_earned:
        ach = ACHIEVEMENTS[ach_id]
        await message.reply(
            f"🏅 <b>Новое достижение!</b>\n"
            f"{ach['icon']} <b>{ach['name']}</b>\n"
            f"<i>{ach['desc']}</i>\n"
            f"🎁 Награда: {ach['reward']}",
            parse_mode="HTML",
        )

def check_achievement_dragon(user_id: int) -> bool:
    """Проверить достижение #5 (Властелин драконов) при вылуплении яйца."""
    if not has_achievement(user_id, 5):
        return grant_achievement(user_id, 5)
    return False

# ─────────────────── СТАТИСТИКА ───────────────────────────────────

def ensure_stats(user_id: int):
    """Создать запись статистики если не существует, обновить last_seen."""
    conn = get_conn()
    c = conn.cursor()
    now = int(time.time())
    # Если записи нет — создаём с first_seen = now
    c.execute("INSERT OR IGNORE INTO user_stats (user_id, first_seen, last_seen) VALUES (?, ?, ?)", (user_id, now, now))
    # Обновляем last_seen при каждом вызове
    c.execute("UPDATE user_stats SET last_seen = ? WHERE user_id = ?", (now, user_id))
    conn.commit()
    conn.close()

def get_user_stats(user_id: int) -> dict:
    ensure_stats(user_id)
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT total_rp_actions, total_games_played, total_duels_won, "
        "total_money_given, total_quiz_correct FROM user_stats WHERE user_id=?",
        (user_id,),
    )
    row = c.fetchone()
    conn.close()
    if row:
        return dict(zip([
            "total_rp_actions", "total_games_played", "total_duels_won",
            "total_money_given", "total_quiz_correct"
        ], row))
    return {k: 0 for k in ["total_rp_actions","total_games_played","total_duels_won","total_money_given","total_quiz_correct"]}

def stat_increment(user_id: int, field: str, amount: int = 1):
    """Увеличить поле статистики на amount."""
    ensure_stats(user_id)
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"UPDATE user_stats SET {field} = {field} + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

# ─────────────────── ELO РЕЙТИНГ ───────────────────────────────────

def get_elo(user_id: int) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT rating FROM elo_ratings WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 1000

def update_elo(winner_id: int, loser_id: int, k_factor: int = 32):
    winner_elo = get_elo(winner_id)
    loser_elo = get_elo(loser_id)
    
    expected_winner = 1 / (1 + 10 ** ((loser_elo - winner_elo) / 400))
    expected_loser = 1 / (1 + 10 ** ((winner_elo - loser_elo) / 400))
    
    new_winner_elo = winner_elo + k_factor * (1 - expected_winner)
    new_loser_elo = loser_elo + k_factor * (0 - expected_loser)
    
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO elo_ratings (user_id, rating, games_played, games_won)
        VALUES (?, ?, 1, 1) ON CONFLICT(user_id) DO UPDATE SET
        rating = ?, games_played = games_played + 1, games_won = games_won + 1
    """, (winner_id, round(new_winner_elo), round(new_winner_elo)))
    c.execute("""
        INSERT INTO elo_ratings (user_id, rating, games_played, games_won)
        VALUES (?, ?, 1, 0) ON CONFLICT(user_id) DO UPDATE SET
        rating = ?, games_played = games_played + 1
    """, (loser_id, round(new_loser_elo), round(new_loser_elo)))
    conn.commit()
    conn.close()

def get_elo_rank(user_id: int) -> str:
    elo = get_elo(user_id)
    if elo >= 1400: return "👑 Гроссмейстер"
    if elo >= 1300: return "🏆 Мастер"
    if elo >= 1200: return "⭐ Эксперт"
    if elo >= 1100: return "🟢 Продвинутый"
    if elo >= 1000: return "🔵 Средний"
    if elo >= 900: return "🟡 Начинающий"
    return "🔴 Новичок"
    
# ─────────────────── БОНУС ДНЯ ────────────────────────────────────

# Бонусы: (ключ, название, вес)
DAILY_BONUSES = [
    ("lucky_slots",    "🍀 День удачи: +20% к выигрышу в /slots",      15),
    ("rp_xp",         "🤗 День объятий: +10 XP за РП-действие",        15),
    ("daily_coins",   "💰 День богатства: +200 монет к /daily",        15),
    ("quiz_xp",       "📖 День знаний: +30 XP за /quiz",              10),
    ("love_rp",       "💝 День любви: усиленные РП-ответы",            10),
    ("free_slots",    "🎲 День азарта: одна бесплатная ставка в /slots",10),
    ("give_xp",       "🎁 День подарков: +20 XP отправителю при /give",10),
    ("double_xp",     "⚡ Двойной опыт: весь XP x2",                  10),
    ("protect_xp",    "🛡️ День защиты: 'защитить' даёт +15 XP",        5),
]

def get_today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def get_active_bonus(user_id: int) -> Optional[str]:
    """Получить активный бонус пользователя на сегодня."""
    today = get_today_str()
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT bonus_type FROM daily_bonus_log WHERE user_id=? AND bonus_date=?",
        (user_id, today),
    )
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def activate_bonus(user_id: int) -> Optional[str]:
    """Активировать случайный бонус дня. Возвращает тип или None если уже активен."""
    today = get_today_str()
    # Проверяем, не активирован ли уже
    if get_active_bonus(user_id):
        return None
    # Взвешенный случайный выбор
    types = [b[0] for b in DAILY_BONUSES]
    weights = [b[2] for b in DAILY_BONUSES]
    bonus_type = random.choices(types, weights=weights, k=1)[0]
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO daily_bonus_log (user_id, bonus_date, bonus_type) VALUES (?, ?, ?)",
        (user_id, today, bonus_type),
    )
    conn.commit()
    conn.close()
    return bonus_type

def get_bonus_display(bonus_type: str) -> str:
    """Получить красивое название бонуса по ключу."""
    for key, name, _ in DAILY_BONUSES:
        if key == bonus_type:
            return name
    return bonus_type

def apply_xp_bonus(user_id: int, base_xp: int) -> int:
    """Применить бонус двойного XP если активен."""
    bonus = get_active_bonus(user_id)
    if bonus == "double_xp":
        return base_xp * 2
    return base_xp

# ─────────────────── КАСТОМНЫЕ РП-КОМАНДЫ ─────────────────────────

def get_custom_rp_pattern(user_id: int):
    """Получить все кастомные ключевые слова пользователя."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT keyword, response FROM custom_rp WHERE user_id=?", (user_id,))
    rows = c.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}

def check_custom_rp(user_id: int, text: str) -> Optional[tuple[str, str]]:
    """
    Проверить, начинается ли сообщение с кастомного ключевого слова пользователя.
    Возвращает (keyword, response) или None.
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT keyword, response, id FROM custom_rp WHERE user_id=?", (user_id,))
    rows = c.fetchall()
    conn.close()
    lower_text = text.strip().lower()
    for keyword, response, rp_id in rows:
        if lower_text.startswith(keyword.lower()):
            # Увеличиваем счётчик использования
            conn2 = get_conn()
            c2 = conn2.cursor()
            c2.execute("UPDATE custom_rp SET uses_count=uses_count+1 WHERE id=?", (rp_id,))
            conn2.commit()
            conn2.close()
            return (keyword, response)
    return None

# ─────────────────── STREAK (СЕРИИ ПОБЕД) ─────────────────────────
# Хранится в памяти (сбрасывается при перезапуске — для простоты)
_duel_win_streak: dict[int, int] = {}
_slots_win_streak: dict[int, int] = {}

def record_duel_result(user_id: int, won: bool) -> int:
    """Обновить серию побед в дуэлях. Возвращает текущую серию."""
    if won:
        _duel_win_streak[user_id] = _duel_win_streak.get(user_id, 0) + 1
    else:
        _duel_win_streak[user_id] = 0
    return _duel_win_streak.get(user_id, 0)

def record_slots_result(user_id: int, won: bool) -> int:
    """Обновить серию побед в слотах. Возвращает текущую серию."""
    if won:
        _slots_win_streak[user_id] = _slots_win_streak.get(user_id, 0) + 1
    else:
        _slots_win_streak[user_id] = 0
    return _slots_win_streak.get(user_id, 0)

# ═══════════════════════════════════════════════════════════════════
# ─────────────────── КОМАНДЫ (СУЩЕСТВУЮЩИЕ) ───────────────────────
# ═══════════════════════════════════════════════════════════════════

# ─────────────────────────── /START ───────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    text = (
        "👋 Привет\\! Я — многофункциональный РП\\-бот\\!\n\n"
        "🎭 *РП\\-действия* — ответь на сообщение командой: _обнять_, _поцеловать_, _погладить_\\.\\.\\.\n"
        "🏆 *Уровни и XP* — /level, /leaderboard, /rank\n"
        "🎲 *Игры* — /dice, /d20, /coin, /rps, /slots, /duel, /quiz\n"
        "💰 *Экономика* — /balance, /daily, /give, /shop, /buy, /inventory\n"
        "💍 *Браки* — «Предложить брак @user», /marry, /divorce\n"
        "🏅 *Достижения* — /achievements\n"
        "📊 *Статистика* — /stats\n"
        "🎁 *Бонус дня* — /daily\\_bonus\n\n"
        "📋 Полный список: /help"
    )
    await message.reply(text, parse_mode="MarkdownV2")
    await check_achievements(message.from_user.id, message)
    
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
        "/rank — фурри-ранг и прогресс\n"
        "/leaderboard — топ-10 (по уровню / деньгам / бракам / рангу / ELO)\n\n"
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
        "/top_marriages — топ долгих браков\n\n"
        "<b>🏅 Достижения</b>\n"
        "/achievements — список достижений\n"
        "/achievement [номер] — подробнее о достижении\n\n"
        "<b>📊 Статистика и профиль</b>\n"
        "/profile [@user] — профиль пользователя\n"
        "/elo — мой ELO рейтинг\n"
        "/top_elo — топ по ELO рейтингу\n"
        "/top_activity — топ по активности\n"
        "/top_rp_actions — топ по РП-действиям\n\n"
        "<b>🎭 Кастомные РП</b>\n"
        "/create_rp [слово] [текст] — создать команду\n"
        "/my_rp — мои команды\n"
        "/delete_rp [слово] — удалить\n"
        "/top_rp — топ кастомных команд\n\n"
        "<b>🎁 Бонус дня</b>\n"
        "/daily_bonus — активировать бонус дня\n"
        "/bonus_info — информация о бонусе\n"
        "<b>🛠️ Админ-команды</b>\n"
        "/admin_panel — админ-панель\n"
        "/chats — статистика бота\n"
    )
    await message.reply(text, parse_mode="HTML")

# ─────────────────────────── /LEVEL ───────────────────────────────

@router.message(Command("level"))
async def cmd_level(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    u = get_user(message.from_user.id)
    level = calc_level(u["xp"])
    xp_needed = xp_for_level(level + 1) - u["xp"]
    rank_name, rank_emoji = get_rank(level)
    await message.reply(
        f"🏆 <b>{message.from_user.full_name}</b>\n"
        f"Уровень: <b>{level}</b>\n"
        f"Ранг: {rank_emoji} <b>{rank_name}</b>\n"
        f"XP: <b>{u['xp']}</b>\n"
        f"До следующего уровня: <b>{xp_needed} XP</b>",
        parse_mode="HTML",
    )

# ─────────────────────────── /LEADERBOARD ─────────────────────────

def make_leaderboard_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏆 По уровню", callback_data="lb_xp"),
            InlineKeyboardButton(text="💰 По деньгам", callback_data="lb_money"),
        ],
        [
            InlineKeyboardButton(text="💍 По бракам", callback_data="lb_marriages"),
            InlineKeyboardButton(text="🦊 По рангу", callback_data="lb_rank"),
            InlineKeyboardButton(text="⚔️ По ELO", callback_data="lb_elo"),
        ]
    ])

@router.message(Command("leaderboard"))
async def cmd_leaderboard(message: Message):
    await _send_leaderboard(message, "lb_xp")

async def _send_leaderboard(target, mode: str):
    conn = get_conn()
    c = conn.cursor()
    if mode == "lb_xp":
        c.execute("SELECT user_id, username, xp, level FROM users ORDER BY xp DESC LIMIT 10")
        rows = c.fetchall()
        lines = ["🏆 <b>Топ по уровню:</b>"]
        for i, (uid, name, xp, lvl) in enumerate(rows, 1):
            crown = "👑 " if _has_item(uid, 12) else ""
            display_name = name or str(uid)
            mention = f"<a href='tg://user?id={uid}'>{display_name}</a>"
            lines.append(f"{i}. {crown}{mention} — Ур.{lvl} ({xp} XP)")
    elif mode == "lb_money":
        c.execute("SELECT user_id, username, balance FROM users ORDER BY balance DESC LIMIT 10")
        rows = c.fetchall()
        lines = ["💰 <b>Топ по монетам:</b>"]
        for i, (uid, name, bal) in enumerate(rows, 1):
            crown = "👑 " if _has_item(uid, 12) else ""
            display_name = name or str(uid)
            mention = f"<a href='tg://user?id={uid}'>{display_name}</a>"
            lines.append(f"{i}. {crown}{mention} — {bal} 🪙")
    elif mode == "lb_rank":
        c.execute("SELECT user_id, username, level FROM users ORDER BY level DESC LIMIT 10")
        rows = c.fetchall()
        lines = ["🦊 <b>Топ по рангу:</b>"]
        for i, (uid, name, lvl) in enumerate(rows, 1):
            rank_name, rank_emoji = get_rank(lvl)
            display_name = name or str(uid)
            mention = f"<a href='tg://user?id={uid}'>{display_name}</a>"
            lines.append(f"{i}. {mention} — {rank_emoji} {rank_name} (Ур.{lvl})")
    elif mode == "lb_elo":
        c.execute("""
            SELECT u.user_id, u.username, e.rating 
            FROM elo_ratings e 
            JOIN users u ON u.user_id = e.user_id 
            ORDER BY e.rating DESC LIMIT 10
        """)
        rows = c.fetchall()
        lines = ["⚔️ <b>Топ по ELO рейтингу:</b>"]
        for i, (uid, name, rating) in enumerate(rows, 1):
            display_name = name or str(uid)
            mention = f"<a href='tg://user?id={uid}'>{display_name}</a>"
            lines.append(f"{i}. {mention} — <b>{rating}</b> ({get_elo_rank(uid)})")
    else:  # lb_marriages
        c.execute(
            "SELECT u1.user_id, u1.username, u2.user_id, u2.username, m.married_since "
            "FROM marriages m "
            "JOIN users u1 ON u1.user_id=m.user1_id "
            "JOIN users u2 ON u2.user_id=m.user2_id "
            "ORDER BY m.married_since ASC LIMIT 10"
        )
        rows = c.fetchall()
        lines = ["💍 <b>Топ самых долгих браков:</b>"]
        for i, (uid1, n1, uid2, n2, ts) in enumerate(rows, 1):
            days = (int(time.time()) - ts) // 86400
            mention1 = f"<a href='tg://user?id={uid1}'>{n1 or str(uid1)}</a>"
            mention2 = f"<a href='tg://user?id={uid2}'>{n2 or str(uid2)}</a>"
            lines.append(f"{i}. {mention1} & {mention2} — {days} дн.")
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

@router.callback_query(F.data.in_({"lb_xp", "lb_money", "lb_marriages", "lb_rank", "lb_elo"}))
async def cb_leaderboard(call: CallbackQuery):
    await call.answer()
    await _send_leaderboard(call, call.data)

# ───────────────────────── МИНИ-ИГРЫ ──────────────────────────────

@router.message(Command("dice"))
async def cmd_dice(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    await message.reply(f"🎲 Выпало: <b>{random.randint(1, 6)}</b>!", parse_mode="HTML")

@router.message(Command("d20"))
async def cmd_d20(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    r = random.randint(1, 20)
    suffix = " 🌟 <b>КРИТ!</b>" if r == 20 else (" 💀 <b>ПРОВАЛ!</b>" if r == 1 else "")
    await message.reply(f"🎲 D20: <b>{r}</b>{suffix}", parse_mode="HTML")

@router.message(Command("coin"))
async def cmd_coin(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    result = random.choice(["🦅 Орёл", "✍️ Решка"])
    await message.reply(f"🪙 <b>{result}</b>!", parse_mode="HTML")

@router.message(Command("rps"))
async def cmd_rps(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or args[1].lower() not in ("камень", "ножницы", "бумага"):
        await message.reply("✋ Использование: /rps [камень|ножницы|бумага]")
        return
    choices = ["камень", "ножницы", "бумага"]
    emojis = {"камень": "🪨", "ножницы": "✂️", "бумага": "📄"}
    wins = {"камень": "ножницы", "ножницы": "бумага", "бумага": "камень"}
    user_choice = args[1].lower()
    bot_choice = random.choice(choices)

    # Статистика: игра сыграна
    stat_increment(message.from_user.id, "total_games_played")

    if user_choice == bot_choice:
        result, extra = "🤝 Ничья!", "+5 XP, +5 🪙"
        xp = apply_xp_bonus(message.from_user.id, 5)
        add_xp(message.from_user.id, xp); add_balance(message.from_user.id, 5)
    elif wins[user_choice] == bot_choice:
        result, extra = "🎉 Вы победили!", "+15 XP, +20 🪙"
        xp = apply_xp_bonus(message.from_user.id, 15)
        add_xp(message.from_user.id, xp); add_balance(message.from_user.id, 20)
    else:
        result, extra = "😔 Бот победил!", ""
    await message.reply(
        f"Вы: {emojis[user_choice]} {user_choice}\nБот: {emojis[bot_choice]} {bot_choice}\n\n<b>{result}</b> {extra}",
        parse_mode="HTML",
    )
    await check_achievements(message.from_user.id, message)

@router.message(Command("slots"))
async def cmd_slots(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    uid = message.from_user.id
    args = message.text.split()

    # Бонус "День азарта": бесплатная ставка
    free_bet = get_active_bonus(uid) == "free_slots"

    if len(args) < 2 or not args[1].isdigit():
        if free_bet:
            # При активном бонусе можно играть без ставки
            bet = 50  # дефолтная ставка при бесплатной игре
        else:
            await message.reply("🎰 Использование: /slots [сумма] (мин. 10)")
            return
    else:
        bet = int(args[1])

    if bet < 10:
        await message.reply("❌ Минимальная ставка — 10 монет.")
        return

    u = get_user(uid)

    if free_bet:
        # Бесплатная ставка — деньги не снимаем, но только раз (отмечаем использование)
        bet_text = f"(бесплатная ставка 🎲 {bet} 🪙)"
        # Снимаем бонус чтобы не использовать повторно
        conn = get_conn(); c = conn.cursor()
        c.execute(
            "UPDATE daily_bonus_log SET bonus_type='free_slots_used' WHERE user_id=? AND bonus_date=?",
            (uid, get_today_str()),
        )
        conn.commit(); conn.close()
    else:
        if u["balance"] < bet:
            await message.reply("❌ Недостаточно монет!")
            return
        bet_text = f"{bet} 🪙"

    # Проверяем бонус клевера (+10% удачи) и день удачи (+20%)
    lucky = _has_item(uid, 8)
    day_lucky = get_active_bonus(uid) == "lucky_slots"

    symbols = ["🍒", "🍋", "🍊", "🍇", "⭐", "🔔"]
    s1, s2, s3 = random.choice(symbols), random.choice(symbols), random.choice(symbols)

    if not free_bet:
        add_balance(uid, -bet)

    # Статистика: игра сыграна
    stat_increment(uid, "total_games_played")

    win = False
    if s1 == s2 == s3:
        win = True
    elif lucky and random.random() < 0.10:
        s3 = s1
        win = s1 == s2 == s3
    elif day_lucky and random.random() < 0.20:
        s3 = s1
        win = s1 == s2 == s3

    slots_streak = record_slots_result(uid, win)

    if win:
        prize = bet * 2
        add_balance(uid, prize)
        xp = apply_xp_bonus(uid, 15)
        add_xp(uid, xp)
        result = f"🎉 ДЖЕКПОТ! Выигрыш: <b>{prize}</b> монет! +{xp} XP"
        # Достижение #9: 3 победы подряд в слотах
        if slots_streak >= 3 and not has_achievement(uid, 9):
            if grant_achievement(uid, 9):
                await message.reply(
                    f"🏅 <b>Новое достижение!</b>\n🌟 <b>Любимчик фортуны</b>\n🎁 Награда: 500 монет",
                    parse_mode="HTML",
                )
    else:
        result = f"😔 Не повезло. Потеряно: <b>{bet}</b> монет."

    await message.reply(f"🎰 | {s1} | {s2} | {s3} |\n{bet_text}\n\n{result}", parse_mode="HTML")
    await check_achievements(uid, message)

@router.message(Command("duel"))
async def cmd_duel(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    args = message.text.split()
    if len(args) < 3 or not args[1].startswith("@") or not args[2].isdigit():
        await message.reply("⚔️ Использование: /duel @username [сумма]")
        return
    amount = int(args[2])
    if amount <= 0:
        await message.reply("❌ Сумма должна быть > 0.")
        return
    challenger = get_user(message.from_user.id)
    if challenger["balance"] < amount:
        await message.reply("❌ Недостаточно монет.")
        return
    target_id = find_user_by_username(args[1])
    if not target_id:
        await message.reply("❌ Пользователь не найден в базе.")
        return
    if target_id == message.from_user.id:
        await message.reply("❌ Нельзя дуэлировать с собой.")
        return
    target_user = get_user(target_id)
    if target_user["balance"] < amount:
        await message.reply(f"❌ У {mention(target_user['username'], target_id)} недостаточно монет.", parse_mode="Markdown")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⚔️ Принять",    callback_data=f"duel_accept_{message.from_user.id}_{target_id}_{amount}"),
        InlineKeyboardButton(text="🏳️ Отказаться", callback_data=f"duel_decline_{message.from_user.id}"),
    ]])
    await message.reply(
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

    # Статистика: игра сыграна для обоих
    stat_increment(challenger_id, "total_games_played")
    stat_increment(target_id, "total_games_played")

    if c_roll == t_roll:
        # Серии не изменяются при ничьей
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
        xp_win = apply_xp_bonus(winner_id, 15)
        add_xp(winner_id, xp_win)
        
                # Обновляем ELO рейтинг
        update_elo(winner_id, loser_id)

        # Статистика победителя
        stat_increment(winner_id, "total_duels_won")

        # Серии дуэлей
        winner_streak = record_duel_result(winner_id, True)
        record_duel_result(loser_id, False)

        await call.message.edit_text(
            f"⚔️ Дуэль завершена\\!\n"
            f"🎲 {mention(c_name, challenger_id)}: {c_roll}\n"
            f"🎲 {mention(t_name, target_id)}: {t_roll}\n\n"
            f"🏆 Победил {mention(winner_name, winner_id)}\\! \\+{amount} монет, \\+{xp_win} XP",
            parse_mode="MarkdownV2", reply_markup=None,
        )
        # Достижение #3: 10 побед подряд в дуэлях
        if winner_streak >= 10 and not has_achievement(winner_id, 3):
            if grant_achievement(winner_id, 3):
                await call.message.answer(
                    "🏅 <b>Новое достижение!</b>\n🍀 <b>Счастливчик</b> — 10 дуэлей подряд!\n🎁 Награда: 2000 монет",
                    parse_mode="HTML",
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
    today_count = get_quiz_today(message.from_user.id)
    if today_count >= QUIZ_DAILY_LIMIT:
        await message.reply("🛑 Ты сегодня уже ответил(а) на 10 вопросов! Возвращайся завтра. 📅")
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
    await message.reply(
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
    stat_increment(owner_id, "total_games_played")
    if chosen == correct:
        # Бонус "День знаний": +30 XP
        day_bonus = get_active_bonus(owner_id)
        base_xp = 15
        if day_bonus == "quiz_xp":
            base_xp += 30
        xp = apply_xp_bonus(owner_id, base_xp)
        add_balance(owner_id, 50)
        add_xp(owner_id, xp)
        stat_increment(owner_id, "total_quiz_correct")
        await call.message.edit_text(f"✅ Правильно! +50 монет, +{xp} XP 🎉", reply_markup=None)
    else:
        await call.message.edit_text("❌ Неверно! Попыток потрачено. Попробуй /quiz снова.", reply_markup=None)
    await call.answer()

# ─────────────────────────── ЭКОНОМИКА ────────────────────────────

@router.message(Command(commands=["balance", "money"]))
async def cmd_balance(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    u = get_user(message.from_user.id)
    await message.reply(
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
        await message.reply(f"⏳ Следующий бонус через: <b>{h}ч {m}м</b>", parse_mode="HTML")
        return

    # Базовые награды
    coins = 100
    # Бонус "День богатства": +200 монет
    if get_active_bonus(message.from_user.id) == "daily_coins":
        coins += 200

    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET balance=balance+?, daily_ts=? WHERE user_id=?", (coins, now, message.from_user.id))
    conn.commit()
    conn.close()
    xp = apply_xp_bonus(message.from_user.id, 10)
    add_xp(message.from_user.id, xp)
    await message.reply(
        f"🎁 Ежедневный бонус: <b>+{coins} монет, +{xp} XP</b>!",
        parse_mode="HTML",
    )
    await check_achievements(message.from_user.id, message)

@router.message(Command("give"))
async def cmd_give(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    args = message.text.split()
    if len(args) < 3 or not args[1].startswith("@") or not args[2].isdigit():
        await message.reply("💸 Использование: /give @username [сумма]")
        return
    amount = int(args[2])
    if amount <= 0:
        await message.reply("❌ Сумма должна быть > 0.")
        return
    sender = get_user(message.from_user.id)
    if sender["balance"] < amount:
        await message.reply("❌ Недостаточно монет!")
        return
    target_id = find_user_by_username(args[1])
    if not target_id:
        await message.reply("❌ Пользователь не найден.")
        return
    if target_id == message.from_user.id:
        await message.reply("❌ Нельзя переводить самому себе.")
        return
    target_user = get_user(target_id)
    add_balance(message.from_user.id, -amount)
    add_balance(target_id, amount)

    # Статистика: отданные монеты
    stat_increment(message.from_user.id, "total_money_given", amount)

    # Бонус "День подарков": +20 XP отправителю
    day_bonus = get_active_bonus(message.from_user.id)
    extra_xp_msg = ""
    if day_bonus == "give_xp":
        add_xp(message.from_user.id, 20)
        extra_xp_msg = " (+20 XP вам 🎁)"

    # Создаём кликабельное упоминание получателя
    target_name = target_user['username'] or str(target_id)
    target_mention = f"<a href='tg://user?id={target_id}'>{target_name}</a>"

    await message.reply(
        f"✅ Вы перевели <b>{amount} 🪙</b> пользователю {target_mention}!{extra_xp_msg}",
        parse_mode="HTML",
    )
    await check_achievements(message.from_user.id, message)

@router.message(Command("shop"))
async def cmd_shop(message: Message):
    lines = ["🛒 <b>Магазин</b>\n"]
    for num, item in SHOP_ITEMS.items():
        if num == 13:
            continue  # Лисий хвост не в продаже
        lines.append(f"{num}. {item['name']} — <b>{item['price']} 🪙</b>\n   <i>{item['desc']}</i>")
    lines.append("\nКупить: /buy [номер]")
    await message.reply("\n".join(lines), parse_mode="HTML")

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
        await message.reply("🛒 Использование: /buy [номер]")
        return
    item_id = int(args[1])
    if item_id not in SHOP_ITEMS or item_id == 13:
        await message.reply("❌ Нет такого предмета. Смотри /shop.")
        return
    item = SHOP_ITEMS[item_id]
    u = get_user(message.from_user.id)
    if u["balance"] < item["price"]:
        await message.reply(f"❌ Нужно {item['price']} 🪙, у вас {u['balance']} 🪙.")
        return
    add_balance(message.from_user.id, -item["price"])
    _add_to_inventory(message.from_user.id, item_id)

    bonus = ""
    if item_id == 4:
        add_xp(message.from_user.id, 10); bonus = " +10 XP!"
    elif item_id == 12:
        add_xp(message.from_user.id, 50); bonus = " +50 XP! Статус «👑 Властелин» активен."
    elif item_id == 11:
        conn = get_conn(); c = conn.cursor()
        c.execute(
            "INSERT INTO item_effects (user_id, dragon_egg, dragon_ts) VALUES (?, 1, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET dragon_egg=1, dragon_ts=?",
            (message.from_user.id, int(time.time()), int(time.time())),
        )
        conn.commit(); conn.close()
        bonus = " Яйцо вылупится через 7 дней!"
    elif item_id == 10:
        conn = get_conn(); c = conn.cursor()
        c.execute(
            "INSERT INTO item_effects (user_id, magic_hat) VALUES (?, 1) "
            "ON CONFLICT(user_id) DO UPDATE SET magic_hat=1",
            (message.from_user.id,),
        )
        conn.commit(); conn.close()
        bonus = " Теперь используй /hat каждые 24ч!"

    await message.reply(f"✅ Куплено: {item['name']}!{bonus}", parse_mode="HTML")
    await check_achievements(message.from_user.id, message)

@router.message(Command("inventory"))
async def cmd_inventory(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT item_id, amount FROM inventory WHERE user_id=? AND amount>0", (message.from_user.id,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        await message.reply("🎒 Инвентарь пуст.")
        return
    lines = ["🎒 <b>Инвентарь</b>:\n"]
    for item_id, amount in rows:
        item = SHOP_ITEMS.get(item_id)
        if item:
            lines.append(f"{item_id}. {item['name']} × {amount}")
    lines.append("\nИспользовать: /use [номер]")
    await message.reply("\n".join(lines), parse_mode="HTML")

# БАГ-ФИКС: /use теперь корректно уменьшает количество и удаляет строку при 0
@router.message(Command(commands=["use", "use_item"]))
async def cmd_use(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.reply("🎒 Использование: /use [номер]")
        return
    item_id = int(args[1])

    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT amount FROM inventory WHERE user_id=? AND item_id=?", (message.from_user.id, item_id))
    row = c.fetchone()
    conn.close()

    if not row or row[0] <= 0:
        await message.reply("❌ У вас нет такого предмета.")
        return

    response = await _apply_item_effect(message, item_id)
    if response is None:
        return

    _remove_from_inventory(message.from_user.id, item_id)
    await message.reply(response, parse_mode="HTML")

async def _apply_item_effect(message: Message, item_id: int) -> Optional[str]:
    """Применить эффект предмета. Возвращает текст ответа или None при ошибке."""
    uid = message.from_user.id
    if item_id == 1:
        return "🍎 Вы съели яблоко. Хруск! Настроение +100%"
    elif item_id == 2:
        if not message.reply_to_message:
            await message.reply("🌹 Ответьте на сообщение того, кому хотите подарить розу.")
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
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT dragon_ts FROM item_effects WHERE user_id=?", (uid,))
        row = c.fetchone()
        conn.close()
        if row and (int(time.time()) - row[0]) >= 7 * 86400:
            prizes = [3, 6, 7, 9]
            prize_id = random.choice(prizes)
            _add_to_inventory(uid, prize_id)
            prize_name = SHOP_ITEMS[prize_id]["name"]
            # Проверяем достижение #5 (Властелин драконов)
            if check_achievement_dragon(uid):
                asyncio.create_task(message.answer(
                    "🏅 <b>Новое достижение!</b>\n🐉 <b>Властелин драконов</b>!\n🎁 Награда: редкий предмет",
                    parse_mode="HTML",
                ))
            return f"🐉 Яйцо вылупилось! Дракончик принёс тебе: <b>{prize_name}</b>! 🎉"
        elif row:
            days_left = 7 - (int(time.time()) - row[0]) // 86400
            return f"🥚 Яйцо ещё не вылупилось. Осталось ~{days_left} дн."
        else:
            return "🥚 Нет активного яйца дракона."
    elif item_id == 12:
        return "👑 Корона уже надета! Ваш статус «Властелин» виден в /leaderboard."
    elif item_id == 13:
        return "🦊 Лисий хвост красиво развевается на ветру. Это редкий предмет!"
    return "❓ Неизвестный предмет."

# Команда /hat — получить рандомный предмет от Магической шляпы
@router.message(Command("hat"))
async def cmd_hat(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    if not _has_item(message.from_user.id, 10):
        await message.reply("🎩 У вас нет Магической шляпы. Купите в /shop!")
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
        await message.reply(f"🎩 Шляпа уже использована. Следующий предмет через {h}ч {m}м.")
        return
    gift_id = random.choice(list(SHOP_ITEMS.keys())[:-3])
    _add_to_inventory(message.from_user.id, gift_id)
    c.execute(
        "INSERT INTO item_effects (user_id, hat_last_ts) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET hat_last_ts=?",
        (message.from_user.id, now, now),
    )
    conn.commit()
    conn.close()
    await message.reply(
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
        await message.reply("❌ Вы уже состоите в браке!")
        return
    target_id = find_user_by_username(target_username)
    if not target_id:
        await message.reply("❌ Пользователь не найден.")
        return
    if target_id == message.from_user.id:
        await message.reply("❌ Нельзя жениться на себе.")
        return
    if get_marriage(target_id):
        await message.reply(f"❌ @{target_username} уже состоит в браке.")
        return
    t_user = get_user(target_id)
    t_name = t_user["username"] or str(target_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❤️ Согласиться", callback_data=f"marry_yes_{message.from_user.id}_{target_id}"),
        InlineKeyboardButton(text="💔 Отказаться",  callback_data=f"marry_no_{message.from_user.id}"),
    ]])
    await message.reply(
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

    # Проверка достижения "Семьянин"
    await check_achievements(proposer_id, call.message)
    await check_achievements(target_id, call.message)

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
        await message.reply("💔 Вы не состоите в браке.")
        return
    partner_id = m["user2_id"] if m["user1_id"] == message.from_user.id else m["user1_id"]
    partner_name = get_username_by_id(partner_id)
    days = (int(time.time()) - m["married_since"]) // 86400
    await message.reply(
    f'💍 Вы женаты с <a href="tg://user?id={partner_id}">{partner_name}</a>\n'
    f'Дней вместе: <b>{days}</b>',
    parse_mode="HTML",
)

@router.message(Command("divorce"))
async def cmd_divorce(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    if not get_marriage(message.from_user.id):
        await message.reply("💔 Вы не состоите в браке.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да, развестись", callback_data=f"divorce_confirm_{message.from_user.id}"),
        InlineKeyboardButton(text="❌ Отмена",          callback_data="divorce_cancel"),
    ]])
    await message.reply("⚠️ Уверены, что хотите развестись?", reply_markup=kb)

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
        await message.reply("💍 Браков ещё нет!")
        return
    lines = ["💍 <b>Топ долгих браков:</b>\n"]
    for i, (n1, id1, n2, id2, ts) in enumerate(rows, 1):
        days = (int(time.time()) - ts) // 86400
        lines.append(f"{i}. {n1 or '???'} & {n2 or '???'} — {days} дн.")
    await message.reply("\n".join(lines), parse_mode="HTML")

# ─────────────────────────── АДМИН-КОМАНДЫ ────────────────────────

def admin_only(func):
    """Декоратор: только для администраторов."""
    async def wrapper(message: Message):
        if not is_admin(message.from_user.id):
            await message.reply("🚫 Нет доступа.")
            return
        await func(message)
    wrapper.__name__ = func.__name__
    return wrapper

@router.message(Command("add_money"))
@admin_only
async def cmd_add_money(message: Message):
    args = message.text.split()
    if len(args) < 3 or not args[2].lstrip("-").isdigit():
        await message.reply("Использование: /add_money @username [сумма]")
        return
    target_id = find_user_by_username(args[1])
    if not target_id:
        await message.reply("❌ Пользователь не найден.")
        return
    amount = int(args[2])
    add_balance(target_id, amount)
    log_admin_action(message.from_user.id, "add_money", target_id, str(amount))
    await message.reply(f"✅ Баланс {args[1]} изменён на {amount:+} 🪙")

@router.message(Command("remove_money"))
@admin_only
async def cmd_remove_money(message: Message):
    args = message.text.split()
    if len(args) < 3 or not args[2].isdigit():
        await message.reply("Использование: /remove_money @username [сумма]")
        return
    target_id = find_user_by_username(args[1])
    if not target_id:
        await message.reply("❌ Пользователь не найден.")
        return
    amount = int(args[2])
    add_balance(target_id, -amount)
    log_admin_action(message.from_user.id, "remove_money", target_id, f"-{amount}")
    await message.reply(f"✅ Снято {amount} 🪙 с {args[1]}")

@router.message(Command("add_xp"))
@admin_only
async def cmd_add_xp(message: Message):
    args = message.text.split()
    if len(args) < 3 or not args[2].isdigit():
        await message.reply("Использование: /add_xp @username [количество]")
        return
    target_id = find_user_by_username(args[1])
    if not target_id:
        await message.reply("❌ Пользователь не найден.")
        return
    amount = int(args[2])
    add_xp(target_id, amount)
    log_admin_action(message.from_user.id, "add_xp", target_id, str(amount))
    await message.reply(f"✅ +{amount} XP начислено {args[1]}")

@router.message(Command("reset_inventory"))
@admin_only
async def cmd_reset_inventory(message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.reply("Использование: /reset_inventory @username")
        return
    target_id = find_user_by_username(args[1])
    if not target_id:
        await message.reply("❌ Пользователь не найден.")
        return
    conn = get_conn(); c = conn.cursor()
    c.execute("DELETE FROM inventory WHERE user_id=?", (target_id,))
    conn.commit(); conn.close()
    log_admin_action(message.from_user.id, "reset_inventory", target_id)
    await message.reply(f"✅ Инвентарь {args[1]} очищен.")

@router.message(Command("reset_daily"))
@admin_only
async def cmd_reset_daily(message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.reply("Использование: /reset_daily @username")
        return
    target_id = find_user_by_username(args[1])
    if not target_id:
        await message.reply("❌ Пользователь не найден.")
        return
    conn = get_conn(); c = conn.cursor()
    c.execute("UPDATE users SET daily_ts=0 WHERE user_id=?", (target_id,))
    conn.commit(); conn.close()
    log_admin_action(message.from_user.id, "reset_daily", target_id)
    await message.reply(f"✅ Ежедневный бонус {args[1]} сброшен.")

@router.message(Command("broadcast"))
@admin_only
async def cmd_broadcast(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("Использование: /broadcast [текст сообщения]")
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
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1
    log_admin_action(message.from_user.id, "broadcast", 0, f"sent={sent}, failed={failed}")
    await message.reply(f"📢 Рассылка завершена. Отправлено: {sent}, ошибок: {failed}.")

# ─────────────────────────── АДМИН-ПАНЕЛЬ ─────────────────────────

def admin_panel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Статистика бота", callback_data="admin_stats"),
            InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin_users"),
        ],
        [
            InlineKeyboardButton(text="💰 Выдать монеты", callback_data="admin_give_money"),
            InlineKeyboardButton(text="🏅 Выдать достижение", callback_data="admin_give_ach"),
        ],
        [
            InlineKeyboardButton(text="📦 Выдать предмет", callback_data="admin_give_item"),
            InlineKeyboardButton(text="💾 Создать бэкап", callback_data="admin_backup"),
        ],
        [
            InlineKeyboardButton(text="📨 Рассылка", callback_data="admin_broadcast"),
        ],
    ])

@router.message(Command("admin_panel"))
@admin_only
async def cmd_admin_panel(message: Message):
    await message.reply("🛠️ <b>АДМИН-ПАНЕЛЬ</b>\n\nВыбери действие:", parse_mode="HTML", reply_markup=admin_panel_kb())


@router.callback_query(F.data.startswith("admin_"))
async def admin_callback(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("🚫 Нет доступа!", show_alert=True)
        return
    
    action = call.data.split("_")[1]
    
    if action == "stats":
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM marriages")
        marriages = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM custom_rp")
        custom_rp = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM achievements")
        achievements = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM elo_ratings WHERE games_played > 0")
        duelists = c.fetchone()[0]
        conn.close()
        
        await call.message.edit_text(
            f"📊 <b>СТАТИСТИКА БОТА</b>\n\n"
            f"👥 Пользователей: <b>{users}</b>\n"
            f"💍 Браков: <b>{marriages}</b>\n"
            f"🎭 Кастомных РП: <b>{custom_rp}</b>\n"
            f"🏅 Достижений выдано: <b>{achievements}</b>\n"
            f"⚔️ Участников дуэлей: <b>{duelists}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]])
        )
    
    elif action == "users":
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT user_id, username, xp, level, balance FROM users ORDER BY xp DESC LIMIT 20")
        rows = c.fetchall()
        conn.close()
        
        text = "👥 <b>ТОП-20 ПОЛЬЗОВАТЕЛЕЙ (по XP)</b>\n\n"
        for i, (uid, name, xp, lvl, bal) in enumerate(rows, 1):
            display = name or str(uid)
            text += f"{i}. {display} — ур.{lvl} ({xp} XP) | {bal}🪙\n"
        
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]]))
    
    elif action == "back":
        await call.message.edit_text("🛠️ <b>АДМИН-ПАНЕЛЬ</b>\n\nВыбери действие:", parse_mode="HTML", reply_markup=admin_panel_kb())
    
    elif action == "backup":
        await call.message.edit_text("💾 Создаю бэкап...")
        if backup_database():
            await call.message.edit_text("✅ Бэкап успешно создан!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]]))
        else:
            await call.message.edit_text("❌ Ошибка при создании бэкапа!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]]))
    
    elif action == "give":
        # Запрос username
        await call.message.edit_text("💰 Введите @username пользователя:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]]))
        # Сохраняем состояние в памяти (упрощённо — в следующем сообщении)
    
    elif action == "give_money":
        await call.message.edit_text("💰 Введите @username и сумму через пробел\nПример: @user 100", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")]]))
    
    elif action == "broadcast":
        await call.message.edit_text("📨 Введите сообщение для рассылки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")]]))
    
    await call.answer()


@router.callback_query(F.data == "admin_cancel")
async def admin_cancel(call: CallbackQuery):
    await call.message.edit_text("🛠️ <b>АДМИН-ПАНЕЛЬ</b>\n\nВыбери действие:", parse_mode="HTML", reply_markup=admin_panel_kb())
    await call.answer()

@router.message(Command("backup"))
@admin_only
async def cmd_backup(message: Message):
    """Создать бэкап базы данных (только для админа)"""
    await message.reply("💾 Создаю бэкап базы данных...")
    if backup_database():
        await message.reply("✅ Бэкап успешно создан!")
    else:
        await message.reply("❌ Ошибка при создании бэкапа. Проверь логи.")

# ═══════════════════════════════════════════════════════════════════
# ─────────────────── НОВЫЕ КОМАНДЫ v3 ─────────────────────────────
# ═══════════════════════════════════════════════════════════════════

# ─────────────────────────── /RANK ────────────────────────────────

@router.message(Command("rank"))
async def cmd_rank(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    u = get_user(message.from_user.id)
    level = calc_level(u["xp"])
    rank_name, rank_emoji = get_rank(level)
    next_rank = get_next_rank(level)

    lines = [
        f"🦊 <b>Фурри-ранг: {rank_emoji} {rank_name}</b>",
        f"📊 Уровень: <b>{level}</b>",
    ]
    if next_rank:
        next_lvl, next_name, next_emoji = next_rank
        levels_needed = next_lvl - level
        lines.append(f"⬆️ Следующий ранг: {next_emoji} <b>{next_name}</b>")
        lines.append(f"🔺 До него: <b>{levels_needed}</b> уровней")
    else:
        lines.append("🌟 Вы достигли высшего ранга!")
    await message.reply("\n".join(lines), parse_mode="HTML")

# ──────────────────────── /ACHIEVEMENTS ───────────────────────────

@router.message(Command("achievements"))
async def cmd_achievements(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    uid = message.from_user.id
    stats = get_user_stats(uid)
    u = get_user(uid)
    level = calc_level(u["xp"])

    lines = ["🏅 <b>Достижения</b>\n"]
    for ach_id, ach in ACHIEVEMENTS.items():
        earned = has_achievement(uid, ach_id)
        status = "✅" if earned else "🔒"

        # Прогресс для некоторых достижений
        progress = ""
        if not earned:
            if ach_id == 1:
                progress = f" ({stats['total_rp_actions']}/100)"
            elif ach_id == 4:
                progress = f" ({stats['total_quiz_correct']}/50)"
            elif ach_id == 7:
                progress = f" ({stats['total_money_given']}/5000)"
            elif ach_id == 8:
                progress = f" ({stats['total_games_played']}/100)"
            elif ach_id == 10:
                progress = f" ({stats['total_duels_won']}/25)"
            elif ach_id == 12:
                progress = f" ({level}/20)"

        lines.append(f"{status} {ach['icon']} <b>{ach['name']}</b>{progress}\n   <i>{ach['desc']}</i>")

    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM achievements WHERE user_id=?", (uid,))
    total_earned = c.fetchone()[0]; conn.close()
    lines.append(f"\n📊 Получено: <b>{total_earned}/{len(ACHIEVEMENTS)}</b>")
    lines.append("ℹ️ Подробнее: /achievement [номер]")
    await message.reply("\n".join(lines), parse_mode="HTML")

@router.message(Command("achievement"))
async def cmd_achievement_detail(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("ℹ️ Использование: /achievement [номер от 1 до 12]")
        return
    # Поиск по номеру или названию
    query = args[1].strip()
    ach_id = None
    if query.isdigit():
        ach_id = int(query)
    else:
        for aid, ach in ACHIEVEMENTS.items():
            if ach["name"].lower() == query.lower():
                ach_id = aid
                break
    if not ach_id or ach_id not in ACHIEVEMENTS:
        await message.reply("❌ Достижение не найдено. Введите номер от 1 до 12.")
        return
    ach = ACHIEVEMENTS[ach_id]
    earned = has_achievement(message.from_user.id, ach_id)
    conn = get_conn(); c = conn.cursor()
    c.execute(
        "SELECT earned_at FROM achievements WHERE user_id=? AND achievement_id=?",
        (message.from_user.id, ach_id),
    )
    row = c.fetchone(); conn.close()
    status = "✅ Получено" if earned else "🔒 Не получено"
    date_str = ""
    if row:
        dt = datetime.fromtimestamp(row[0], tz=timezone.utc).strftime("%d.%m.%Y")
        date_str = f"\n📅 Дата получения: {dt}"
    await message.reply(
        f"{ach['icon']} <b>{ach['name']}</b>\n"
        f"Статус: {status}{date_str}\n\n"
        f"📋 Условие: {ach['desc']}\n"
        f"🎁 Награда: {ach['reward']}",
        parse_mode="HTML",
    )

# ─────────────────────────── /STATS ───────────────────────────────

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)

    # Определяем цель: себя или другого пользователя
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("@"):
        target_id = find_user_by_username(args[1])
        if not target_id:
            await message.reply("❌ Пользователь не найден.")
            return
        target_name = get_username_by_id(target_id)
    else:
        target_id = message.from_user.id
        target_name = message.from_user.full_name

    u = get_user(target_id)
    if not u:
        await message.reply("❌ Пользователь не найден.")
        return

    stats = get_user_stats(target_id)
    level = calc_level(u["xp"])
    rank_name, rank_emoji = get_rank(level)

    # Дней в боте (с момента первого появления в БД — approximation by user_id order)
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM achievements WHERE user_id=?", (target_id,))
    ach_count = c.fetchone()[0]
    conn.close()

    m = get_marriage(target_id)
    marriage_info = "нет"
    if m:
        partner_id = m["user2_id"] if m["user1_id"] == target_id else m["user1_id"]
        partner_name = get_username_by_id(partner_id)
        days_married = (int(time.time()) - m["married_since"]) // 86400
        marriage_info = f"{partner_name} ({days_married} дн.)"

    await message.reply(
        f"📊 <b>Статистика: {target_name}</b>\n\n"
        f"🏆 Уровень: <b>{level}</b> ({u['xp']} XP)\n"
        f"🦊 Ранг: {rank_emoji} <b>{rank_name}</b>\n"
        f"💰 Баланс: <b>{u['balance']} 🪙</b>\n"
        f"💍 Брак: {marriage_info}\n\n"
        f"🎭 РП-действий: <b>{stats['total_rp_actions']}</b>\n"
        f"🎲 Игр сыграно: <b>{stats['total_games_played']}</b>\n"
        f"⚔️ Дуэлей выиграно: <b>{stats['total_duels_won']}</b>\n"
        f"💸 Монет подарено: <b>{stats['total_money_given']}</b>\n"
        f"❓ Правильных ответов в квизе: <b>{stats['total_quiz_correct']}</b>\n"
        f"🏅 Достижений: <b>{ach_count}/{len(ACHIEVEMENTS)}</b>",
        parse_mode="HTML",
    )

@router.message(Command("top_activity"))
async def cmd_top_activity(message: Message):
    """Топ пользователей по last_seen (last_daily_ts как приближение)."""
    conn = get_conn(); c = conn.cursor()
    # Используем daily_ts как last_seen, дополнительно XP как вторичный критерий
    c.execute("SELECT username, xp, daily_ts FROM users ORDER BY daily_ts DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()
    if not rows:
        await message.reply("📊 Статистика пуста.")
        return
    lines = ["📊 <b>Топ по активности (последний /daily):</b>\n"]
    now = int(time.time())
    for i, (name, xp, ts) in enumerate(rows, 1):
        if ts > 0:
            hours_ago = (now - ts) // 3600
            when = f"{hours_ago}ч назад" if hours_ago < 24 else f"{hours_ago // 24}д назад"
        else:
            when = "давно"
        lines.append(f"{i}. {name or '???'} — {when}")
    await message.reply("\n".join(lines), parse_mode="HTML")

@router.message(Command("top_rp_actions"))
async def cmd_top_rp_actions(message: Message):
    """Топ по количеству РП-действий."""
    conn = get_conn(); c = conn.cursor()
    c.execute(
        "SELECT u.username, s.total_rp_actions "
        "FROM user_stats s JOIN users u ON u.user_id=s.user_id "
        "ORDER BY s.total_rp_actions DESC LIMIT 10"
    )
    rows = c.fetchall()
    conn.close()
    if not rows:
        await message.reply("🎭 Статистика РП пуста.")
        return
    lines = ["🎭 <b>Топ по РП-действиям:</b>\n"]
    for i, (name, cnt) in enumerate(rows, 1):
        lines.append(f"{i}. {name or '???'} — {cnt} действий")
    await message.reply("\n".join(lines), parse_mode="HTML")

# ─────────────────── КАСТОМНЫЕ РП-КОМАНДЫ ─────────────────────────

@router.message(Command("create_rp"))
async def cmd_create_rp(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.reply(
            "✍️ Использование: /create_rp [слово] [текст ответа]\n\n"
            "Слово: 2-20 символов, только русские буквы, без пробелов.\n"
            "Пример: /create_rp мяукнуть {actor} мяукает на {target} 🐱"
        )
        return

    keyword = args[1].strip().lower()
    response_text = args[2].strip()

    # Валидация ключевого слова
    if not re.match(r'^[а-яёА-ЯЁ]{2,20}$', keyword):
        await message.reply("❌ Слово должно содержать только русские буквы (2-20 символов), без пробелов.")
        return

    # Проверяем конфликт со встроенными командами
    if keyword in RP_ALIAS:
        await message.reply("❌ Это слово уже занято встроенной РП-командой.")
        return

    uid = message.from_user.id

    # Лимит 10 команд на пользователя
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM custom_rp WHERE user_id=?", (uid,))
    cnt = c.fetchone()[0]
    conn.close()
    if cnt >= 10:
        await message.reply("❌ Достигнут лимит кастомных команд (10). Удалите старую: /delete_rp [слово]")
        return

    # Проверяем уникальность для пользователя
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT 1 FROM custom_rp WHERE user_id=? AND keyword=?", (uid, keyword))
    exists = c.fetchone()
    conn.close()
    if exists:
        await message.reply(f"❌ У вас уже есть команда «{keyword}». Удалите старую: /delete_rp {keyword}")
        return

    # Сохраняем
    conn = get_conn(); c = conn.cursor()
    c.execute(
        "INSERT INTO custom_rp (user_id, keyword, response, created_at) VALUES (?, ?, ?, ?)",
        (uid, keyword, response_text, int(time.time())),
    )
    conn.commit(); conn.close()

    await message.reply(
        f"✅ Кастомная РП-команда создана!\n"
        f"Ключевое слово: <b>{keyword}</b>\n"
        f"Используй: напиши <code>{keyword}</code> в ответ на сообщение пользователя.",
        parse_mode="HTML",
    )
    await check_achievements(uid, message)

@router.message(Command("my_rp"))
async def cmd_my_rp(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    conn = get_conn(); c = conn.cursor()
    c.execute(
        "SELECT keyword, response, uses_count FROM custom_rp WHERE user_id=? ORDER BY uses_count DESC",
        (message.from_user.id,),
    )
    rows = c.fetchall(); conn.close()
    if not rows:
        await message.reply("🎭 У вас нет кастомных РП-команд.\nСоздать: /create_rp [слово] [текст]")
        return
    lines = [f"🎭 <b>Ваши кастомные РП-команды</b> ({len(rows)}/10):\n"]
    for kw, resp, uses in rows:
        short_resp = resp[:40] + "..." if len(resp) > 40 else resp
        lines.append(f"• <b>{kw}</b> (используется: {uses})\n  <i>{short_resp}</i>")
    lines.append("\nУдалить: /delete_rp [слово]")
    await message.reply("\n".join(lines), parse_mode="HTML")

@router.message(Command("delete_rp"))
async def cmd_delete_rp(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    args = message.text.split()
    if len(args) < 2:
        await message.reply("❌ Использование: /delete_rp [слово]")
        return
    keyword = args[1].strip().lower()
    conn = get_conn(); c = conn.cursor()
    c.execute("DELETE FROM custom_rp WHERE user_id=? AND keyword=?", (message.from_user.id, keyword))
    deleted = c.rowcount
    conn.commit(); conn.close()
    if deleted:
        await message.reply(f"✅ Команда «{keyword}» удалена.")
    else:
        await message.reply(f"❌ Команда «{keyword}» не найдена.")

@router.message(Command("top_rp"))
async def cmd_top_rp(message: Message):
    """Топ кастомных РП-команд по uses_count."""
    conn = get_conn(); c = conn.cursor()
    c.execute(
        "SELECT cr.keyword, u.username, cr.uses_count "
        "FROM custom_rp cr JOIN users u ON u.user_id=cr.user_id "
        "ORDER BY cr.uses_count DESC LIMIT 10"
    )
    rows = c.fetchall(); conn.close()
    if not rows:
        await message.reply("🎭 Кастомных команд ещё нет.")
        return
    lines = ["🎭 <b>Топ кастомных РП-команд:</b>\n"]
    for i, (kw, name, uses) in enumerate(rows, 1):
        lines.append(f"{i}. <b>{kw}</b> от {name or '???'} — {uses} раз")
    await message.reply("\n".join(lines), parse_mode="HTML")

# ─────────────────── БОНУС ДНЯ ────────────────────────────────────

@router.message(Command("daily_bonus"))
async def cmd_daily_bonus(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    uid = message.from_user.id

    existing = get_active_bonus(uid)
    if existing:
        display = get_bonus_display(existing)
        await message.reply(
            f"🎁 Ваш бонус дня уже активен:\n<b>{display}</b>\n\n"
            f"Он действует до 23:59 UTC сегодня.",
            parse_mode="HTML",
        )
        return

    bonus_type = activate_bonus(uid)
    if not bonus_type:
        await message.reply("⚠️ Не удалось активировать бонус. Попробуйте позже.")
        return

    display = get_bonus_display(bonus_type)
    await message.reply(
        f"🎁 <b>Бонус дня активирован!</b>\n\n{display}\n\n"
        f"Действует до 23:59 UTC. Удачи! ✨",
        parse_mode="HTML",
    )

@router.message(Command("bonus_info"))
async def cmd_bonus_info(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    uid = message.from_user.id

    active = get_active_bonus(uid)

    # Рассчитываем время до следующего бонуса (до 00:00 UTC)
    now_utc = datetime.now(timezone.utc)
    midnight = now_utc.replace(hour=23, minute=59, second=59, microsecond=0)
    seconds_left = int((midnight - now_utc).total_seconds())
    h, remainder = divmod(seconds_left, 3600)
    m, _ = divmod(remainder, 60)

    if active:
        display = get_bonus_display(active)
        await message.reply(
            f"🎁 <b>Текущий бонус:</b>\n{display}\n\n"
            f"⏰ До конца дня: <b>{h}ч {m}м</b>\n\n"
            f"Завтра у вас будет новый бонус!",
            parse_mode="HTML",
        )
    else:
        await message.reply(
            f"🎁 У вас нет активного бонуса.\n\n"
            f"Активировать: /daily_bonus\n"
            f"⏰ До сброса: <b>{h}ч {m}м</b>",
            parse_mode="HTML",
        )

# ─────────────────────────── /ELO ────────────────────────────────
# Команда показывает твой личный ELO рейтинг для дуэлей
# ELO — система рейтинга: побеждаешь сильных → много очков, проигрываешь слабым → теряешь много

@router.message(Command("elo"))
async def cmd_elo(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    uid = message.from_user.id
    
    # Получаем текущий рейтинг пользователя (по умолчанию 1000)
    elo = get_elo(uid)
    
    # Получаем текстовый ранг (Новичок, Средний, Эксперт, Мастер и т.д.)
    rank = get_elo_rank(uid)
    
    # Получаем статистику игр из базы данных
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT games_played, games_won FROM elo_ratings WHERE user_id=?", (uid,))
    row = c.fetchone()
    conn.close()
    
    games = row[0] if row else 0      # Сколько всего дуэлей сыграл
    wins = row[1] if row else 0       # Сколько дуэлей выиграл
    
    # Считаем процент побед (если игр не было — 0%)
    winrate = (wins / games * 100) if games > 0 else 0
    
    # Отправляем красивое сообщение с рейтингом
    await message.reply(
        f"⚔️ <b>ELO РЕЙТИНГ</b>\n\n"
        f"📊 Рейтинг: <b>{elo}</b>\n"
        f"{rank}\n\n"
        f"🎮 Всего игр: <b>{games}</b>\n"
        f"🏆 Побед: <b>{wins}</b>\n"
        f"📈 Процент побед: <b>{winrate:.1f}%</b>",
        parse_mode="HTML"
    )

# ─────────────────────────── /PROFILE ─────────────────────────────
# Команда показывает красивую карточку пользователя с полной статистикой
# Использование: /profile — свой профиль, /profile @username — профиль другого
# В профиле есть: уровень, ранг, баланс, XP, ELO, брак, достижения, кастомные команды

@router.message(Command("profile"))
async def cmd_profile(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    
    # Определяем цель: себя или другого пользователя (если указан @username)
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("@"):
        target_id = find_user_by_username(args[1])
        if not target_id:
            await message.reply("❌ Пользователь не найден.")
            return
    else:
        target_id = message.from_user.id
    
    # Получаем данные пользователя из БД
    u = get_user(target_id)
    if not u:
        await message.reply("❌ Пользователь не найден.")
        return
    
    # Получаем статистику, уровень, ранг, ELO
    stats = get_user_stats(target_id)
    level = calc_level(u["xp"])
    rank_name, rank_emoji = get_rank(level)
    elo = get_elo(target_id)
    elo_rank = get_elo_rank(target_id)
    
    # Считаем количество полученных достижений
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM achievements WHERE user_id=?", (target_id,))
    ach_count = c.fetchone()[0]
    conn.close()
    
    # Получаем информацию о браке (если есть)
    m = get_marriage(target_id)
    if m:
        partner_id = m["user2_id"] if m["user1_id"] == target_id else m["user1_id"]
        partner_name = get_username_by_id(partner_id)
        partner_mention = f"<a href='tg://user?id={partner_id}'>{partner_name}</a>"
        days_married = (int(time.time()) - m["married_since"]) // 86400
        marriage_info = f"💍 {partner_mention} ({days_married} дн.)"
    else:
        marriage_info = "💔 нет"
    
    # Создаём кликабельное имя пользователя
    user_name = u["username"] or str(target_id)
    user_mention = f"<a href='tg://user?id={target_id}'>{user_name}</a>"
    
    # Красивая карточка с рамкой
    profile_text = f"""
╔════════════════════════════════════════╗
║        🦊 <b>ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ</b> 🦊       ║
╠════════════════════════════════════════╣
║                                        ║
║    🌟 {user_mention}
║                                        ║
║    🏆 Уровень: <b>{level}</b>
║    {rank_emoji} Ранг: <b>{rank_name}</b>
║    💰 Баланс: <b>{u['balance']} 🪙</b>
║    ✨ Опыт: <b>{u['xp']} XP</b>
║    ⚔️ ELO: <b>{elo}</b> ({elo_rank})
║    💍 Брак: {marriage_info}
║                                        ║
╠════════════════════════════════════════╣
║        📊 <b>СТАТИСТИКА</b>                 ║
╠════════════════════════════════════════╣
║                                        ║
║    🎭 РП-действий: <b>{stats['total_rp_actions']}</b>
║    🎲 Игр сыграно: <b>{stats['total_games_played']}</b>
║    ⚔️ Дуэлей выиграно: <b>{stats['total_duels_won']}</b>
║    💸 Монет подарено: <b>{stats['total_money_given']}</b>
║    ❓ Правильных ответов: <b>{stats['total_quiz_correct']}</b>
║    🏅 Достижений: <b>{ach_count}/12</b>
║                                        ║
╚════════════════════════════════════════╝
"""
    
    # Кнопки для просмотра достижений и кастомных команд
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏅 Достижения", callback_data=f"profile_achievements_{target_id}"),
            InlineKeyboardButton(text="🎭 Мои команды", callback_data=f"profile_commands_{target_id}"),
        ]
    ])
    
    await message.reply(profile_text, parse_mode="HTML", reply_markup=kb)


# ─────────────────── ПРОФИЛЬ: ДОСТИЖЕНИЯ ─────────────────────────
# Обработчик кнопки "Достижения" в профиле
# Показывает список всех 12 достижений и статус (получено/нет)

@router.callback_query(F.data.startswith("profile_achievements_"))
async def profile_achievements(call: CallbackQuery):
    target_id = int(call.data.split("_")[2])
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT achievement_id FROM achievements WHERE user_id=?", (target_id,))
    earned = [row[0] for row in c.fetchall()]
    conn.close()
    
    text = "🏅 <b>ДОСТИЖЕНИЯ</b>\n\n"
    for ach_id, ach in ACHIEVEMENTS.items():
        status = "✅" if ach_id in earned else "🔒"
        text += f"{status} {ach['icon']} <b>{ach['name']}</b>\n   <i>{ach['desc']}</i>\n\n"
    
    await call.message.edit_text(text, parse_mode="HTML")


# ─────────────────── ПРОФИЛЬ: КАСТОМНЫЕ КОМАНДЫ ──────────────────
# Обработчик кнопки "Мои команды" в профиле
# Показывает список кастомных РП-команд пользователя

@router.callback_query(F.data.startswith("profile_commands_"))
async def profile_commands(call: CallbackQuery):
    target_id = int(call.data.split("_")[2])
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT keyword, uses_count FROM custom_rp WHERE user_id=? ORDER BY uses_count DESC", (target_id,))
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        text = "🎭 <b>КАСТОМНЫЕ КОМАНДЫ</b>\n\nУ пользователя нет кастомных РП-команд."
    else:
        text = "🎭 <b>КАСТОМНЫЕ КОМАНДЫ</b>\n\n"
        for kw, uses in rows:
            text += f"• <b>{kw}</b> (использований: {uses})\n"
    
    await call.message.edit_text(text, parse_mode="HTML")

# ─────────────────────────── /TOP_ELO ─────────────────────────────
# Команда показывает топ-10 игроков по ELO рейтингу

@router.message(Command("top_elo"))
async def cmd_top_elo(message: Message):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT u.user_id, u.username, e.rating 
        FROM elo_ratings e 
        JOIN users u ON u.user_id = e.user_id 
        ORDER BY e.rating DESC LIMIT 10
    """)
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        await message.reply("⚔️ Нет данных для топа ELO. Сыграйте в дуэль!")
        return
    
    lines = ["⚔️ <b>ТОП ПО ELO РЕЙТИНГУ</b>\n"]
    for i, (uid, name, rating) in enumerate(rows, 1):
        display_name = name or str(uid)
        mention = f"<a href='tg://user?id={uid}'>{display_name}</a>"
        # Определяем значок для топ-3
        medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
        lines.append(f"{medal} {mention} — <b>{rating}</b> ({get_elo_rank(uid)})")
    
    await message.reply("\n".join(lines), parse_mode="HTML")

# ═══════════════════════════════════════════════════════════════════
# ─────────────────────────── РП-ХЭНДЛЕР ──────────────────────────
# ═══════════════════════════════════════════════════════════════════

@router.message(F.text)
async def rp_handler(message: Message):
    if not message.text:
        return

    uid = message.from_user.id
    text = message.text.strip()

    # ── Проверка встроенных РП-команд ──
    m = RP_PATTERN.match(text)
    if m:
        if message.reply_to_message is None:
            await message.reply("💬 Чтобы совершить действие, ответьте на сообщение нужного пользователя!")
            return

        keyword = m.group(1).lower()
        canonical = RP_ALIAS.get(keyword)
        if not canonical:
            return

        verb, emoji, phrases = RP_ACTIONS[canonical]
        ensure_user(uid, message.from_user.username or message.from_user.full_name)
        target = message.reply_to_message.from_user
        ensure_user(target.id, target.username or target.full_name)

        actor_name = message.from_user.full_name
        actor_id   = uid
        target_name = target.full_name
        target_id   = target.id
        phrase = random.choice(phrases)

        partner_id = get_partner_id(actor_id)
        is_spouse  = partner_id == target_id

        if canonical in ("обнять", "обнял", "обнимаю") and is_spouse:
            base_xp = 10
            text_msg = (
                f"❤️ {mention(actor_name, actor_id)} нежно обнимает своего\\(ю\\) супруг\\(у\\) "
                f"{mention(target_name, target_id)} с особой теплотой\\! ❤️"
            )
            parse = "MarkdownV2"
        else:
            base_xp = 5
            text_msg = (
                f"{mention(actor_name, actor_id)} {verb} {mention(target_name, target_id)} "
                f"{phrase} {emoji}"
            )
            parse = "Markdown"

        # Бонус "День объятий": +10 XP за РП
        day_bonus = get_active_bonus(actor_id)
        if day_bonus == "rp_xp":
            base_xp += 10

        # Бонус "День защиты": защитить даёт +15 XP
        if canonical == "защитить" and day_bonus == "protect_xp":
            base_xp += 15

        xp_gain = apply_xp_bonus(actor_id, base_xp)
        add_xp(actor_id, xp_gain)

        # Статистика: РП-действие
        stat_increment(actor_id, "total_rp_actions")

        await message.reply(text_msg, parse_mode=parse)
        await check_achievements(actor_id, message)
        return

    # ── Проверка кастомных РП-команд ──
    ensure_user(uid, message.from_user.username or message.from_user.full_name)
    result = check_custom_rp(uid, text)
    if result:
        keyword, response_text = result
        if message.reply_to_message is None:
            await message.reply("💬 Чтобы использовать кастомное действие, ответьте на сообщение пользователя!")
            return

        target = message.reply_to_message.from_user
        ensure_user(target.id, target.username or target.full_name)

                # Подстановка {actor} и {target} с упоминаниями (как в обычных РП)
        actor_id = message.from_user.id
        target_id = target.id
        actor_name = message.from_user.full_name
        target_name = target.full_name
        
        # Создаём кликабельные упоминания
        actor_mention = f"<a href='tg://user?id={actor_id}'>{actor_name}</a>"
        target_mention = f"<a href='tg://user?id={target_id}'>{target_name}</a>"
        
        # Заменяем переменные
        final_text = (
            response_text
            .replace("{actor}", actor_mention)      # ссылка на актёра
            .replace("{target}", target_mention)    # ссылка на цель
            .replace("{actor_name}", actor_name)    # просто имя актёра
            .replace("{target_name}", target_name)  # просто имя цели
        )

        # +5 XP за использование своей кастомной команды
        xp = apply_xp_bonus(uid, 5)
        add_xp(uid, xp)
        stat_increment(uid, "total_rp_actions")

        await message.reply(f"🎭 {final_text}", parse_mode="HTML")
        await check_achievements(uid, message)

# ─────────────────── БЭКАПЫ БД ───────────────────────────────────

def backup_database():
    """Создаёт бэкап базы данных в папку /app/data/backups"""
    try:
        backup_dir = "/app/data/backups"
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(backup_dir, f"database_backup_{timestamp}.db")
        
        shutil.copy2(DB_FILE, backup_file)
        
        # Удаляем старые бэкапы (оставляем только 7 последних)
        backups = sorted([f for f in os.listdir(backup_dir) if f.startswith("database_backup_")])
        for old_backup in backups[:-7]:
            os.remove(os.path.join(backup_dir, old_backup))
        
        logger.info(f"Бэкап создан: {backup_file}")
        return True
    except Exception as e:
        logger.error(f"Ошибка бэкапа: {e}")
        return False

async def scheduled_backup():
    """Запускает бэкап каждые 24 часа"""
    while True:
        await asyncio.sleep(86400)  # 24 часа
        backup_database()

# ──────────────────────────── ЗАПУСК ──────────────────────────────

async def main():
    init_db()
    if not ADMIN_IDS:
        logger.warning("⚠️  ADMIN_IDS не заданы! Добавь свой ID в .env: ADMIN_IDS=123456789")
    
    # Запускаем фоновый бэкап
    asyncio.create_task(scheduled_backup())
    
    logger.info("Бот v3.0 запускается...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
