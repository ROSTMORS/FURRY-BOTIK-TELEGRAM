from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from app.core import router

# ─────────────────── КНОПКИ ───────────────────

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


# ─────────────────── /help ───────────────────

@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 <b>ПОМОЩЬ ПО БОТУ</b>\n\n"
        "Выбери раздел ниже 👇",
        reply_markup=help_kb(),
        parse_mode="HTML"
    )


# ─────────────────── ОБРАБОТКА КНОПОК ───────────────────

@router.callback_query(F.data == "help_main")
async def help_main(call: CallbackQuery):
    await call.message.edit_text(
        "📖 <b>ПОМОЩЬ ПО БОТУ</b>\n\nВыбери раздел 👇",
        reply_markup=help_kb(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "help_rp")
async def help_rp(call: CallbackQuery):
    await call.message.edit_text(
        "🎭 <b>РП</b>\n\n"
        "• обнять — РП-действие\n"
        "• поцеловать — РП-действие\n"
        "• погладить — РП-действие\n"
        "• /create_rp — создать своё РП\n",
        reply_markup=back_kb(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "help_economy")
async def help_economy(call: CallbackQuery):
    await call.message.edit_text(
        "💰 <b>Экономика</b>\n\n"
        "• /balance — баланс\n"
        "• /daily — ежедневная награда\n"
        "• /give @user сумма — перевод\n",
        reply_markup=back_kb(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "help_games")
async def help_games(call: CallbackQuery):
    await call.message.edit_text(
        "🎰 <b>Игры</b>\n\n"
        "• /slots [ставка] — слот-автомат\n"
        "• /quiz — вопрос\n"
        "• /rps — камень/ножницы/бумага\n",
        reply_markup=back_kb(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "help_duel")
async def help_duel(call: CallbackQuery):
    await call.message.edit_text(
        "⚔️ <b>Дуэли</b>\n\n"
        "• /duel @user [ставка] — дуэль\n"
        "• /elo — рейтинг\n",
        reply_markup=back_kb(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "help_items")
async def help_items(call: CallbackQuery):
    await call.message.edit_text(
        "🎒 <b>Предметы</b>\n\n"
        "• /shop — магазин\n"
        "• /inventory — инвентарь\n"
        "• /use [id] — использовать\n",
        reply_markup=back_kb(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "help_quests")
async def help_quests(call: CallbackQuery):
    await call.message.edit_text(
        "🧩 <b>Квесты</b>\n\n"
        "• /quests — список\n"
        "• /claim — забрать награды\n",
        reply_markup=back_kb(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "help_profile")
async def help_profile(call: CallbackQuery):
    await call.message.edit_text(
        "👤 <b>Профиль</b>\n\n"
        "• /profile — твой профиль\n"
        "• /leaderboard — топ\n"
        "• /achievements — достижения\n",
        reply_markup=back_kb(),
        parse_mode="HTML"
    )
