
import asyncio
import math
import os
import random
import re
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional

from aiogram import F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.core import ADMIN_IDS, DB_FILE, admin_actions, bot, logger, router, AdminInputFilter
from app.db import get_conn
from app.constants import (
    ACHIEVEMENTS,
    DAILY_BONUSES,
    PREDICTIONS,
    QUIZ_QUESTIONS,
    RP_ACTIONS,
    RP_ALIAS,
    RP_PATTERN,
    SHOP_ITEMS,
    get_next_rank,
    get_rank,
)

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

# ═══════════════════════════════════════════════════════════════════
# ─────────────────── НОВЫЙ ФУНКЦИОНАЛ v3 ──────────────────────────
# ═══════════════════════════════════════════════════════════════════


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
