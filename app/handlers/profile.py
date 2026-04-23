from datetime import datetime, timezone
import time

from aiogram import F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto

from app.core import router, bot
from app.db import get_conn
from app.shared import (
    get_user,
    get_user_stats,
    calc_level,
    get_elo,
    get_elo_rank,
    get_marriage,
    get_username_by_id,
    get_rank,
)


def profile_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏅 Достижения", callback_data=f"profile_achievements_{user_id}"),
            InlineKeyboardButton(text="🎭 Мои команды", callback_data=f"profile_commands_{user_id}"),
        ]
    ])


def back_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"profile_back_{user_id}")]
    ])


def _safe_name(name: str | None, fallback: str) -> str:
    value = (name or "").strip()
    return value if value else fallback


def _format_number(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _xp_progress_bar(current_xp: int, level: int, length: int = 10) -> str:
    current_level_xp = (level - 1) ** 2 * 100
    next_level_xp = level ** 2 * 100
    span = max(1, next_level_xp - current_level_xp)
    progress = max(0, min(current_xp - current_level_xp, span))
    filled = round((progress / span) * length)
    bar = "█" * filled + "░" * (length - filled)
    percent = int((progress / span) * 100)
    return f"[{bar}] {percent}%"


def _count_achievements(user_id: int) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM achievements WHERE user_id=?", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count


def _count_inventory_items(user_id: int) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COALESCE(SUM(amount), 0) FROM inventory WHERE user_id=?", (user_id,))
    count = c.fetchone()[0] or 0
    conn.close()
    return count


def _get_custom_commands(user_id: int) -> list[tuple[str, int]]:
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT keyword, uses_count FROM custom_rp WHERE user_id=? ORDER BY uses_count DESC, keyword ASC",
        (user_id,),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def _get_active_effects(user_id: int) -> list[str]:
    conn = get_conn()
    c = conn.cursor()

    effects: list[str] = []

    # Универсальные эффекты из новой таблицы
    try:
        now = int(time.time())
        c.execute(
            "SELECT effect_type, value, stacks, expires_at FROM active_effects "
            "WHERE user_id=? ORDER BY expires_at ASC",
            (user_id,),
        )
        for effect_type, value, stacks, expires_at in c.fetchall():
            left_text = ""
            if expires_at:
                remaining = max(0, expires_at - now)
                if remaining > 0:
                    mins = remaining // 60
                    left_text = f" ({mins} мин.)" if mins else " (<1 мин.)"

            if effect_type == "slots_luck":
                effects.append(f"🍀 Удача в слотах: +{value}% ×{stacks}{left_text}")
            elif effect_type == "duel_initiative":
                effects.append(f"🎯 Инициатива дуэли: +{value}{left_text}")
            elif effect_type == "duel_damage":
                effects.append(f"🔥 Урон в дуэли: +{value}{left_text}")
            elif effect_type == "duel_shield":
                effects.append(f"🛡️ Щит дуэли: -{value}% урона{left_text}")
            elif effect_type == "duel_heal":
                effects.append(f"🩹 Лечение дуэли: +{value} HP{left_text}")
            else:
                effects.append(f"✨ {effect_type}: {value} ×{stacks}{left_text}")
    except Exception:
        pass

    # Старые эффекты для совместимости
    try:
        c.execute(
            "SELECT lucky_slots, magic_hat, dragon_egg FROM item_effects WHERE user_id=?",
            (user_id,),
        )
        row = c.fetchone()
        if row:
            lucky_slots, magic_hat, dragon_egg = row
            if lucky_slots:
                effects.append("🍀 Клевер: усиление слотов")
            if magic_hat:
                effects.append("🎩 Магическая шляпа активна")
            if dragon_egg:
                effects.append("🐉 Яйцо дракона активно")
    except Exception:
        pass

    conn.close()
    return effects[:5]


def build_profile_text(user_id: int, viewer_id: int | None = None) -> str | None:
    u = get_user(user_id)
    if not u:
        return None

    stats = get_user_stats(user_id)
    level = calc_level(u["xp"])
    rank_name, rank_emoji = get_rank(level)
    elo = get_elo(user_id)
    elo_rank = get_elo_rank(user_id)
    ach_count = _count_achievements(user_id)
    item_count = _count_inventory_items(user_id)
    effects = _get_active_effects(user_id)

    show_balance = viewer_id is None or viewer_id == user_id
    display_name = _safe_name(u.get("username"), str(user_id))
    mention = f"<a href='tg://user?id={user_id}'>{display_name}</a>"

    marriage_info = "💔 <b>Брак:</b> нет"
    m = get_marriage(user_id)
    if m:
        partner_id = m["user2_id"] if m["user1_id"] == user_id else m["user1_id"]
        partner_name = _safe_name(get_username_by_id(partner_id), str(partner_id))
        partner_mention = f"<a href='tg://user?id={partner_id}'>{partner_name}</a>"
        days_married = (int(time.time()) - m["married_since"]) // 86400
        marriage_info = f"💍 <b>Брак:</b> {partner_mention} ({days_married} дн.)"

    lines = [
        "🦊 <b>ПРОФИЛЬ ИГРОКА</b>",
        "",
        f"⭐ <b>{mention}</b>",
        "",
        "━━━━━━━━━━━━━━━",
        f"🏆 <b>Уровень:</b> {level}",
        f"✨ <b>Опыт:</b> {_format_number(u['xp'])} XP",
        f"📈 <b>Прогресс:</b> {_xp_progress_bar(u['xp'], level)}",
        f"{rank_emoji} <b>Ранг:</b> {rank_name}",
        "",
        "━━━━━━━━━━━━━━━",
    ]

    if show_balance:
        lines.append(f"💰 <b>Баланс:</b> {_format_number(u['balance'])} 🪙")
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━")

    lines.extend([
        "⚔️ <b>Боевые показатели</b>",
        f"• ELO: <b>{elo}</b> ({elo_rank})",
        f"• Дуэлей выиграно: <b>{stats['total_duels_won']}</b>",
        "",
        "━━━━━━━━━━━━━━━",
        "📊 <b>Активность</b>",
        f"• 🎭 РП-действий: <b>{stats['total_rp_actions']}</b>",
        f"• 🎲 Игр сыграно: <b>{stats['total_games_played']}</b>",
        f"• 🎁 Монет подарено: <b>{_format_number(stats['total_money_given'])}</b>",
        f"• ❓ Правильных ответов: <b>{stats['total_quiz_correct']}</b>",
        "",
        "━━━━━━━━━━━━━━━",
        marriage_info,
        "",
        "━━━━━━━━━━━━━━━",
        f"🎒 <b>Предметов в инвентаре:</b> {item_count}",
    ])

    if effects:
        lines.append("✨ <b>Активные эффекты:</b>")
        for effect in effects:
            lines.append(f"• {effect}")
    else:
        lines.append("✨ <b>Активные эффекты:</b> нет")

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━",
        f"🏅 <b>Достижения:</b> {ach_count} / 12",
    ])

    return "\n".join(lines)


async def _get_profile_photo_file_id(user_id: int) -> str | None:
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if photos.total_count > 0 and photos.photos and photos.photos[0]:
            return photos.photos[0][-1].file_id
    except Exception:
        return None
    return None


async def _send_profile_message(message: Message, target_id: int, viewer_id: int | None = None):
    text = build_profile_text(target_id, viewer_id=viewer_id)
    if not text:
        await message.reply("❌ Пользователь не найден.")
        return

    kb = profile_kb(target_id)
    file_id = await _get_profile_photo_file_id(target_id)

    if file_id:
        try:
            await message.reply_photo(
                photo=file_id,
                caption=text,
                reply_markup=kb,
                parse_mode="HTML",
            )
            return
        except Exception:
            pass

    await message.reply(text, reply_markup=kb, parse_mode="HTML")


async def _edit_profile_message(call: CallbackQuery, text: str, user_id: int, viewer_id: int | None = None):
    kb = profile_kb(user_id)
    msg = call.message

    if msg.photo:
        file_id = await _get_profile_photo_file_id(user_id)
        if file_id:
            try:
                await msg.edit_media(
                    media=InputMediaPhoto(media=file_id, caption=text, parse_mode="HTML"),
                    reply_markup=kb,
                )
                return
            except Exception:
                pass
        try:
            await msg.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
            return
        except Exception:
            pass

    await msg.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.message(Command("profile"))
async def cmd_profile(message: Message):
    args = message.text.split()
    target_id = message.from_user.id

    if len(args) > 1 and args[1].startswith("@"):
        username = args[1].lstrip("@")
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE username=?", (username,))
        row = c.fetchone()
        conn.close()
        if not row:
            await message.reply("❌ Пользователь не найден.")
            return
        target_id = row[0]

    await _send_profile_message(message, target_id, viewer_id=message.from_user.id)


@router.callback_query(F.data.startswith("profile_back_"))
async def profile_back(call: CallbackQuery):
    target_id = int(call.data.split("_")[2])
    text = build_profile_text(target_id, viewer_id=call.from_user.id)
    if not text:
        await call.answer("Профиль не найден.", show_alert=True)
        return
    await _edit_profile_message(call, text, target_id, viewer_id=call.from_user.id)
    await call.answer()


@router.callback_query(F.data.startswith("profile_achievements_"))
async def profile_achievements(call: CallbackQuery):
    target_id = int(call.data.split("_")[2])

    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT achievement_id FROM achievements WHERE user_id=?", (target_id,))
    earned = {row[0] for row in c.fetchall()}
    conn.close()

    achievements = {
        1:  ("🎭", "Душа компании"),
        2:  ("💑", "Семьянин"),
        3:  ("🍀", "Счастливчик"),
        4:  ("🎓", "Эрудит"),
        5:  ("🐉", "Властелин драконов"),
        6:  ("💰", "Богатей"),
        7:  ("🎁", "Щедрая душа"),
        8:  ("🎰", "Азартный игрок"),
        9:  ("🌟", "Любимчик фортуны"),
        10: ("⚔️", "Силач"),
        11: ("✍️", "Мастер РП"),
        12: ("🦊", "Истинный фурри"),
    }

    lines = ["🏅 <b>ДОСТИЖЕНИЯ</b>", ""]
    for ach_id, (icon, name) in achievements.items():
        status = "✅" if ach_id in earned else "🔒"
        lines.append(f"{status} {icon} <b>{name}</b>")

    text = "\n".join(lines)
    msg = call.message

    if msg.photo:
        try:
            await msg.edit_caption(caption=text, reply_markup=back_kb(target_id), parse_mode="HTML")
        except Exception:
            await msg.edit_text(text, reply_markup=back_kb(target_id), parse_mode="HTML")
    else:
        await msg.edit_text(text, reply_markup=back_kb(target_id), parse_mode="HTML")

    await call.answer()


@router.callback_query(F.data.startswith("profile_commands_"))
async def profile_commands(call: CallbackQuery):
    target_id = int(call.data.split("_")[2])
    commands = _get_custom_commands(target_id)

    if not commands:
        text = "🎭 <b>МОИ КОМАНДЫ</b>\n\nУ пользователя нет кастомных РП-команд."
    else:
        lines = [f"🎭 <b>МОИ КОМАНДЫ</b>\n"]
        for keyword, uses in commands[:15]:
            lines.append(f"• <b>{keyword}</b> — {uses} исп.")
        text = "\n".join(lines)

    msg = call.message
    if msg.photo:
        try:
            await msg.edit_caption(caption=text, reply_markup=back_kb(target_id), parse_mode="HTML")
        except Exception:
            await msg.edit_text(text, reply_markup=back_kb(target_id), parse_mode="HTML")
    else:
        await msg.edit_text(text, reply_markup=back_kb(target_id), parse_mode="HTML")

    await call.answer()
