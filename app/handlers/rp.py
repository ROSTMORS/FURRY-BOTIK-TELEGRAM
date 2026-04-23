from aiogram import F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.shared import *

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
        update_quest_progress(actor_id, "rp_action", 1)

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
        update_quest_progress(uid, "rp_action", 1)

        await message.reply(f"🎭 {final_text}", parse_mode="HTML")
        await check_achievements(uid, message)

