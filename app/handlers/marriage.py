from aiogram import F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.shared import *

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

