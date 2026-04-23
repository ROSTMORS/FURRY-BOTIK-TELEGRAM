import sqlite3

from app.core import DB_FILE

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

        -- Универсальные временные эффекты предметов 2.0
        CREATE TABLE IF NOT EXISTS active_effects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            effect_key TEXT NOT NULL,
            effect_value REAL DEFAULT 0,
            expires_at INTEGER DEFAULT 0,
            uses_left INTEGER DEFAULT 1,
            source_item_id INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT 0
        );

        -- История дуэлей 2.0
        CREATE TABLE IF NOT EXISTS duel_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            winner_id INTEGER,
            loser_id INTEGER,
            bet INTEGER DEFAULT 0,
            mode TEXT DEFAULT 'classic',
            battle_log TEXT DEFAULT '',
            ts INTEGER DEFAULT 0
        );
    """)

    # ── МИГРАЦИЯ: добавляем недостающие колонки в существующую таблицу user_stats ──
    try:
        c.execute("ALTER TABLE user_stats ADD COLUMN first_seen INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # колонка уже существует
    try:
        c.execute("ALTER TABLE user_stats ADD COLUMN last_seen INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()
