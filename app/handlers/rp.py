
import random
import sqlite3
from aiogram import F
from aiogram.types import Message
from aiogram.filters import Command
from app.core import router
from app.shared import add_xp

DB_PATH = "database.db"

RARE_CHANCE = 0.05
rp_combo = {}

# ───────── DB ─────────
def get_conn():
    return sqlite3.connect(DB_PATH)

def init_tables():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS custom_rp (
        user_id INTEGER,
        keyword TEXT,
        text TEXT
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS rp_stats (
        actor_id INTEGER,
        target_id INTEGER,
        count INTEGER DEFAULT 1
    )
    """)
    conn.commit()
    conn.close()

init_tables()

# ───────── DEFAULT ACTIONS ─────────
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

# ───────── TARGET ─────────
def get_target(message: Message):
    if message.reply_to_message:
        return message.reply_to_message.from_user
    if message.entities:
        for e in message.entities:
            if e.type == "mention":
                return message.text[e.offset:e.offset+e.length]
    return None

# ───────── CUSTOM RP ─────────
@router.message(Command("create_rp"))
async def create_rp(message: Message):
    try:
        _, keyword, *text = message.text.split()
        text = " ".join(text)

        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "INSERT INTO custom_rp (user_id, keyword, text) VALUES (?, ?, ?)",
            (message.from_user.id, keyword, text)
        )
        conn.commit()
        conn.close()

        await message.reply(f"✅ Команда '{keyword}' создана!")

    except:
        await message.reply("❗ Используй: /create_rp слово текст")

@router.message(Command("my_rp"))
async def my_rp(message: Message):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT keyword FROM custom_rp WHERE user_id=?",
        (message.from_user.id,)
    )
    rows = c.fetchall()
    conn.close()

    if not rows:
        return await message.reply("❌ У тебя нет кастомных РП")

    text = "🎭 Твои РП:\n"
    for r in rows:
        text += f"• {r[0]}\n"

    await message.reply(text)

# ───────── MAIN RP ─────────
@router.message(F.text)
async def rp_handler(message: Message):
    word = message.text.lower().split()[0]

    target = get_target(message)
    if not target:
        return

    actor = message.from_user

    conn = get_conn()
    c = conn.cursor()

    # кастомные
    c.execute(
        "SELECT text FROM custom_rp WHERE keyword=?",
        (word,)
    )
    custom = c.fetchone()

    if custom:
        action_text = custom[0].replace("{actor}", actor.first_name)
        target_name = target.first_name if hasattr(target,"first_name") else target
        action_text = action_text.replace("{target}", target_name)
    elif word in RP_ACTIONS:
        action_text = f"{actor.first_name} {random.choice(RP_ACTIONS[word])} {target.first_name if hasattr(target,'first_name') else target}"
    else:
        conn.close()
        return

    # статистика
    target_id = getattr(target, "id", 0)
    c.execute("""
    INSERT INTO rp_stats (actor_id, target_id, count)
    VALUES (?, ?, 1)
    ON CONFLICT(actor_id, target_id) DO UPDATE SET count = count + 1
    """, (actor.id, target_id))

    conn.commit()
    conn.close()

    xp = random.randint(3,6)

    # редкое событие
    rare = ""
    if random.random() < RARE_CHANCE:
        bonus = random.randint(10,20)
        xp += bonus
        rare = f"\n✨ Особое взаимодействие +{bonus} XP"

    # комбо
    key = (actor.id, target_id)
    rp_combo.setdefault(key, []).append(word)

    combo = ""
    if len(rp_combo[key]) >= 3:
        xp += 15
        combo = "\n💞 Комбо +15 XP"
        rp_combo[key] = []

    add_xp(actor.id, xp)

    await message.reply(f"{action_text}\n💫 +{xp} XP{rare}{combo}")

# ───────── FAVORITE PARTNER ─────────
@router.message(Command("fav_rp"))
async def fav_rp(message: Message):
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
    SELECT target_id, count FROM rp_stats
    WHERE actor_id=?
    ORDER BY count DESC LIMIT 1
    """, (message.from_user.id,))

    row = c.fetchone()
    conn.close()

    if not row:
        return await message.reply("❌ Нет статистики")

    await message.reply(f"👥 Любимый партнёр ID: {row[0]} (взаимодействий: {row[1]})")
