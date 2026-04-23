from aiogram import F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.shared import *

# ─────────────────────────── /RANK ────────────────────────────────

@router.message(Command("rank"))
async def cmd_rank(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    u = get_user(message.from_user.id)
    level = calc_level(u["xp"])
    rank_name, rank_emoji = get_rank(level)
    next_rank = get_next_rank(level)

    lines = [
        f"🦊 <b>Фурри-ранг: {rank_emoji} {rank_name}</b>",
        f"📊 Уровень: <b>{level}</b>",
    ]
    if next_rank:
        next_lvl, next_name, next_emoji = next_rank
        levels_needed = next_lvl - level
        lines.append(f"⬆️ Следующий ранг: {next_emoji} <b>{next_name}</b>")
        lines.append(f"🔺 До него: <b>{levels_needed}</b> уровней")
    else:
        lines.append("🌟 Вы достигли высшего ранга!")
    await message.reply("\n".join(lines), parse_mode="HTML")

# ──────────────────────── /ACHIEVEMENTS ───────────────────────────

@router.message(Command("achievements"))
async def cmd_achievements(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    uid = message.from_user.id
    stats = get_user_stats(uid)
    u = get_user(uid)
    level = calc_level(u["xp"])

    lines = ["🏅 <b>Достижения</b>\n"]
    for ach_id, ach in ACHIEVEMENTS.items():
        earned = has_achievement(uid, ach_id)
        status = "✅" if earned else "🔒"

        # Прогресс для некоторых достижений
        progress = ""
        if not earned:
            if ach_id == 1:
                progress = f" ({stats['total_rp_actions']}/100)"
            elif ach_id == 4:
                progress = f" ({stats['total_quiz_correct']}/50)"
            elif ach_id == 7:
                progress = f" ({stats['total_money_given']}/5000)"
            elif ach_id == 8:
                progress = f" ({stats['total_games_played']}/100)"
            elif ach_id == 10:
                progress = f" ({stats['total_duels_won']}/25)"
            elif ach_id == 12:
                progress = f" ({level}/20)"

        lines.append(f"{status} {ach['icon']} <b>{ach['name']}</b>{progress}\n   <i>{ach['desc']}</i>")

    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM achievements WHERE user_id=?", (uid,))
    total_earned = c.fetchone()[0]; conn.close()
    lines.append(f"\n📊 Получено: <b>{total_earned}/{len(ACHIEVEMENTS)}</b>")
    lines.append("ℹ️ Подробнее: /achievement [номер]")
    await message.reply("\n".join(lines), parse_mode="HTML")

@router.message(Command("achievement"))
async def cmd_achievement_detail(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("ℹ️ Использование: /achievement [номер от 1 до 12]")
        return
    # Поиск по номеру или названию
    query = args[1].strip()
    ach_id = None
    if query.isdigit():
        ach_id = int(query)
    else:
        for aid, ach in ACHIEVEMENTS.items():
            if ach["name"].lower() == query.lower():
                ach_id = aid
                break
    if not ach_id or ach_id not in ACHIEVEMENTS:
        await message.reply("❌ Достижение не найдено. Введите номер от 1 до 12.")
        return
    ach = ACHIEVEMENTS[ach_id]
    earned = has_achievement(message.from_user.id, ach_id)
    conn = get_conn(); c = conn.cursor()
    c.execute(
        "SELECT earned_at FROM achievements WHERE user_id=? AND achievement_id=?",
        (message.from_user.id, ach_id),
    )
    row = c.fetchone(); conn.close()
    status = "✅ Получено" if earned else "🔒 Не получено"
    date_str = ""
    if row:
        dt = datetime.fromtimestamp(row[0], tz=timezone.utc).strftime("%d.%m.%Y")
        date_str = f"\n📅 Дата получения: {dt}"
    await message.reply(
        f"{ach['icon']} <b>{ach['name']}</b>\n"
        f"Статус: {status}{date_str}\n\n"
        f"📋 Условие: {ach['desc']}\n"
        f"🎁 Награда: {ach['reward']}",
        parse_mode="HTML",
    )

# ─────────────────────────── /TOP_ACTIVITY ───────────────────────────────

@router.message(Command("top_activity"))
async def cmd_top_activity(message: Message):
    """Топ пользователей по last_seen (last_daily_ts как приближение)."""
    conn = get_conn(); c = conn.cursor()
    # Используем daily_ts как last_seen, дополнительно XP как вторичный критерий
    c.execute("SELECT username, xp, daily_ts FROM users ORDER BY daily_ts DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()
    if not rows:
        await message.reply("📊 Статистика пуста.")
        return
    lines = ["📊 <b>Топ по активности (последний /daily):</b>\n"]
    now = int(time.time())
    for i, (name, xp, ts) in enumerate(rows, 1):
        if ts > 0:
            hours_ago = (now - ts) // 3600
            when = f"{hours_ago}ч назад" if hours_ago < 24 else f"{hours_ago // 24}д назад"
        else:
            when = "давно"
        lines.append(f"{i}. {name or '???'} — {when}")
    await message.reply("\n".join(lines), parse_mode="HTML")

# ─────────────────────────── /TOP_RP_ACTIONS ─────────────────────────────

@router.message(Command("top_rp_actions"))
async def cmd_top_rp_actions(message: Message):
    """Топ по количеству РП-действий."""
    conn = get_conn(); c = conn.cursor()
    c.execute(
        "SELECT u.username, s.total_rp_actions "
        "FROM user_stats s JOIN users u ON u.user_id=s.user_id "
        "ORDER BY s.total_rp_actions DESC LIMIT 10"
    )
    rows = c.fetchall()
    conn.close()
    if not rows:
        await message.reply("🎭 Статистика РП пуста.")
        return
    lines = ["🎭 <b>Топ по РП-действиям:</b>\n"]
    for i, (name, cnt) in enumerate(rows, 1):
        lines.append(f"{i}. {name or '???'} — {cnt} действий")
    await message.reply("\n".join(lines), parse_mode="HTML")

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

# ─────────────────── БОНУС ДНЯ ────────────────────────────────────

@router.message(Command("daily_bonus"))
async def cmd_daily_bonus(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    uid = message.from_user.id

    existing = get_active_bonus(uid)
    if existing:
        display = get_bonus_display(existing)
        await message.reply(
            f"🎁 Ваш бонус дня уже активен:\n<b>{display}</b>\n\n"
            f"Он действует до 23:59 UTC сегодня.",
            parse_mode="HTML",
        )
        return

    bonus_type = activate_bonus(uid)
    if not bonus_type:
        await message.reply("⚠️ Не удалось активировать бонус. Попробуйте позже.")
        return

    display = get_bonus_display(bonus_type)
    await message.reply(
        f"🎁 <b>Бонус дня активирован!</b>\n\n{display}\n\n"
        f"Действует до 23:59 UTC. Удачи! ✨",
        parse_mode="HTML",
    )

@router.message(Command("bonus_info"))
async def cmd_bonus_info(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    uid = message.from_user.id

    active = get_active_bonus(uid)

    # Рассчитываем время до следующего бонуса (до 00:00 UTC)
    now_utc = datetime.now(timezone.utc)
    midnight = now_utc.replace(hour=23, minute=59, second=59, microsecond=0)
    seconds_left = int((midnight - now_utc).total_seconds())
    h, remainder = divmod(seconds_left, 3600)
    m, _ = divmod(remainder, 60)

    if active:
        display = get_bonus_display(active)
        await message.reply(
            f"🎁 <b>Текущий бонус:</b>\n{display}\n\n"
            f"⏰ До конца дня: <b>{h}ч {m}м</b>\n\n"
            f"Завтра у вас будет новый бонус!",
            parse_mode="HTML",
        )
    else:
        await message.reply(
            f"🎁 У вас нет активного бонуса.\n\n"
            f"Активировать: /daily_bonus\n"
            f"⏰ До сброса: <b>{h}ч {m}м</b>",
            parse_mode="HTML",
        )

# ─────────────────────────── /ELO ────────────────────────────────
# Команда показывает твой личный ELO рейтинг для дуэлей
# ELO — система рейтинга: побеждаешь сильных → много очков, проигрываешь слабым → теряешь много

@router.message(Command("elo"))
async def cmd_elo(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    uid = message.from_user.id
    
    # Получаем текущий рейтинг пользователя (по умолчанию 1000)
    elo = get_elo(uid)
    
    # Получаем текстовый ранг (Новичок, Средний, Эксперт, Мастер и т.д.)
    rank = get_elo_rank(uid)
    
    # Получаем статистику игр из базы данных
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT games_played, games_won FROM elo_ratings WHERE user_id=?", (uid,))
    row = c.fetchone()
    conn.close()
    
    games = row[0] if row else 0      # Сколько всего дуэлей сыграл
    wins = row[1] if row else 0       # Сколько дуэлей выиграл
    
    # Считаем процент побед (если игр не было — 0%)
    winrate = (wins / games * 100) if games > 0 else 0
    
    # Отправляем красивое сообщение с рейтингом
    await message.reply(
        f"⚔️ <b>ELO РЕЙТИНГ</b>\n\n"
        f"📊 Рейтинг: <b>{elo}</b>\n"
        f"{rank}\n\n"
        f"🎮 Всего игр: <b>{games}</b>\n"
        f"🏆 Побед: <b>{wins}</b>\n"
        f"📈 Процент побед: <b>{winrate:.1f}%</b>",
        parse_mode="HTML"
    )

# ─────────────────────────── /PROFILE ─────────────────────────────
# Команда показывает красивую карточку пользователя с полной статистикой
# Использование: /profile — свой профиль, /profile @username — профиль другого
# В профиле есть: уровень, ранг, баланс, XP, ELO, брак, достижения, кастомные команды

async def show_profile(target, user_id: int):
    """Универсальная функция показа профиля (для команды и кнопки Назад)"""
    u = get_user(user_id)
    if not u:
        if isinstance(target, CallbackQuery):
            await target.message.edit_text("❌ Пользователь не найден.")
        else:
            await target.reply("❌ Пользователь не найден.")
        return

    stats = get_user_stats(user_id)
    level = calc_level(u["xp"])
    rank_name, rank_emoji = get_rank(level)
    elo = get_elo(user_id)
    elo_rank = get_elo_rank(user_id)

    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM achievements WHERE user_id=?", (user_id,))
    ach_count = c.fetchone()[0]
    conn.close()

    m = get_marriage(user_id)
    if m:
        partner_id = m["user2_id"] if m["user1_id"] == user_id else m["user1_id"]
        partner_name = get_username_by_id(partner_id)
        partner_mention = f"<a href='tg://user?id={partner_id}'>{partner_name}</a>"
        days_married = (int(time.time()) - m["married_since"]) // 86400
        marriage_info = f"💍 {partner_mention} ({days_married} дн.)"
    else:
        marriage_info = "💔 нет"

    user_name = u["username"] or str(user_id)
    user_mention = f"<a href='tg://user?id={user_id}'>{user_name}</a>"

    profile_text = f"""
🦊 <b>ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ</b> 🦊
———————————————

🌟 {user_mention}

🏆 Уровень: <b>{level}</b>
{rank_emoji} Ранг: <b>{rank_name}</b>
💰 Баланс: <b>{u['balance']} 🪙</b>
✨ Опыт: <b>{u['xp']} XP</b>
⚔️ ELO: <b>{elo}</b> ({elo_rank})
💍 Брак: {marriage_info}

📊 <b>СТАТИСТИКА</b>
———————————————
🎭 РП-действий: <b>{stats['total_rp_actions']}</b>
🎲 Игр сыграно: <b>{stats['total_games_played']}</b>
⚔️ Дуэлей выиграно: <b>{stats['total_duels_won']}</b>
💸 Монет подарено: <b>{stats['total_money_given']}</b>
❓ Правильных ответов: <b>{stats['total_quiz_correct']}</b>
🏅 Достижений: <b>{ach_count}/12</b>
"""

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏅 Достижения", callback_data=f"profile_achievements_{user_id}"),
            InlineKeyboardButton(text="🎭 Мои команды", callback_data=f"profile_commands_{user_id}"),
        ]
    ])

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(profile_text, parse_mode="HTML", reply_markup=kb)
    else:
        await target.reply(profile_text, parse_mode="HTML", reply_markup=kb)


@router.message(Command("profile"))
async def cmd_profile(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)

    args = message.text.split()
    if len(args) > 1 and args[1].startswith("@"):
        target_id = find_user_by_username(args[1])
        if not target_id:
            await message.reply("❌ Пользователь не найден.")
            return
    else:
        target_id = message.from_user.id

    await show_profile(message, target_id)


# ─────────────────── ПРОФИЛЬ: ДОСТИЖЕНИЯ ─────────────────────────
# Обработчик кнопки "Достижения" в профиле
# Показывает список всех 12 достижений и статус (получено/нет)

@router.callback_query(F.data.startswith("profile_achievements_"))
async def profile_achievements(call: CallbackQuery):
    target_id = int(call.data.split("_")[2])
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT achievement_id FROM achievements WHERE user_id=?", (target_id,))
    earned = [row[0] for row in c.fetchall()]
    conn.close()

    text = "🏅 <b>ДОСТИЖЕНИЯ</b>\n\n"
    for ach_id, ach in ACHIEVEMENTS.items():
        status = "✅" if ach_id in earned else "🔒"
        text += f"{status} {ach['icon']} <b>{ach['name']}</b>\n   <i>{ach['desc']}</i>\n\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"profile_back_{target_id}")]
    ])
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


# ─────────────────── ПРОФИЛЬ: КАСТОМНЫЕ КОМАНДЫ ──────────────────
# Обработчик кнопки "Мои команды" в профиле
# Показывает список кастомных РП-команд пользователя

@router.callback_query(F.data.startswith("profile_commands_"))
async def profile_commands(call: CallbackQuery):
    target_id = int(call.data.split("_")[2])
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT keyword, uses_count FROM custom_rp WHERE user_id=? ORDER BY uses_count DESC", (target_id,))
    rows = c.fetchall()
    conn.close()

    if not rows:
        text = "🎭 <b>КАСТОМНЫЕ КОМАНДЫ</b>\n\nУ пользователя нет кастомных РП-команд."
    else:
        text = "🎭 <b>КАСТОМНЫЕ КОМАНДЫ</b>\n\n"
        for kw, uses in rows:
            text += f"• <b>{kw}</b> (использований: {uses})\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"profile_back_{target_id}")]
    ])
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


# ─────────────────── ПРОФИЛЬ: НАЗАД ─────────────────────────────
# Обработчик кнопки "Назад" из разделов достижений и команд

@router.callback_query(F.data.startswith("profile_back_"))
async def profile_back(call: CallbackQuery):
    target_id = int(call.data.split("_")[2])
    await show_profile(call, target_id)
    await call.answer()

