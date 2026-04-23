from aiogram import F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from app.core import router


def help_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎭 РП", callback_data="help_rp"),
            InlineKeyboardButton(text="💰 Экономика", callback_data="help_economy"),
        ],
        [
            InlineKeyboardButton(text="🎰 Игры", callback_data="help_games"),
            InlineKeyboardButton(text="⚔️ Дуэли", callback_data="help_duel"),
        ],
        [
            InlineKeyboardButton(text="🎒 Предметы", callback_data="help_items"),
            InlineKeyboardButton(text="🧩 Квесты", callback_data="help_quests"),
        ],
        [
            InlineKeyboardButton(text="👤 Профиль", callback_data="help_profile"),
        ]
    ])


def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="help_main")]
    ])


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.reply(
        "📖 <b>ПОМОЩЬ ПО БОТУ</b>\n\nВыбери раздел 👇",
        reply_markup=help_kb(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "help_main")
async def help_main(call: CallbackQuery):
    await call.message.edit_text(
        "📖 <b>ПОМОЩЬ ПО БОТУ</b>\n\nВыбери раздел 👇",
        reply_markup=help_kb(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "help_rp")
async def help_rp(call: CallbackQuery):
    await call.message.edit_text(
        "🎭 <b>РП</b>\n\n"
        "• РП-действия работают ответом на сообщение\n"
        "• /create_rp — создать своё РП\n"
        "• /my_rp — мои команды\n"
        "• /delete_rp [слово] — удалить команду\n"
        "• /top_rp — топ кастомных РП\n",
        reply_markup=back_kb(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "help_economy")
async def help_economy(call: CallbackQuery):
    await call.message.edit_text(
        "💰 <b>Экономика</b>\n\n"
        "• /balance или /money — баланс\n"
        "• /daily — ежедневный бонус\n"
        "• /give @user [сумма] — перевод монет\n"
        "• /daily_bonus — бонус дня\n"
        "• /bonus_info — активный бонус\n",
        reply_markup=back_kb(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "help_games")
async def help_games(call: CallbackQuery):
    await call.message.edit_text(
        "🎰 <b>Игры</b>\n\n"
        "• /slots [сумма] — слот-автомат\n"
        "• /dice — кубик 1-6\n"
        "• /d20 — кубик 1-20\n"
        "• /coin — орёл/решка\n"
        "• /rps камень|ножницы|бумага — игра\n"
        "• /quiz — викторина\n",
        reply_markup=back_kb(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "help_duel")
async def help_duel(call: CallbackQuery):
    await call.message.edit_text(
        "⚔️ <b>Дуэли</b>\n\n"
        "• /duel @user [сумма] — вызвать на дуэль\n"
        "• /elo — твой рейтинг\n"
        "• /top_elo — топ по ELO\n",
        reply_markup=back_kb(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "help_items")
async def help_items(call: CallbackQuery):
    await call.message.edit_text(
        "🎒 <b>Предметы</b>\n\n"
        "• /shop — магазин\n"
        "• /buy [номер] — купить предмет\n"
        "• /inventory — инвентарь\n"
        "• /use [номер] — использовать предмет\n"
        "• /effects — активные эффекты\n",
        reply_markup=back_kb(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "help_quests")
async def help_quests(call: CallbackQuery):
    await call.message.edit_text(
        "🧩 <b>Квесты</b>\n\n"
        "• /quests — список квестов\n"
        "• /claim — забрать награды\n",
        reply_markup=back_kb(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "help_profile")
async def help_profile(call: CallbackQuery):
    await call.message.edit_text(
        "👤 <b>Профиль и статистика</b>\n\n"
        "• /profile [@user] — профиль\n"
        "• /leaderboard — лидерборд\n"
        "• /level — уровень\n"
        "• /rank — ранг\n"
        "• /achievements — достижения\n"
        "• /achievement [номер] — детали достижения\n",
        reply_markup=back_kb(),
        parse_mode="HTML"
    )
    await call.answer()
