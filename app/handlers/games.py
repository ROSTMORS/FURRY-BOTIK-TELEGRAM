from aiogram import F
from aiogram.filters import Command, CommandStart
from collections import Counter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.shared import *
import html
from app.quiz_bank import QUIZ_QUESTIONS_2, QUIZ_DIFFICULTY_META

# ───────────────────────── МИНИ-ИГРЫ ──────────────────────────────

@router.message(Command("dice"))
async def cmd_dice(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    await message.reply(f"🎲 Выпало: <b>{random.randint(1, 6)}</b>!", parse_mode="HTML")

@router.message(Command("d20"))
async def cmd_d20(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    r = random.randint(1, 20)
    suffix = " 🌟 <b>КРИТ!</b>" if r == 20 else (" 💀 <b>ПРОВАЛ!</b>" if r == 1 else "")
    await message.reply(f"🎲 D20: <b>{r}</b>{suffix}", parse_mode="HTML")

@router.message(Command("coin"))
async def cmd_coin(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    result = random.choice(["🦅 Орёл", "✍️ Решка"])
    await message.reply(f"🪙 <b>{result}</b>!", parse_mode="HTML")

@router.message(Command("rps"))
async def cmd_rps(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or args[1].lower() not in ("камень", "ножницы", "бумага"):
        await message.reply("✋ Использование: /rps [камень|ножницы|бумага]")
        return
    choices = ["камень", "ножницы", "бумага"]
    emojis = {"камень": "🪨", "ножницы": "✂️", "бумага": "📄"}
    wins = {"камень": "ножницы", "ножницы": "бумага", "бумага": "камень"}
    user_choice = args[1].lower()
    bot_choice = random.choice(choices)

    # Статистика: игра сыграна
    stat_increment(message.from_user.id, "total_games_played")
    update_quest_progress(message.from_user.id, "play_game", 1)

    if user_choice == bot_choice:
        result, extra = "🤝 Ничья!", "+5 XP, +5 🪙"
        xp = apply_xp_bonus(message.from_user.id, 5)
        add_xp(message.from_user.id, xp); add_balance(message.from_user.id, 5)
    elif wins[user_choice] == bot_choice:
        result, extra = "🎉 Вы победили!", "+15 XP, +20 🪙"
        xp = apply_xp_bonus(message.from_user.id, 15)
        add_xp(message.from_user.id, xp); add_balance(message.from_user.id, 20)
    else:
        result, extra = "😔 Бот победил!", ""
    await message.reply(
        f"Вы: {emojis[user_choice]} {user_choice}\nБот: {emojis[bot_choice]} {bot_choice}\n\n<b>{result}</b> {extra}",
        parse_mode="HTML",
    )
    await check_achievements(message.from_user.id, message)


SLOT_SYMBOLS = {
    "🍒": {"weight": 22, "pair": 1.50, "triple": 3.10, "label": "Вишни"},
    "🍋": {"weight": 22, "pair": 1.50, "triple": 3.10, "label": "Лимоны"},
    "🍊": {"weight": 22, "pair": 1.50, "triple": 3.10, "label": "Апельсины"},
    "🍇": {"weight": 22, "pair": 1.50, "triple": 3.10, "label": "Виноград"},
    "⭐": {"weight": 10, "pair": 2.00, "triple": 4.80, "label": "Звёзды"},
    "🍀": {"weight": 6,  "pair": 2.50, "triple": 6.20, "label": "Клевер"},
    "💎": {"weight": 2,  "pair": 3.00, "triple": 8.00, "label": "Алмазы"},
}

COMMON_FRUIT_SYMBOLS = {"🍒", "🍋", "🍊", "🍇"}

SLOT_SESSION_TIMEOUT = 180
SLOT_SPIN_COOLDOWN = 2.0
SLOT_MIN_BET = 10
SLOT_SESSIONS: dict[tuple[int, int], dict] = {}
SLOT_BET_INPUT: dict[tuple[int, int], bool] = {}


def _spin_slot_symbols() -> list[str]:
    population = list(SLOT_SYMBOLS.keys())
    weights = [SLOT_SYMBOLS[s]["weight"] for s in population]
    return random.choices(population, weights=weights, k=3)


def _soften_common_fruit_pairs(symbols: list[str]) -> list[str]:
    counts = Counter(symbols)
    pair_symbol = next((sym for sym, count in counts.items() if count == 2), None)
    if not pair_symbol or pair_symbol not in COMMON_FRUIT_SYMBOLS:
        return symbols

    # Обычные фруктовые пары не должны падать слишком часто.
    # Иногда ломаем такую пару мягким рероллом одного из двух совпавших символов.
    if random.random() >= 0.35:
        return symbols

    population = [sym for sym in SLOT_SYMBOLS.keys() if sym != pair_symbol]
    weights = [SLOT_SYMBOLS[sym]["weight"] for sym in population]
    pair_indexes = [i for i, sym in enumerate(symbols) if sym == pair_symbol]
    reroll_index = random.choice(pair_indexes)
    symbols = symbols[:]
    symbols[reroll_index] = random.choices(population, weights=weights, k=1)[0]
    return symbols


def _evaluate_slots(symbols: list[str]) -> dict:
    counts = Counter(symbols)
    most_symbol, most_count = counts.most_common(1)[0]

    if most_count == 3:
        multiplier = SLOT_SYMBOLS[most_symbol]["triple"]
        return {
            "win": True,
            "kind": "triple",
            "symbol": most_symbol,
            "multiplier": multiplier,
            "title": "💥 ДЖЕКПОТ!" if most_symbol == "💎" else "🎉 Большой выигрыш!",
            "detail": f"Три одинаковых: {SLOT_SYMBOLS[most_symbol]['label']}",
            "xp": 22 if most_symbol == "💎" else 18 if most_symbol in {"🍀", "⭐"} else 14,
        }

    if most_count == 2:
        pair_symbol = next(sym for sym, count in counts.items() if count == 2)
        multiplier = SLOT_SYMBOLS[pair_symbol]["pair"]
        clover_bonus = False
        if "🍀" in counts and pair_symbol != "🍀":
            multiplier += 0.20
            clover_bonus = True
        return {
            "win": True,
            "kind": "pair",
            "symbol": pair_symbol,
            "multiplier": multiplier,
            "title": "✨ Неплохо!",
            "detail": f"Совпало 2 символа: {SLOT_SYMBOLS[pair_symbol]['label']}" + (" + бонус клевера" if clover_bonus else ""),
            "xp": 8 if pair_symbol in {"⭐", "🍀", "💎"} else 5,
        }

    if counts.get("🍀", 0) >= 2:
        return {
            "win": True,
            "kind": "lucky_save",
            "symbol": "🍀",
            "multiplier": 1.10,
            "title": "🍀 Удачное спасение!",
            "detail": "Два клевера вернули часть ставки",
            "xp": 3,
        }

    return {
        "win": False,
        "kind": "lose",
        "symbol": None,
        "multiplier": 0.0,
        "title": "😔 Не повезло",
        "detail": "Комбинация ничего не дала",
        "xp": 0,
    }


def _slots_key(chat_id: int, user_id: int) -> tuple[int, int]:
    return (chat_id, user_id)


def _slots_base_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎰 Крутить ещё", callback_data="slots_spin"),
            InlineKeyboardButton(text="💰 Сменить ставку", callback_data="slots_bet"),
        ],
        [
            InlineKeyboardButton(text="❌ Закрыть", callback_data="slots_close"),
        ],
    ])


def _slots_closed_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⛔ Автомат закрыт", callback_data="slots_dead")]
    ])


def _render_slots_board(symbols: list[str]) -> str:
    a, b, c = symbols
    return f"<b>[ {a} | {b} | {c} ]</b>"


def _slots_luck_info(uid: int) -> tuple[float, list[str], float]:
    passive_lucky = 0.10 if has_inventory_item(uid, 8) else 0.0
    daily_lucky = 0.20 if get_active_bonus(uid) == "lucky_slots" else 0.0
    temp_slots_bonus = float(get_effect_value(uid, "slots_bonus") or 0.0)
    total_luck = passive_lucky + daily_lucky + temp_slots_bonus
    luck_parts = []
    if passive_lucky:
        luck_parts.append("клевер +10%")
    if daily_lucky:
        luck_parts.append("бонус дня +20%")
    if temp_slots_bonus:
        luck_parts.append(f"эффект предмета +{int(temp_slots_bonus * 100)}%")
    return total_luck, luck_parts, temp_slots_bonus


def _slots_expired(session: dict) -> bool:
    return time.time() > session["expires_at"]


def _render_slots_text(uid: int, bet: int, symbols: list[str], result_text: str, status: str = "") -> str:
    user = get_user(uid)
    total_luck, luck_parts, _ = _slots_luck_info(uid)
    luck_line = f"\n🍀 Удача: <b>{', '.join(luck_parts)}</b>" if luck_parts else ""
    status_line = f"{status}\n\n" if status else ""
    return (
        "🎰 <b>СЛОТ-АВТОМАТ</b>\n\n"
        f"{_render_slots_board(symbols)}\n\n"
        f"💰 Ставка: <b>{bet} 🪙</b>\n"
        f"💳 Баланс: <b>{user['balance']} 🪙</b>{luck_line}\n\n"
        f"{status_line}{result_text}"
    )


def _create_slot_session(chat_id: int, user_id: int, bet: int, message_id: int) -> dict:
    session = {
        "chat_id": chat_id,
        "user_id": user_id,
        "bet": bet,
        "message_id": message_id,
        "last_spin": 0.0,
        "expires_at": time.time() + SLOT_SESSION_TIMEOUT,
        "symbols": ["❔", "❔", "❔"],
        "last_text": "Нажми <b>🎰 Крутить ещё</b>, чтобы начать.",
    }
    SLOT_SESSIONS[_slots_key(chat_id, user_id)] = session
    return session


def _close_slot_session(chat_id: int, user_id: int):
    SLOT_SESSIONS.pop(_slots_key(chat_id, user_id), None)
    SLOT_BET_INPUT.pop(_slots_key(chat_id, user_id), None)


async def _safe_edit_slots_message(message: Message, text: str, markup):
    try:
        await message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception:
        await message.edit_text(text, reply_markup=markup)


async def _run_slots_spin(session: dict) -> tuple[list[str], str]:
    uid = session["user_id"]
    bet = session["bet"]
    user = get_user(uid)

    free_bet = get_active_bonus(uid) == "free_slots"
    if free_bet:
        bet_note = "🎁 Бесплатная ставка дня"
        conn = get_conn(); c = conn.cursor()
        c.execute(
            "UPDATE daily_bonus_log SET bonus_type='free_slots_used' WHERE user_id=? AND bonus_date=?",
            (uid, get_today_str()),
        )
        conn.commit(); conn.close()
    else:
        if user["balance"] < bet:
            return session["symbols"], "❌ Недостаточно монет для этой ставки."
        bet_note = "💸 Ставка принята"
        add_balance(uid, -bet)

    total_luck, _, temp_slots_bonus = _slots_luck_info(uid)
    symbols = _spin_slot_symbols()
    symbols = _soften_common_fruit_pairs(symbols)
    result = _evaluate_slots(symbols)
    luck_used = False

    if not result["win"] and total_luck > 0 and random.random() < min(total_luck, 0.30):
        symbols[2] = random.choice([symbols[0], symbols[1]])
        symbols = _soften_common_fruit_pairs(symbols)
        result = _evaluate_slots(symbols)
        luck_used = result["win"]

    if temp_slots_bonus:
        consume_effects(uid, "slots_bonus", 1)

    stat_increment(uid, "total_games_played")
    update_quest_progress(uid, "play_game", 1)

    multiplier = result["multiplier"]
    payout = int(round(bet * multiplier))
    net = payout if free_bet else payout - bet

    lines = [bet_note, "", result["title"], result["detail"]]

    if result["win"]:
        if payout > 0:
            add_balance(uid, payout)
        xp = apply_xp_bonus(uid, result["xp"])
        if xp > 0:
            add_xp(uid, xp)
        significant_win = multiplier >= 2.0
        slots_streak = record_slots_result(uid, significant_win)

        lines.append(f"💵 Возвращено на баланс: <b>{payout} 🪙</b>")
        if free_bet:
            lines.append(f"📈 Чистая прибыль: <b>+{payout} 🪙</b>")
        else:
            sign = "+" if net >= 0 else ""
            lines.append(f"📈 Чистая прибыль: <b>{sign}{net} 🪙</b>")
        if xp > 0:
            lines.append(f"⭐ Опыт: <b>+{xp} XP</b>")
        if luck_used:
            lines.append("🍀 Удача дотянула барабан до выигрыша")

        if significant_win and slots_streak >= 3 and not has_achievement(uid, 9):
            if grant_achievement(uid, 9):
                lines.append("🏅 Получено достижение: <b>Любимчик фортуны</b>")
    else:
        record_slots_result(uid, False)
        lines.append(f"📉 Потеряно: <b>{bet} 🪙</b>")

    return symbols, "\n".join(lines)


@router.message(Command("slots"))
async def cmd_slots(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    uid = message.from_user.id
    chat_id = message.chat.id
    key = _slots_key(chat_id, uid)
    args = message.text.split()

    if key in SLOT_SESSIONS and not _slots_expired(SLOT_SESSIONS[key]):
        await message.reply("🎰 У тебя уже открыт слот-автомат в этом чате.")
        return

    free_bet = get_active_bonus(uid) == "free_slots"
    if len(args) < 2 or not args[1].isdigit():
        if free_bet:
            bet = 50
        else:
            await message.reply("🎰 Использование: /slots [сумма] (мин. 10)")
            return
    else:
        bet = int(args[1])

    if bet < SLOT_MIN_BET:
        await message.reply(f"❌ Минимальная ставка — {SLOT_MIN_BET} монет.")
        return

    user = get_user(uid)
    if not free_bet and user["balance"] < bet:
        await message.reply("❌ Недостаточно монет!")
        return

    sent = await message.reply(
        _render_slots_text(uid, bet, ["❔", "❔", "❔"], "Нажми <b>🎰 Крутить ещё</b>, чтобы начать."),
        parse_mode="HTML",
        reply_markup=_slots_base_kb(),
    )
    _create_slot_session(chat_id, uid, bet, sent.message_id)


@router.callback_query(F.data.in_({"slots_spin", "slots_bet", "slots_close", "slots_dead"}))
async def cb_slots_controls(call: CallbackQuery):
    uid = call.from_user.id
    chat_id = call.message.chat.id
    key = _slots_key(chat_id, uid)
    session = SLOT_SESSIONS.get(key)

    if call.data == "slots_dead":
        await call.answer()
        return

    if not session or session["message_id"] != call.message.message_id:
        await call.answer("Это не твой слот-автомат.", show_alert=True)
        return

    if session["user_id"] != uid:
        await call.answer("Это не твой слот-автомат.", show_alert=True)
        return

    if _slots_expired(session):
        await _safe_edit_slots_message(
            call.message,
            _render_slots_text(uid, session["bet"], session["symbols"], "⛔ Автомат закрыт по таймауту."),
            _slots_closed_kb(),
        )
        _close_slot_session(chat_id, uid)
        await call.answer("Автомат уже закрылся.")
        return

    session["expires_at"] = time.time() + SLOT_SESSION_TIMEOUT

    if call.data == "slots_close":
        await _safe_edit_slots_message(
            call.message,
            _render_slots_text(uid, session["bet"], session["symbols"], "❌ Автомат закрыт."),
            _slots_closed_kb(),
        )
        _close_slot_session(chat_id, uid)
        await call.answer("Закрыто.")
        return

    if call.data == "slots_bet":
        SLOT_BET_INPUT[key] = True
        await call.answer("Жду новую ставку числом.", show_alert=True)
        try:
            await call.message.reply("💰 Введи новую ставку числом. Минимум — 10.")
        except Exception:
            pass
        return

    now = time.time()
    if now - session["last_spin"] < SLOT_SPIN_COOLDOWN:
        wait_left = max(1, int(round(SLOT_SPIN_COOLDOWN - (now - session["last_spin"]))))
        await call.answer(f"Подожди {wait_left} сек.", show_alert=True)
        return

    session["last_spin"] = now
    symbols, result_text = await _run_slots_spin(session)
    session["symbols"] = symbols
    session["last_text"] = result_text
    await _safe_edit_slots_message(
        call.message,
        _render_slots_text(uid, session["bet"], symbols, result_text),
        _slots_base_kb(),
    )
    await call.answer()


@router.message(lambda message: message.text and message.text.isdigit())
async def slots_bet_input_handler(message: Message):
    uid = message.from_user.id
    chat_id = message.chat.id
    key = _slots_key(chat_id, uid)

    if key not in SLOT_BET_INPUT:
        return

    session = SLOT_SESSIONS.get(key)
    SLOT_BET_INPUT.pop(key, None)

    if not session:
        await message.reply("⛔ Слот-автомат уже закрыт.")
        return

    if _slots_expired(session):
        _close_slot_session(chat_id, uid)
        await message.reply("⛔ Слот-автомат уже закрылся по таймауту.")
        return

    bet = int(message.text)
    if bet < SLOT_MIN_BET:
        await message.reply(f"❌ Минимальная ставка — {SLOT_MIN_BET} монет.")
        return

    user = get_user(uid)
    free_bet = get_active_bonus(uid) == "free_slots"
    if not free_bet and user["balance"] < bet:
        await message.reply("❌ Недостаточно монет для такой ставки.")
        return

    session["bet"] = bet
    session["expires_at"] = time.time() + SLOT_SESSION_TIMEOUT
    await message.reply(f"✅ Ставка обновлена: <b>{bet} 🪙</b>", parse_mode="HTML")
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=session["message_id"],
            text=_render_slots_text(uid, bet, session["symbols"], "Ставка обновлена. Нажми <b>🎰 Крутить ещё</b>."),
            parse_mode="HTML",
            reply_markup=_slots_base_kb(),
        )
    except Exception:
        pass
    return


DUEL_SESSIONS: dict[str, dict] = {}


def _duel_session_id(challenger_id: int, target_id: int, message_id: int) -> str:
    return f"{challenger_id}_{target_id}_{message_id}"


def _duel_kb(session_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚔️ Атака", callback_data=f"d2_{session_id}_atk"),
            InlineKeyboardButton(text="🛡️ Защита", callback_data=f"d2_{session_id}_def"),
        ],
        [InlineKeyboardButton(text="💥 Риск", callback_data=f"d2_{session_id}_risk")],
    ])


def _duel_name(uid: int) -> str:
    return get_username_by_id(uid) or str(uid)


def _render_duel(session: dict) -> str:
    p1 = session["players"][session["order"][0]]
    p2 = session["players"][session["order"][1]]
    current_id = session["turn"]
    current_name = _duel_name(current_id)
    log_lines = session["log"][-8:]
    body = "\n".join(log_lines) if log_lines else "Бой начинается!"
    p1_extra = (f" | 🔥+{p1['damage_bonus']}" if p1['damage_bonus'] else "") + (f" | 🛡️{int(p1['defense_bonus']*100)}%" if p1['defense_bonus'] else "")
    p2_extra = (f" | 🔥+{p2['damage_bonus']}" if p2['damage_bonus'] else "") + (f" | 🛡️{int(p2['defense_bonus']*100)}%" if p2['defense_bonus'] else "")
    return (
        f"⚔️ <b>Дуэль 2.0</b>\n"
        f"💰 Ставка: <b>{session['bet']} 🪙</b>\n\n"
        f"<b>{_duel_name(p1['id'])}</b>: ❤️ {p1['hp']}/{p1['max_hp']}{p1_extra}\n"
        f"<b>{_duel_name(p2['id'])}</b>: ❤️ {p2['hp']}/{p2['max_hp']}{p2_extra}\n\n"
        f"🎯 Ход: <b>{current_name}</b>\n\n"
        f"{body}"
    )


def _start_duel_session(challenger_id: int, target_id: int, amount: int, message_id: int) -> dict:
    c_init = int(get_effect_value(challenger_id, "duel_roll_bonus"))
    t_init = int(get_effect_value(target_id, "duel_roll_bonus"))
    c_hp_bonus = int(get_effect_value(challenger_id, "duel_hp_bonus"))
    t_hp_bonus = int(get_effect_value(target_id, "duel_hp_bonus"))
    c_dmg_bonus = int(get_effect_value(challenger_id, "duel_damage_bonus"))
    t_dmg_bonus = int(get_effect_value(target_id, "duel_damage_bonus"))
    c_def_bonus = float(get_effect_value(challenger_id, "duel_defense_bonus"))
    t_def_bonus = float(get_effect_value(target_id, "duel_defense_bonus"))

    if c_init:
        consume_effects(challenger_id, "duel_roll_bonus", 1)
    if t_init:
        consume_effects(target_id, "duel_roll_bonus", 1)
    if c_hp_bonus:
        consume_effects(challenger_id, "duel_hp_bonus", 1)
    if t_hp_bonus:
        consume_effects(target_id, "duel_hp_bonus", 1)
    if c_dmg_bonus:
        consume_effects(challenger_id, "duel_damage_bonus", 1)
    if t_dmg_bonus:
        consume_effects(target_id, "duel_damage_bonus", 1)
    if c_def_bonus:
        consume_effects(challenger_id, "duel_defense_bonus", 1)
    if t_def_bonus:
        consume_effects(target_id, "duel_defense_bonus", 1)

    c_roll = random.randint(1, 20) + c_init
    t_roll = random.randint(1, 20) + t_init
    if c_roll == t_roll:
        c_roll += 1

    first = challenger_id if c_roll > t_roll else target_id
    session_id = _duel_session_id(challenger_id, target_id, message_id)
    session = {
        "id": session_id,
        "bet": amount,
        "order": [challenger_id, target_id],
        "turn": first,
        "players": {
            challenger_id: {
                "id": challenger_id,
                "hp": 100 + c_hp_bonus,
                "max_hp": 100 + c_hp_bonus,
                "guard": False,
                "damage_bonus": c_dmg_bonus,
                "defense_bonus": c_def_bonus,
            },
            target_id: {
                "id": target_id,
                "hp": 100 + t_hp_bonus,
                "max_hp": 100 + t_hp_bonus,
                "guard": False,
                "damage_bonus": t_dmg_bonus,
                "defense_bonus": t_def_bonus,
            },
        },
        "log": [
            f"🎲 Инициатива: {_duel_name(challenger_id)} {c_roll} vs {_duel_name(target_id)} {t_roll}",
            f"🚩 Первым ходит <b>{_duel_name(first)}</b>",
        ],
    }
    if c_hp_bonus:
        session["log"].append(f"🩹 {_duel_name(challenger_id)} получает +{c_hp_bonus} HP перед боем")
    if t_hp_bonus:
        session["log"].append(f"🩹 {_duel_name(target_id)} получает +{t_hp_bonus} HP перед боем")
    if c_dmg_bonus:
        session["log"].append(f"🔥 {_duel_name(challenger_id)} усиливает атаку на +{c_dmg_bonus}")
    if t_dmg_bonus:
        session["log"].append(f"🔥 {_duel_name(target_id)} усиливает атаку на +{t_dmg_bonus}")
    if c_def_bonus:
        session["log"].append(f"🛡️ {_duel_name(challenger_id)} получает {int(c_def_bonus * 100)}% защиты")
    if t_def_bonus:
        session["log"].append(f"🛡️ {_duel_name(target_id)} получает {int(t_def_bonus * 100)}% защиты")
    DUEL_SESSIONS[session_id] = session
    return session


def _apply_duel_action(session: dict, actor_id: int, action: str) -> tuple[bool, int | None]:
    defender_id = [uid for uid in session["players"] if uid != actor_id][0]
    actor = session["players"][actor_id]
    defender = session["players"][defender_id]
    actor_name = _duel_name(actor_id)
    defender_name = _duel_name(defender_id)

    if action == "def":
        actor["guard"] = True
        session["log"].append(f"🛡️ <b>{actor_name}</b> уходит в защиту")
        return False, None

    if action == "risk":
        if random.random() < 0.28:
            session["log"].append(f"💨 <b>{actor_name}</b> рискует, но промахивается")
            return False, None
        damage = random.randint(24, 34) + actor["damage_bonus"]
        crit_chance = 0.10
        action_label = "рискованный удар"
    else:
        damage = random.randint(12, 20) + actor["damage_bonus"]
        crit_chance = 0.15
        action_label = "атаку"

    crit = random.random() < crit_chance
    if crit:
        damage = int(round(damage * 1.5))

    guard_note = ""
    if defender["guard"]:
        damage = int(round(damage * 0.60))
        defender["guard"] = False
        guard_note = " и часть урона блокирует защитой"

    if defender["defense_bonus"]:
        damage = int(round(damage * (1 - defender["defense_bonus"])))

    damage = max(1, damage)
    defender["hp"] = max(0, defender["hp"] - damage)

    crit_note = " 💥 КРИТ!" if crit else ""
    session["log"].append(
        f"⚔️ <b>{actor_name}</b> проводит {action_label} по <b>{defender_name}</b> на <b>{damage}</b> урона{guard_note}{crit_note}"
    )
    if defender["hp"] <= 0:
        session["log"].append(f"☠️ <b>{defender_name}</b> падает в бою")
        return True, actor_id
    return False, None


def _finish_duel(session: dict, winner_id: int):
    loser_id = [uid for uid in session["players"] if uid != winner_id][0]
    bet = session["bet"]
    add_balance(loser_id, -bet)
    add_balance(winner_id, bet)
    xp_win = apply_xp_bonus(winner_id, 25)
    add_xp(winner_id, xp_win)
    add_xp(loser_id, 5)
    update_elo(winner_id, loser_id)
    log_duel_history(winner_id, loser_id, bet, mode="tactical", battle_log="\n".join(session["log"][-12:]))
    stat_increment(winner_id, "total_duels_won")
    stat_increment(winner_id, "total_games_played")
    stat_increment(loser_id, "total_games_played")
    update_quest_progress(winner_id, "win_duel", 1)
    update_quest_progress(winner_id, "play_game", 1)
    update_quest_progress(loser_id, "play_game", 1)
    winner_streak = record_duel_result(winner_id, True)
    record_duel_result(loser_id, False)
    return loser_id, xp_win, winner_streak


@router.message(Command("duel"))
async def cmd_duel(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    args = message.text.split()
    if len(args) < 3 or not args[1].startswith("@") or not args[2].isdigit():
        await message.reply("⚔️ Использование: /duel @username [сумма]")
        return
    amount = int(args[2])
    if amount <= 0:
        await message.reply("❌ Сумма должна быть > 0.")
        return
    challenger = get_user(message.from_user.id)
    if challenger["balance"] < amount:
        await message.reply("❌ Недостаточно монет.")
        return
    target_id = find_user_by_username(args[1])
    if not target_id:
        await message.reply("❌ Пользователь не найден в базе.")
        return
    if target_id == message.from_user.id:
        await message.reply("❌ Нельзя дуэлировать с собой.")
        return
    ensure_user(target_id, args[1].lstrip("@"))
    target_user = get_user(target_id)
    if not target_user:
        await message.reply("❌ Ошибка: не удалось получить данные цели.")
        return
    if target_user["balance"] < amount:
        await message.reply(f"❌ У {mention(target_user['username'], target_id)} недостаточно монет.", parse_mode="Markdown")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⚔️ Принять", callback_data=f"duel_accept_{message.from_user.id}_{target_id}_{amount}"),
        InlineKeyboardButton(text="🏳️ Отказаться", callback_data=f"duel_decline_{message.from_user.id}"),
    ]])
    await message.reply(
        f"⚔️ {mention(message.from_user.full_name, message.from_user.id)} вызывает "
        f"{mention(target_user['username'] or str(target_id), target_id)} на дуэль\\!\n"
        f"Ставка: *{amount}* монет 🪙\n\n"
        f"Формат: *атака / защита / риск*\n"
        f"{mention(target_user['username'] or str(target_id), target_id)}, принимаешь вызов?",
        parse_mode="MarkdownV2",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("duel_accept_"))
async def cb_duel_accept(call: CallbackQuery):
    _, _, challenger_id, target_id, amount = call.data.split("_")
    challenger_id, target_id, amount = int(challenger_id), int(target_id), int(amount)
    if call.from_user.id != target_id:
        await call.answer("Это не ваша дуэль!", show_alert=True)
        return

    ensure_user(challenger_id)
    ensure_user(target_id)
    c_user = get_user(challenger_id)
    t_user = get_user(target_id)
    if not c_user or not t_user:
        await call.message.edit_text("❌ Ошибка: данные участников не найдены.", reply_markup=None)
        return
    if c_user["balance"] < amount or t_user["balance"] < amount:
        await call.message.edit_text("❌ Недостаточно монет у одного из участников. Дуэль отменена.", reply_markup=None)
        return

    session = _start_duel_session(challenger_id, target_id, amount, call.message.message_id)
    await call.message.edit_text(_render_duel(session), parse_mode="HTML", reply_markup=_duel_kb(session["id"]))
    await call.answer("Дуэль началась!")


@router.callback_query(F.data.startswith("d2_"))
async def cb_duel_action(call: CallbackQuery):
    payload = call.data[3:]
    session_id, action = payload.rsplit("_", 1)
    session = DUEL_SESSIONS.get(session_id)
    if not session:
        await call.answer("Эта дуэль уже завершена или сброшена.", show_alert=True)
        return
    if call.from_user.id != session["turn"]:
        await call.answer("Сейчас не ваш ход!", show_alert=True)
        return
    if call.from_user.id not in session["players"]:
        await call.answer("Вы не участвуете в этой дуэли.", show_alert=True)
        return

    finished, winner_id = _apply_duel_action(session, call.from_user.id, action)
    if finished and winner_id is not None:
        loser_id, xp_win, winner_streak = _finish_duel(session, winner_id)
        winner_name = _duel_name(winner_id)
        loser_name = _duel_name(loser_id)
        final_text = (
            _render_duel(session)
            + f"\n\n🏆 Победил <b>{winner_name}</b>!\n"
            + f"💰 +{session['bet']} 🪙 | ✨ +{xp_win} XP\n"
            + f"😵 Проиграл: <b>{loser_name}</b>"
        )
        await call.message.edit_text(final_text, parse_mode="HTML", reply_markup=None)
        if winner_streak >= 10 and not has_achievement(winner_id, 3):
            if grant_achievement(winner_id, 3):
                await call.message.reply(
                    "🏅 <b>Новое достижение!</b>\n🍀 <b>Счастливчик</b> — 10 дуэлей подряд!\n🎁 Награда: 2000 монет",
                    parse_mode="HTML",
                )
        await check_achievements(winner_id, call.message)
        await check_achievements(loser_id, call.message)
        DUEL_SESSIONS.pop(session_id, None)
        await call.answer()
        return

    all_ids = list(session["players"].keys())
    session["turn"] = all_ids[0] if call.from_user.id == all_ids[1] else all_ids[1]
    await call.message.edit_text(_render_duel(session), parse_mode="HTML", reply_markup=_duel_kb(session["id"]))
    await call.answer()


@router.callback_query(F.data.startswith("duel_decline_"))
async def cb_duel_decline(call: CallbackQuery):
    challenger_id = int(call.data.split("_")[2])
    ensure_user(call.from_user.id, call.from_user.username or call.from_user.full_name)
    c_name = get_username_by_id(challenger_id)
    await call.message.edit_text(
        f"🏳️ {mention(call.from_user.full_name, call.from_user.id)} отказался от дуэли с {mention(c_name, challenger_id)}\\.",
        parse_mode="MarkdownV2", reply_markup=None,
    )
    await call.answer()

# ─────────────────────────── QUIZ 2.0 ─────────────────────────────

QUIZ_STREAKS: dict[int, int] = {}


def _pick_quiz_question() -> tuple[int, dict]:
    roll = random.random()
    if roll < 0.35:
        target = "easy"
    elif roll < 0.85:
        target = "normal"
    else:
        target = "hard"

    pool = [(i, q) for i, q in enumerate(QUIZ_QUESTIONS_2) if q.get("difficulty") == target]
    if not pool:
        pool = list(enumerate(QUIZ_QUESTIONS_2))
    return random.choice(pool)


def _quiz_reward(difficulty: str) -> tuple[int, int]:
    meta = QUIZ_DIFFICULTY_META.get(difficulty, QUIZ_DIFFICULTY_META["normal"])
    return meta["coins"], meta["xp"]


@router.message(Command("quiz"))
async def cmd_quiz(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    uid = message.from_user.id
    today_count = get_quiz_today(uid)

    if today_count >= QUIZ_DAILY_LIMIT:
        await message.reply("🛑 Ты сегодня уже ответил(а) на 10 вопросов! Возвращайся завтра. 📅")
        return

    q_index, q = _pick_quiz_question()
    difficulty = q.get("difficulty", "normal")
    meta = QUIZ_DIFFICULTY_META.get(difficulty, QUIZ_DIFFICULTY_META["normal"])
    coins, xp = _quiz_reward(difficulty)
    letters = ["A", "B", "C", "D"]

    buttons = [
        [InlineKeyboardButton(text=f"{letters[i]}. {opt}", callback_data=f"quiz2_{uid}_{q_index}_{i}")]
        for i, opt in enumerate(q["o"])
    ]

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    remaining_after = QUIZ_DAILY_LIMIT - today_count - 1
    question_text = html.escape(q["q"])
    category = html.escape(q.get("category", "Общее"))

    await message.reply(
        "🧠 <b>Викторина 2.0</b>\n\n"
        f"📚 Категория: <b>{category}</b>\n"
        f"🎚️ Сложность: {meta['label']}\n\n"
        f"❓ <b>{question_text}</b>\n\n"
        f"🎁 За верный ответ: <b>{coins} 🪙</b> и <b>{xp} XP</b>\n"
        f"📅 Осталось попыток сегодня после этого вопроса: <b>{remaining_after}</b>",
        parse_mode="HTML",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("quiz2_"))
async def cb_quiz2(call: CallbackQuery):
    parts = call.data.split("_")
    if len(parts) != 4:
        await call.answer("Ошибка данных викторины.", show_alert=True)
        return

    owner_id = int(parts[1])
    q_index = int(parts[2])
    chosen = int(parts[3])

    if call.from_user.id != owner_id:
        await call.answer("Это не ваша викторина!", show_alert=True)
        return

    today_count = get_quiz_today(owner_id)
    if today_count >= QUIZ_DAILY_LIMIT:
        await call.message.edit_text("🛑 Лимит викторины на сегодня уже исчерпан.", reply_markup=None)
        await call.answer()
        return

    if q_index < 0 or q_index >= len(QUIZ_QUESTIONS_2):
        await call.message.edit_text("⚠️ Этот вопрос устарел. Запусти /quiz ещё раз.", reply_markup=None)
        await call.answer()
        return

    q = QUIZ_QUESTIONS_2[q_index]
    correct = int(q["a"])
    difficulty = q.get("difficulty", "normal")

    increment_quiz_count(owner_id)
    stat_increment(owner_id, "total_games_played")
    update_quest_progress(owner_id, "play_game", 1)

    question_text = html.escape(q["q"])
    correct_text = html.escape(q["o"][correct])

    if chosen == correct:
        base_coins, base_xp = _quiz_reward(difficulty)

        if get_active_bonus(owner_id) == "quiz_xp":
            base_xp += 30

        xp = apply_xp_bonus(owner_id, base_xp)
        coins = base_coins

        QUIZ_STREAKS[owner_id] = QUIZ_STREAKS.get(owner_id, 0) + 1
        streak = QUIZ_STREAKS[owner_id]
        streak_bonus = 0

        if streak % 3 == 0:
            streak_bonus = 25
            coins += streak_bonus

        add_balance(owner_id, coins)
        add_xp(owner_id, xp)
        stat_increment(owner_id, "total_quiz_correct")
        update_quest_progress(owner_id, "quiz_correct", 1)

        extra = f"\n🔥 Серия верных ответов: <b>{streak}</b>"
        if streak_bonus:
            extra += f"\n🎁 Бонус серии: <b>+{streak_bonus} 🪙</b>"

        await call.message.edit_text(
            "✅ <b>Правильно!</b>\n\n"
            f"❓ {question_text}\n"
            f"✔️ Ответ: <b>{correct_text}</b>\n\n"
            f"💰 Награда: <b>+{coins} 🪙</b>\n"
            f"⭐ Опыт: <b>+{xp} XP</b>"
            f"{extra}",
            parse_mode="HTML",
            reply_markup=None,
        )
        await check_achievements(owner_id, call.message)
    else:
        QUIZ_STREAKS[owner_id] = 0
        chosen_text = html.escape(q["o"][chosen]) if 0 <= chosen < len(q["o"]) else "неизвестно"

        await call.message.edit_text(
            "❌ <b>Неверно!</b>\n\n"
            f"❓ {question_text}\n"
            f"Ваш ответ: <b>{chosen_text}</b>\n"
            f"Правильный ответ: <b>{correct_text}</b>\n\n"
            "Попробуй ещё: /quiz",
            parse_mode="HTML",
            reply_markup=None,
        )

    await call.answer()

