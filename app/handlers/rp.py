import random
import re
import time
from typing import Optional

from aiogram import F
from aiogram.filters import Command
from aiogram.types import Message

from app.core import router
from app.db import get_conn
from app.shared import add_xp


RARE_CHANCE = 0.05
COMBO_REQUIRED = 3
COMBO_BONUS_XP = 15

# Память для комбо. Сбрасывается при перезапуске бота — это нормально.
rp_combo: dict[tuple[int, int], list[str]] = {}


# ───────── DEFAULT ACTIONS ─────────
# ВАЖНО: текущие РП-команды оставлены из твоего файла.
RP_ACTIONS = {
    "трахнуть":        ("трахнул",            "🥵", ["жёстко", "загнал в угол", "схватив за волосы"]),
    "выебать":         ("выебал",             "👀", ["страсно", "безпощадно"]),
    "отдаться":        ("отдался",            "😳", ["с ухмылкой", "раздвинув ноги"]),
    "засосать":        ("засосал",            "🫦", ["жадно", "прижав к себе"]),
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
    "поправить шапку": ("поправляет шапку",   "🧢", ["заботливо", "нежно", "с улыбкой", "аккуратно"]),
    "защитить":        ("защищает",           "🛡️", ["смело", "без колебаний", "решительно", "с гордостью"]),
    "пожалеть":        ("жалеет",             "🤗", ["с теплотой", "по-доброму", "искренне", "с объятием"]),
    "похитить":        ("похищает",           "🚗", ["в ночи", "стремительно", "шутливо", "с хохотом"]),
}


def _html_mention(user_id: int, name: str) -> str:
    safe_name = (name or str(user_id)).replace("<", "&lt;").replace(">", "&gt;")
    return f"<a href='tg://user?id={user_id}'>{safe_name}</a>"


def _username_to_id(username: str) -> Optional[int]:
    username = username.lstrip("@").strip()
    if not username:
        return None

    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE lower(username)=lower(?)", (username,))
    row = c.fetchone()
    conn.close()

    return row[0] if row else None


def _get_username_by_id(user_id: int) -> str:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] else str(user_id)


def _ensure_user(user_id: int, username: str = ""):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username or ""))
    if username:
        c.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
    conn.commit()
    conn.close()


def init_tables():
    conn = get_conn()
    c = conn.cursor()

    # Совместимая таблица кастомных РП.
    # В старом проекте уже могла быть колонка response, поэтому используем именно её.
    c.execute("""
        CREATE TABLE IF NOT EXISTS custom_rp (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            keyword TEXT,
            response TEXT,
            uses_count INTEGER DEFAULT 0,
            created_at INTEGER,
            UNIQUE(user_id, keyword)
        )
    """)

    # Миграции на случай старой/кривой таблицы.
    c.execute("PRAGMA table_info(custom_rp)")
    cols = {row[1] for row in c.fetchall()}
    if "response" not in cols:
        try:
            c.execute("ALTER TABLE custom_rp ADD COLUMN response TEXT DEFAULT ''")
        except Exception:
            pass
    if "uses_count" not in cols:
        try:
            c.execute("ALTER TABLE custom_rp ADD COLUMN uses_count INTEGER DEFAULT 0")
        except Exception:
            pass
    if "created_at" not in cols:
        try:
            c.execute("ALTER TABLE custom_rp ADD COLUMN created_at INTEGER DEFAULT 0")
        except Exception:
            pass

    # Статистика РП без ON CONFLICT, чтобы не падать на старой таблице без UNIQUE.
    c.execute("""
        CREATE TABLE IF NOT EXISTS rp_stats (
            actor_id INTEGER,
            target_id INTEGER,
            action TEXT DEFAULT '',
            count INTEGER DEFAULT 1,
            last_ts INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()


init_tables()


def _get_custom_column() -> str:
    """Определяем, где лежит текст кастомной команды: response или text."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("PRAGMA table_info(custom_rp)")
    cols = {row[1] for row in c.fetchall()}
    conn.close()
    if "response" in cols:
        return "response"
    return "text"


def _find_action(text: str) -> Optional[str]:
    lower = text.strip().lower()

    # Сначала встроенные команды, от длинных к коротким.
    for action in sorted(RP_ACTIONS.keys(), key=len, reverse=True):
        if lower == action or lower.startswith(action + " "):
            return action

    # Потом кастомные РП.
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT keyword FROM custom_rp")
    rows = c.fetchall()
    conn.close()

    keywords = sorted((row[0] for row in rows if row[0]), key=len, reverse=True)
    for keyword in keywords:
        kw = keyword.lower()
        if lower == kw or lower.startswith(kw + " "):
            return keyword

    return None


def _get_target(message: Message) -> tuple[Optional[int], Optional[str]]:
    """Возвращает (target_id, target_display). ID может быть 0, если @user не найден в базе."""
    if message.reply_to_message and message.reply_to_message.from_user:
        user = message.reply_to_message.from_user
        _ensure_user(user.id, user.username or user.full_name)
        return user.id, _html_mention(user.id, user.full_name)

    if message.entities:
        for entity in message.entities:
            if entity.type == "mention":
                username = message.text[entity.offset:entity.offset + entity.length]
                uid = _username_to_id(username)
                if uid:
                    return uid, _html_mention(uid, _get_username_by_id(uid))
                return 0, username

            if entity.type == "text_mention" and entity.user:
                user = entity.user
                _ensure_user(user.id, user.username or user.full_name)
                return user.id, _html_mention(user.id, user.full_name)

    return None, None


def _increment_rp_stats(actor_id: int, target_id: int, action: str):
    now = int(time.time())

    conn = get_conn()
    c = conn.cursor()

    # Без ON CONFLICT — работает даже если таблица была создана старой схемой.
    c.execute(
        "SELECT count FROM rp_stats WHERE actor_id=? AND target_id=? AND action=?",
        (actor_id, target_id, action),
    )
    row = c.fetchone()

    if row:
        c.execute(
            "UPDATE rp_stats SET count=count+1, last_ts=? WHERE actor_id=? AND target_id=? AND action=?",
            (now, actor_id, target_id, action),
        )
    else:
        c.execute(
            "INSERT INTO rp_stats (actor_id, target_id, action, count, last_ts) VALUES (?, ?, ?, 1, ?)",
            (actor_id, target_id, action, now),
        )

    conn.commit()
    conn.close()


def _increment_total_rp(user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO user_stats (user_id) VALUES (?)", (user_id,))
    c.execute("UPDATE user_stats SET total_rp_actions = total_rp_actions + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def _get_favorite_partner(user_id: int) -> Optional[tuple[int, int]]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT target_id, SUM(count) AS total
        FROM rp_stats
        WHERE actor_id=? AND target_id > 0
        GROUP BY target_id
        ORDER BY total DESC
        LIMIT 1
    """, (user_id,))
    row = c.fetchone()
    conn.close()
    return (row[0], row[1]) if row else None


def _get_favorite_action(user_id: int) -> Optional[tuple[str, int]]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT action, SUM(count) AS total
        FROM rp_stats
        WHERE actor_id=?
        GROUP BY action
        ORDER BY total DESC
        LIMIT 1
    """, (user_id,))
    row = c.fetchone()
    conn.close()
    return (row[0], row[1]) if row else None


def _render_builtin_action(actor_display: str, target_display: str, action_key: str) -> str:
    verb, emoji, phrases = RP_ACTIONS[action_key]
    phrase = random.choice(phrases)
    return f"{emoji} {actor_display} {verb} {target_display} {phrase}"


def _get_custom_response(keyword: str) -> Optional[tuple[str, int]]:
    column = _get_custom_column()
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"SELECT {column}, user_id FROM custom_rp WHERE lower(keyword)=lower(?)", (keyword,))
    row = c.fetchone()
    conn.close()
    return (row[0], row[1]) if row else None


def _increment_custom_uses(keyword: str):
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("UPDATE custom_rp SET uses_count = COALESCE(uses_count, 0) + 1 WHERE lower(keyword)=lower(?)", (keyword,))
        conn.commit()
    finally:
        conn.close()


def _apply_custom_template(template: str, actor_display: str, target_display: str, actor_name: str, target_name: str) -> str:
    return (
        template
        .replace("{actor}", actor_display)
        .replace("{target}", target_display)
        .replace("{actor_name}", actor_name)
        .replace("{target_name}", target_name)
    )


@router.message(Command("create_rp"))
async def create_rp(message: Message):
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.reply(
            "🎭 <b>Создание РП-команды</b>\n\n"
            "Использование:\n"
            "<code>/create_rp слово текст</code>\n\n"
            "Переменные:\n"
            "<code>{actor}</code> — кто делает\n"
            "<code>{target}</code> — цель\n"
            "<code>{actor_name}</code> — имя без ссылки\n"
            "<code>{target_name}</code> — имя цели без ссылки\n\n"
            "Пример:\n"
            "<code>/create_rp мур {actor} мурчит рядом с {target} 🐾</code>",
            parse_mode="HTML",
        )
        return

    keyword = args[1].strip().lower()
    response = args[2].strip()

    if not re.fullmatch(r"[а-яёa-z0-9_-]{2,24}", keyword, flags=re.IGNORECASE):
        await message.reply("❌ Слово должно быть 2–24 символа: буквы, цифры, _ или -")
        return

    if keyword in RP_ACTIONS:
        await message.reply("❌ Это слово уже занято встроенной РП-командой.")
        return

    column = _get_custom_column()
    now = int(time.time())

    conn = get_conn()
    c = conn.cursor()

    # Удаляем старую команду пользователя с таким словом, чтобы не зависеть от UNIQUE.
    c.execute("DELETE FROM custom_rp WHERE user_id=? AND lower(keyword)=lower(?)", (message.from_user.id, keyword))

    if column == "response":
        c.execute(
            "INSERT INTO custom_rp (user_id, keyword, response, uses_count, created_at) VALUES (?, ?, ?, 0, ?)",
            (message.from_user.id, keyword, response, now),
        )
    else:
        c.execute(
            "INSERT INTO custom_rp (user_id, keyword, text) VALUES (?, ?, ?)",
            (message.from_user.id, keyword, response),
        )

    conn.commit()
    conn.close()

    preview_actor = _html_mention(message.from_user.id, message.from_user.full_name)
    preview = _apply_custom_template(response, preview_actor, "@target", message.from_user.full_name, "target")

    await message.reply(
        f"✅ <b>Кастомная РП-команда создана!</b>\n\n"
        f"Команда: <code>{keyword}</code>\n"
        f"Пример:\n{preview}",
        parse_mode="HTML",
    )


@router.message(Command("my_rp"))
async def my_rp(message: Message):
    column = _get_custom_column()

    conn = get_conn()
    c = conn.cursor()
    c.execute(
        f"SELECT keyword, {column}, COALESCE(uses_count, 0) FROM custom_rp WHERE user_id=? ORDER BY uses_count DESC, keyword ASC",
        (message.from_user.id,),
    )
    rows = c.fetchall()
    conn.close()

    if not rows:
        await message.reply("🎭 У тебя пока нет кастомных РП.\nСоздать: /create_rp слово текст")
        return

    lines = [f"🎭 <b>Твои кастомные РП</b> ({len(rows)}):\n"]
    for keyword, response, uses in rows:
        short = response[:45] + "..." if response and len(response) > 45 else response
        lines.append(f"• <code>{keyword}</code> — {uses} исп.\n  <i>{short}</i>")

    lines.append("\nУдалить: /delete_rp слово")
    await message.reply("\n".join(lines), parse_mode="HTML")


@router.message(Command("delete_rp"))
async def delete_rp(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❗ Использование: /delete_rp слово")
        return

    keyword = args[1].strip().lower()

    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM custom_rp WHERE user_id=? AND lower(keyword)=lower(?)", (message.from_user.id, keyword))
    deleted = c.rowcount
    conn.commit()
    conn.close()

    if deleted:
        await message.reply(f"✅ Команда <code>{keyword}</code> удалена.", parse_mode="HTML")
    else:
        await message.reply(f"❌ Команда <code>{keyword}</code> не найдена.", parse_mode="HTML")


@router.message(Command("fav_rp"))
async def fav_rp(message: Message):
    fav_partner = _get_favorite_partner(message.from_user.id)
    fav_action = _get_favorite_action(message.from_user.id)

    if not fav_partner and not fav_action:
        await message.reply("📊 РП-статистики пока нет.")
        return

    lines = ["📊 <b>Твоя РП-статистика</b>\n"]

    if fav_partner:
        partner_id, count = fav_partner
        partner_name = _get_username_by_id(partner_id)
        lines.append(f"👥 Любимый партнёр: {_html_mention(partner_id, partner_name)} — <b>{count}</b> раз")

    if fav_action:
        action, count = fav_action
        lines.append(f"🎭 Любимое действие: <b>{action}</b> — <b>{count}</b> раз")

    await message.reply("\n".join(lines), parse_mode="HTML")


@router.message(Command("top_rp_pairs"))
async def top_rp_pairs(message: Message):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT actor_id, target_id, SUM(count) AS total
        FROM rp_stats
        WHERE target_id > 0
        GROUP BY actor_id, target_id
        ORDER BY total DESC
        LIMIT 10
    """)
    rows = c.fetchall()
    conn.close()

    if not rows:
        await message.reply("📊 Топ РП-пар пока пуст.")
        return

    lines = ["🏆 <b>Топ РП-пар</b>\n"]
    for i, (actor_id, target_id, total) in enumerate(rows, 1):
        actor_name = _get_username_by_id(actor_id)
        target_name = _get_username_by_id(target_id)
        lines.append(
            f"{i}. {_html_mention(actor_id, actor_name)} → {_html_mention(target_id, target_name)} — <b>{total}</b>"
        )

    await message.reply("\n".join(lines), parse_mode="HTML")


@router.message(F.text)
async def rp_handler(message: Message):
    if not message.text:
        return

    action_key = _find_action(message.text)
    if not action_key:
        return

    target_id, target_display = _get_target(message)
    if target_display is None:
        await message.reply("❗ Укажи цель: ответь на сообщение или напиши @user")
        return

    actor = message.from_user
    _ensure_user(actor.id, actor.username or actor.full_name)
    actor_display = _html_mention(actor.id, actor.full_name)

    custom = _get_custom_response(action_key)
    if custom:
        template, owner_id = custom
        target_name = target_display
        if target_id and target_id > 0:
            target_name = _get_username_by_id(target_id)
        action_text = _apply_custom_template(
            template,
            actor_display,
            target_display,
            actor.full_name,
            target_name,
        )
        _increment_custom_uses(action_key)
    else:
        action_text = _render_builtin_action(actor_display, target_display, action_key)

    real_target_id = target_id or 0

    # Статистика РП
    _increment_rp_stats(actor.id, real_target_id, action_key)
    _increment_total_rp(actor.id)

    # XP
    xp = random.randint(3, 6)

    # Редкое событие
    rare = ""
    if random.random() < RARE_CHANCE:
        bonus = random.randint(10, 20)
        xp += bonus
        rare = f"\n✨ <b>Особое взаимодействие!</b> +{bonus} XP"

    # Комбо
    combo = ""
    combo_key = (actor.id, real_target_id)
    rp_combo.setdefault(combo_key, []).append(action_key)

    if len(rp_combo[combo_key]) >= COMBO_REQUIRED:
        xp += COMBO_BONUS_XP
        combo = f"\n💞 <b>Комбо!</b> +{COMBO_BONUS_XP} XP"
        rp_combo[combo_key] = []

    add_xp(actor.id, xp)

    await message.reply(
        f"{action_text}\n💫 +{xp} XP{rare}{combo}",
        parse_mode="HTML",
    )
