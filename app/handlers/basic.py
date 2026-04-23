from aiogram import F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.shared import *

# ─────────────────────────── /START ───────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    text = (
        "👋 Привет\\! Я — многофункциональный РП\\-бот\\!\n\n"
        "🎭 *РП\\-действия* — ответь на сообщение командой: _обнять_, _поцеловать_, _погладить_\\.\\.\\.\n"
        "🏆 *Уровни и XP* — /level, /leaderboard, /rank\n"
        "🎲 *Игры* — /dice, /d20, /coin, /rps, /slots, /duel, /quiz\n"
        "💰 *Экономика* — /balance, /daily, /give, /shop, /buy, /inventory\n"
        "💍 *Браки* — «Предложить брак @user», /marry, /divorce\n"
        "🏅 *Достижения* — /achievements\n"
        "📊 *Профиль* — /profile\n"
        "🎁 *Бонус дня* — /daily\\_bonus\n\n"
        "📋 Полный список: /help"
    )
    await message.reply(text, parse_mode="MarkdownV2")
    await check_achievements(message.from_user.id, message)
    

# ─────────────────────────── /LEVEL ───────────────────────────────

@router.message(Command("level"))
async def cmd_level(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    u = get_user(message.from_user.id)
    level = calc_level(u["xp"])
    xp_needed = xp_for_level(level + 1) - u["xp"]
    rank_name, rank_emoji = get_rank(level)
    await message.reply(
        f"🏆 <b>{message.from_user.full_name}</b>\n"
        f"Уровень: <b>{level}</b>\n"
        f"Ранг: {rank_emoji} <b>{rank_name}</b>\n"
        f"XP: <b>{u['xp']}</b>\n"
        f"До следующего уровня: <b>{xp_needed} XP</b>",
        parse_mode="HTML",
    )

# ─────────────────────────── /LEADERBOARD ─────────────────────────

def make_leaderboard_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏆 По уровню", callback_data="lb_xp"),
            InlineKeyboardButton(text="💰 По деньгам", callback_data="lb_money"),
        ],
        [
            InlineKeyboardButton(text="💍 По бракам", callback_data="lb_marriages"),
            InlineKeyboardButton(text="🦊 По рангу", callback_data="lb_rank"),
            InlineKeyboardButton(text="⚔️ По ELO", callback_data="lb_elo"),
        ]
    ])

@router.message(Command("leaderboard"))
async def cmd_leaderboard(message: Message):
    await _send_leaderboard(message, "lb_xp")

async def _send_leaderboard(target, mode: str):
    conn = get_conn()
    c = conn.cursor()
    if mode == "lb_xp":
        c.execute("SELECT user_id, username, xp, level FROM users ORDER BY xp DESC LIMIT 10")
        rows = c.fetchall()
        lines = ["🏆 <b>Топ по уровню:</b>"]
        for i, (uid, name, xp, lvl) in enumerate(rows, 1):
            crown = "👑 " if _has_item(uid, 12) else ""
            display_name = name or str(uid)
            mention = f"<a href='tg://user?id={uid}'>{display_name}</a>"
            lines.append(f"{i}. {crown}{mention} — Ур.{lvl} ({xp} XP)")
    elif mode == "lb_money":
        c.execute("SELECT user_id, username, balance FROM users ORDER BY balance DESC LIMIT 10")
        rows = c.fetchall()
        lines = ["💰 <b>Топ по монетам:</b>"]
        for i, (uid, name, bal) in enumerate(rows, 1):
            crown = "👑 " if _has_item(uid, 12) else ""
            display_name = name or str(uid)
            mention = f"<a href='tg://user?id={uid}'>{display_name}</a>"
            lines.append(f"{i}. {crown}{mention} — {bal} 🪙")
    elif mode == "lb_rank":
        c.execute("SELECT user_id, username, level FROM users ORDER BY level DESC LIMIT 10")
        rows = c.fetchall()
        lines = ["🦊 <b>Топ по рангу:</b>"]
        for i, (uid, name, lvl) in enumerate(rows, 1):
            rank_name, rank_emoji = get_rank(lvl)
            display_name = name or str(uid)
            mention = f"<a href='tg://user?id={uid}'>{display_name}</a>"
            lines.append(f"{i}. {mention} — {rank_emoji} {rank_name} (Ур.{lvl})")
    elif mode == "lb_elo":
        c.execute("""
            SELECT u.user_id, u.username, e.rating 
            FROM elo_ratings e 
            JOIN users u ON u.user_id = e.user_id 
            ORDER BY e.rating DESC LIMIT 10
        """)
        rows = c.fetchall()
        lines = ["⚔️ <b>Топ по ELO рейтингу:</b>"]
        for i, (uid, name, rating) in enumerate(rows, 1):
            display_name = name or str(uid)
            mention = f"<a href='tg://user?id={uid}'>{display_name}</a>"
            lines.append(f"{i}. {mention} — <b>{rating}</b> ({get_elo_rank(uid)})")
    else:  # lb_marriages
        c.execute(
            "SELECT u1.user_id, u1.username, u2.user_id, u2.username, m.married_since "
            "FROM marriages m "
            "JOIN users u1 ON u1.user_id=m.user1_id "
            "JOIN users u2 ON u2.user_id=m.user2_id "
            "ORDER BY m.married_since ASC LIMIT 10"
        )
        rows = c.fetchall()
        lines = ["💍 <b>Топ самых долгих браков:</b>"]
        for i, (uid1, n1, uid2, n2, ts) in enumerate(rows, 1):
            days = (int(time.time()) - ts) // 86400
            mention1 = f"<a href='tg://user?id={uid1}'>{n1 or str(uid1)}</a>"
            mention2 = f"<a href='tg://user?id={uid2}'>{n2 or str(uid2)}</a>"
            lines.append(f"{i}. {mention1} & {mention2} — {days} дн.")
    conn.close()
    text = "\n".join(lines)
    kb = make_leaderboard_kb()
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await target.reply(text, parse_mode="HTML", reply_markup=kb)

def _has_item(user_id: int, item_id: int) -> bool:
    return has_inventory_item(user_id, item_id)

@router.callback_query(F.data.in_({"lb_xp", "lb_money", "lb_marriages", "lb_rank", "lb_elo"}))
async def cb_leaderboard(call: CallbackQuery):
    await call.answer()
    await _send_leaderboard(call, call.data)

