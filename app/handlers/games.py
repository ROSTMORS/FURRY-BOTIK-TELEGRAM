from aiogram import F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.shared import *

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

@router.message(Command("slots"))
async def cmd_slots(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    uid = message.from_user.id
    args = message.text.split()

    # Бонус "День азарта": бесплатная ставка
    free_bet = get_active_bonus(uid) == "free_slots"

    if len(args) < 2 or not args[1].isdigit():
        if free_bet:
            # При активном бонусе можно играть без ставки
            bet = 50  # дефолтная ставка при бесплатной игре
        else:
            await message.reply("🎰 Использование: /slots [сумма] (мин. 10)")
            return
    else:
        bet = int(args[1])

    if bet < 10:
        await message.reply("❌ Минимальная ставка — 10 монет.")
        return

    u = get_user(uid)

    if free_bet:
        # Бесплатная ставка — деньги не снимаем, но только раз (отмечаем использование)
        bet_text = f"(бесплатная ставка 🎲 {bet} 🪙)"
        # Снимаем бонус чтобы не использовать повторно
        conn = get_conn(); c = conn.cursor()
        c.execute(
            "UPDATE daily_bonus_log SET bonus_type='free_slots_used' WHERE user_id=? AND bonus_date=?",
            (uid, get_today_str()),
        )
        conn.commit(); conn.close()
    else:
        if u["balance"] < bet:
            await message.reply("❌ Недостаточно монет!")
            return
        bet_text = f"{bet} 🪙"

    # Проверяем бонус клевера (+10% удачи), день удачи (+20%) и временные эффекты предметов 2.0
    lucky = has_inventory_item(uid, 8)
    day_lucky = get_active_bonus(uid) == "lucky_slots"
    temp_slots_bonus = get_effect_value(uid, "slots_bonus")

    symbols = ["🍒", "🍋", "🍊", "🍇", "⭐", "🔔"]
    s1, s2, s3 = random.choice(symbols), random.choice(symbols), random.choice(symbols)

    if not free_bet:
        add_balance(uid, -bet)

    # Статистика: игра сыграна
    stat_increment(uid, "total_games_played")

    win = False
    if s1 == s2 == s3:
        win = True
    elif lucky and random.random() < 0.10:
        s3 = s1
        win = s1 == s2 == s3
    elif day_lucky and random.random() < 0.20:
        s3 = s1
        win = s1 == s2 == s3
    elif temp_slots_bonus and random.random() < float(temp_slots_bonus):
        s3 = s1
        win = s1 == s2 == s3

    if temp_slots_bonus:
        consume_effects(uid, "slots_bonus", 1)

    slots_streak = record_slots_result(uid, win)

    if win:
        prize = bet * 2
        add_balance(uid, prize)
        xp = apply_xp_bonus(uid, 15)
        add_xp(uid, xp)
        result = f"🎉 ДЖЕКПОТ! Выигрыш: <b>{prize}</b> монет! +{xp} XP"
        # Достижение #9: 3 победы подряд в слотах
        if slots_streak >= 3 and not has_achievement(uid, 9):
            if grant_achievement(uid, 9):
                await message.reply(
                    f"🏅 <b>Новое достижение!</b>\n🌟 <b>Любимчик фортуны</b>\n🎁 Награда: 500 монет",
                    parse_mode="HTML",
                )
    else:
        result = f"😔 Не повезло. Потеряно: <b>{bet}</b> монет."

    await message.reply(f"🎰 | {s1} | {s2} | {s3} |\n{bet_text}\n\n{result}", parse_mode="HTML")
    await check_achievements(uid, message)


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

@router.message(Command("quiz"))
async def cmd_quiz(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    today_count = get_quiz_today(message.from_user.id)
    if today_count >= QUIZ_DAILY_LIMIT:
        await message.reply("🛑 Ты сегодня уже ответил(а) на 10 вопросов! Возвращайся завтра. 📅")
        return
    q = random.choice(QUIZ_QUESTIONS)
    buttons = [
        [InlineKeyboardButton(
            text=opt,
            callback_data=f"quiz_{i}_{q['a']}_{message.from_user.id}",
        )]
        for i, opt in enumerate(q["o"])
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    remaining = QUIZ_DAILY_LIMIT - today_count
    await message.reply(
        f"❓ <b>Вопрос:</b> {q['q']}\n\n<i>Осталось попыток сегодня: {remaining - 1}</i>",
        parse_mode="HTML",
        reply_markup=kb,
    )

@router.callback_query(F.data.startswith("quiz_"))
async def cb_quiz(call: CallbackQuery):
    parts = call.data.split("_")
    chosen, correct, owner_id = int(parts[1]), int(parts[2]), int(parts[3])
    if call.from_user.id != owner_id:
        await call.answer("Это не ваша викторина!", show_alert=True)
        return
    increment_quiz_count(owner_id)
    stat_increment(owner_id, "total_games_played")
    if chosen == correct:
        # Бонус "День знаний": +30 XP
        day_bonus = get_active_bonus(owner_id)
        base_xp = 15
        if day_bonus == "quiz_xp":
            base_xp += 30
        xp = apply_xp_bonus(owner_id, base_xp)
        add_balance(owner_id, 50)
        add_xp(owner_id, xp)
        stat_increment(owner_id, "total_quiz_correct")
        await call.message.edit_text(f"✅ Правильно! +50 монет, +{xp} XP 🎉", reply_markup=None)
    else:
        await call.message.edit_text("❌ Неверно! Попыток потрачено. Попробуй /quiz снова.", reply_markup=None)
    await call.answer()

