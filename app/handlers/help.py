from aiogram import F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.shared import *


def help_kb() -> InlineKeyboardMarkup:
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
            InlineKeyboardButton(text="💍 Браки", callback_data="help_marriage"),
        ],
        [
            InlineKeyboardButton(text="🏅 Достижения", callback_data="help_achievements"),
            InlineKeyboardButton(text="🛠️ Админка", callback_data="help_admin"),
        ],
    ])


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="help_main")]
    ])


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.reply(
        "📖 <b>ПОМОЩЬ ПО БОТУ</b>

"
        "Выбери раздел ниже 👇",
        parse_mode="HTML",
        reply_markup=help_kb(),
    )


@router.callback_query(F.data == "help_main")
async def help_main(call: CallbackQuery):
    await call.message.edit_text(
        "📖 <b>ПОМОЩЬ ПО БОТУ</b>

Выбери раздел ниже 👇",
        parse_mode="HTML",
        reply_markup=help_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "help_rp")
async def help_rp(call: CallbackQuery):
    await call.message.edit_text(
        "🎭 <b>РП и кастомные команды</b>

"
        "• РП-действия работают <b>ответом на сообщение</b>
"
        "• /create_rp [слово] [текст] — создать своё РП
"
        "• /my_rp — мои кастомные РП
"
        "• /delete_rp [слово] — удалить РП
"
        "• /top_rp — топ кастомных РП

"
        "Примеры действий: обнять, поцеловать, погладить, укусить, дать пять",
        parse_mode="HTML",
        reply_markup=back_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "help_economy")
async def help_economy(call: CallbackQuery):
    await call.message.edit_text(
        "💰 <b>Экономика</b>

"
        "• /balance или /money — баланс
"
        "• /daily — ежедневная награда
"
        "• /give @user [сумма] — перевод монет
"
        "• /daily_bonus — активировать бонус дня
"
        "• /bonus_info — посмотреть активный бонус",
        parse_mode="HTML",
        reply_markup=back_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "help_games")
async def help_games(call: CallbackQuery):
    await call.message.edit_text(
        "🎰 <b>Игры</b>

"
        "• /slots [сумма] — слот-автомат
"
        "• /dice — кубик 1-6
"
        "• /d20 — кубик 1-20
"
        "• /coin — орёл/решка
"
        "• /rps камень|ножницы|бумага — игра с ботом
"
        "• /quiz — викторина",
        parse_mode="HTML",
        reply_markup=back_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "help_duel")
async def help_duel(call: CallbackQuery):
    await call.message.edit_text(
        "⚔️ <b>Дуэли</b>

"
        "• /duel @user [сумма] — вызвать на дуэль
"
        "• /elo — твой ELO рейтинг
"
        "• /top_elo — топ по ELO

"
        "В дуэлях помогают боевые предметы и активные эффекты.",
        parse_mode="HTML",
        reply_markup=back_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "help_items")
async def help_items(call: CallbackQuery):
    await call.message.edit_text(
        "🎒 <b>Предметы</b>

"
        "• /shop — магазин
"
        "• /buy [номер] — купить предмет
"
        "• /inventory — инвентарь
"
        "• /use [номер] — использовать предмет
"
        "• /effects — активные эффекты",
        parse_mode="HTML",
        reply_markup=back_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "help_quests")
async def help_quests(call: CallbackQuery):
    await call.message.edit_text(
        "🧩 <b>Квесты</b>

"
        "• /quests — ежедневные и недельные квесты
"
        "• /claim — забрать готовые награды

"
        "Квесты дают монеты, XP и иногда предметы.",
        parse_mode="HTML",
        reply_markup=back_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "help_profile")
async def help_profile(call: CallbackQuery):
    await call.message.edit_text(
        "👤 <b>Профиль и статистика</b>

"
        "• /profile [@user] — профиль пользователя
"
        "• /leaderboard — лидерборд
"
        "• /level — уровень и XP
"
        "• /rank — фурри-ранг
"
        "• /top_activity — топ по активности
"
        "• /top_rp_actions — топ по РП-действиям",
        parse_mode="HTML",
        reply_markup=back_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "help_marriage")
async def help_marriage(call: CallbackQuery):
    await call.message.edit_text(
        "💍 <b>Браки</b>

"
        "• предложить брак @user — сделать предложение
"
        "• /marry — информация о браке
"
        "• /divorce — развод
"
        "• /top_marriages — топ долгих браков",
        parse_mode="HTML",
        reply_markup=back_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "help_achievements")
async def help_achievements(call: CallbackQuery):
    await call.message.edit_text(
        "🏅 <b>Достижения</b>

"
        "• /achievements — список достижений
"
        "• /achievement [номер] — подробнее о достижении

"
        "Достижения дают монеты, XP и редкие награды.",
        parse_mode="HTML",
        reply_markup=back_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "help_admin")
async def help_admin(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Раздел только для администраторов", show_alert=True)
        return
    await call.message.edit_text(
        "🛠️ <b>Админ-команды</b>

"
        "• /admin_panel — админ-панель
"
        "• /backup — бэкап базы
"
        "• /broadcast — рассылка
"
        "• /add_money /remove_money — управление балансом
"
        "• /add_xp — выдать XP",
        parse_mode="HTML",
        reply_markup=back_kb(),
    )
    await call.answer()
