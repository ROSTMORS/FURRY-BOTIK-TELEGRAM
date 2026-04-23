
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
    CATEGORY_META,
    DAILY_BONUSES,
    PREDICTIONS,
    QUIZ_QUESTIONS,
    RARITY_META,
    RP_ACTIONS,
    RP_ALIAS,
    RP_PATTERN,
    SHOP_ITEMS,
    category_label,
    get_next_rank,
    get_rank,
    hat_drop_pool,
    rarity_badge,
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

# ─────────────────── ЭФФЕКТЫ ПРЕДМЕТОВ 2.0 ───────────────────────

def cleanup_expired_effects(user_id: int | None = None):
    conn = get_conn()
    c = conn.cursor()
    now = int(time.time())
    if user_id is None:
        c.execute("DELETE FROM active_effects WHERE expires_at > 0 AND expires_at <= ?", (now,))
        c.execute("DELETE FROM active_effects WHERE uses_left <= 0")
    else:
        c.execute("DELETE FROM active_effects WHERE user_id=? AND expires_at > 0 AND expires_at <= ?", (user_id, now))
        c.execute("DELETE FROM active_effects WHERE user_id=? AND uses_left <= 0", (user_id,))
    conn.commit()
    conn.close()


def add_active_effect(user_id: int, effect_key: str, effect_value: float, duration_hours: int = 24, uses: int = 1, source_item_id: int = 0):
    cleanup_expired_effects(user_id)
    now = int(time.time())
    expires_at = now + int(duration_hours * 3600) if duration_hours else 0
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO active_effects (user_id, effect_key, effect_value, expires_at, uses_left, source_item_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, effect_key, effect_value, expires_at, uses, source_item_id, now),
    )
    conn.commit()
    conn.close()


def get_active_effects(user_id: int) -> list[dict]:
    cleanup_expired_effects(user_id)
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT id, effect_key, effect_value, expires_at, uses_left, source_item_id, created_at FROM active_effects WHERE user_id=? ORDER BY created_at ASC",
        (user_id,),
    )
    rows = c.fetchall()
    conn.close()
    return [
        {
            "id": row[0],
            "effect_key": row[1],
            "effect_value": row[2],
            "expires_at": row[3],
            "uses_left": row[4],
            "source_item_id": row[5],
            "created_at": row[6],
        }
        for row in rows
    ]


def get_effect_value(user_id: int, effect_key: str) -> float:
    effects = get_active_effects(user_id)
    return sum(float(e["effect_value"]) for e in effects if e["effect_key"] == effect_key)


def consume_effects(user_id: int, effect_key: str, count: int = 1):
    if count <= 0:
        return
    cleanup_expired_effects(user_id)
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT id, uses_left FROM active_effects WHERE user_id=? AND effect_key=? ORDER BY created_at ASC",
        (user_id, effect_key),
    )
    rows = c.fetchall()
    remaining = count
    for effect_id, uses_left in rows:
        if remaining <= 0:
            break
        take = min(uses_left, remaining)
        new_uses = uses_left - take
        if new_uses <= 0:
            c.execute("DELETE FROM active_effects WHERE id=?", (effect_id,))
        else:
            c.execute("UPDATE active_effects SET uses_left=? WHERE id=?", (new_uses, effect_id))
        remaining -= take
    conn.commit()
    conn.close()


def has_inventory_item(user_id: int, item_id: int) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT amount FROM inventory WHERE user_id=? AND item_id=? AND amount>0", (user_id, item_id))
    row = c.fetchone()
    conn.close()
    return bool(row)


def format_effect_line(effect: dict) -> str:
    item = SHOP_ITEMS.get(effect["source_item_id"], {})
    item_name = item.get("name", "Эффект")
    now = int(time.time())
    if effect["expires_at"] > 0:
        left = max(0, effect["expires_at"] - now)
        h, rem = divmod(left // 60, 60)
        ttl = f"{h}ч {rem}м"
    else:
        ttl = "без срока"
    value = effect["effect_value"]
    if effect["effect_key"] == "duel_roll_bonus":
        detail = f"+{int(value)} к следующей дуэли"
    elif effect["effect_key"] == "slots_bonus":
        detail = f"+{int(value * 100)}% к слоту"
    else:
        detail = str(value)
    return f"• {item_name}: <b>{detail}</b> | использований: <b>{effect['uses_left']}</b> | срок: <b>{ttl}</b>"


# ─────────────────── РП-ДЕЙСТВИЯ ──────────────────────────────────


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
