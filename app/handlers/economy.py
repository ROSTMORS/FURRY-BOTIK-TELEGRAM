from aiogram.filters import Command
from aiogram.types import Message

from app.shared import *


@router.message(Command(commands=["balance", "money"]))
async def cmd_balance(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    u = get_user(message.from_user.id)
    await message.reply(
        f"💰 <b>{message.from_user.full_name}</b>\nБаланс: <b>{u['balance']}</b> 🪙",
        parse_mode="HTML",
    )


@router.message(Command("daily"))
async def cmd_daily(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    u = get_user(message.from_user.id)
    now = int(time.time())
    if now - u["daily_ts"] < 86400:
        remaining = 86400 - (now - u["daily_ts"])
        h, m = divmod(remaining // 60, 60)
        await message.reply(f"⏳ Следующий бонус через: <b>{h}ч {m}м</b>", parse_mode="HTML")
        return

    coins = 100
    if get_active_bonus(message.from_user.id) == "daily_coins":
        coins += 200

    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET balance=balance+?, daily_ts=? WHERE user_id=?", (coins, now, message.from_user.id))
    conn.commit()
    conn.close()
    xp = apply_xp_bonus(message.from_user.id, 10)
    add_xp(message.from_user.id, xp)
    await message.reply(
        f"🎁 Ежедневный бонус: <b>+{coins} монет, +{xp} XP</b>!",
        parse_mode="HTML",
    )
    await check_achievements(message.from_user.id, message)


@router.message(Command("give"))
async def cmd_give(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    args = message.text.split()
    if len(args) < 3 or not args[1].startswith("@") or not args[2].isdigit():
        await message.reply("💸 Использование: /give @username [сумма]")
        return
    amount = int(args[2])
    if amount <= 0:
        await message.reply("❌ Сумма должна быть > 0.")
        return
    sender = get_user(message.from_user.id)
    if sender["balance"] < amount:
        await message.reply("❌ Недостаточно монет!")
        return
    target_id = find_user_by_username(args[1])
    if not target_id:
        await message.reply("❌ Пользователь не найден.")
        return
    if target_id == message.from_user.id:
        await message.reply("❌ Нельзя переводить самому себе.")
        return
    ensure_user(target_id, args[1].lstrip("@"))
    target_user = get_user(target_id)
    if not target_user:
        await message.reply("❌ Ошибка: не удалось получить данные получателя.")
        return
    add_balance(message.from_user.id, -amount)
    add_balance(target_id, amount)
    stat_increment(message.from_user.id, "total_money_given", amount)
    update_quest_progress(message.from_user.id, "give_money", amount)

    day_bonus = get_active_bonus(message.from_user.id)
    extra_xp_msg = ""
    if day_bonus == "give_xp":
        add_xp(message.from_user.id, 20)
        extra_xp_msg = " (+20 XP вам 🎁)"

    target_name = target_user['username'] or str(target_id)
    target_mention = f"<a href='tg://user?id={target_id}'>{target_name}</a>"

    await message.reply(
        f"✅ Вы перевели <b>{amount} 🪙</b> пользователю {target_mention}!{extra_xp_msg}",
        parse_mode="HTML",
    )
    await check_achievements(message.from_user.id, message)


@router.message(Command("shop"))
async def cmd_shop(message: Message):
    lines = ["🛒 <b>Магазин 2.0</b>", ""]
    for num, item in SHOP_ITEMS.items():
        if num == 13:
            continue
        passive = " | пассивный" if item.get("passive") else ""
        lines.append(
            f"{num}. {item['name']} — <b>{item['price']} 🪙</b>\n"
            f"   <i>{item['desc']}</i>\n"
            f"   {rarity_badge(item)} • {category_label(item)}{passive}"
        )
    lines.append("\nКупить: /buy [номер]")
    lines.append("Активные эффекты: /effects")
    await message.reply("\n".join(lines), parse_mode="HTML")


def _add_to_inventory(user_id: int, item_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO inventory (user_id, item_id, amount) VALUES (?, ?, 1) ON CONFLICT(user_id, item_id) DO UPDATE SET amount = amount + 1",
        (user_id, item_id),
    )
    conn.commit()
    conn.close()


def _remove_from_inventory(user_id: int, item_id: int) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT amount FROM inventory WHERE user_id=? AND item_id=?", (user_id, item_id))
    row = c.fetchone()
    if not row or row[0] <= 0:
        conn.close()
        return False
    if row[0] == 1:
        c.execute("DELETE FROM inventory WHERE user_id=? AND item_id=?", (user_id, item_id))
    else:
        c.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id=? AND item_id=?", (user_id, item_id))
    conn.commit()
    conn.close()
    return True


@router.message(Command("buy"))
async def cmd_buy(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.reply("🛒 Использование: /buy [номер]")
        return
    item_id = int(args[1])
    if item_id not in SHOP_ITEMS or item_id == 13:
        await message.reply("❌ Нет такого предмета. Смотри /shop.")
        return
    item = SHOP_ITEMS[item_id]
    u = get_user(message.from_user.id)
    if u["balance"] < item["price"]:
        await message.reply(f"❌ Нужно {item['price']} 🪙, у вас {u['balance']} 🪙.")
        return
    add_balance(message.from_user.id, -item["price"])
    _add_to_inventory(message.from_user.id, item_id)

    bonus = ""
    if item_id == 4:
        add_xp(message.from_user.id, 10)
        bonus = " +10 XP!"
    elif item_id == 12:
        add_xp(message.from_user.id, 50)
        bonus = " +50 XP! Статус «👑 Властелин» активен."
    elif item_id == 11:
        conn = get_conn(); c = conn.cursor()
        c.execute(
            "INSERT INTO item_effects (user_id, dragon_egg, dragon_ts) VALUES (?, 1, ?) ON CONFLICT(user_id) DO UPDATE SET dragon_egg=1, dragon_ts=?",
            (message.from_user.id, int(time.time()), int(time.time())),
        )
        conn.commit(); conn.close()
        bonus = " Яйцо вылупится через 7 дней!"
    elif item_id == 10:
        conn = get_conn(); c = conn.cursor()
        c.execute(
            "INSERT INTO item_effects (user_id, magic_hat) VALUES (?, 1) ON CONFLICT(user_id) DO UPDATE SET magic_hat=1",
            (message.from_user.id,),
        )
        conn.commit(); conn.close()
        bonus = " Теперь используй /hat каждые 24ч!"

    update_quest_progress(message.from_user.id, "buy_item", 1)
    await message.reply(f"✅ Куплено: {item['name']}!{bonus}", parse_mode="HTML")
    await check_achievements(message.from_user.id, message)


@router.message(Command("inventory"))
async def cmd_inventory(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT item_id, amount FROM inventory WHERE user_id=? AND amount>0 ORDER BY item_id ASC", (message.from_user.id,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        await message.reply("🎒 Инвентарь пуст.")
        return
    lines = ["🎒 <b>Инвентарь 2.0</b>", ""]
    for item_id, amount in rows:
        item = SHOP_ITEMS.get(item_id)
        if item:
            lines.append(f"{item_id}. {item['name']} × {amount} — {rarity_badge(item)} • {category_label(item)}")
    lines.append("\nИспользовать: /use [номер]")
    lines.append("Эффекты: /effects")
    await message.reply("\n".join(lines), parse_mode="HTML")


@router.message(Command(commands=["use", "use_item"]))
async def cmd_use(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.reply("🎒 Использование: /use [номер]")
        return
    item_id = int(args[1])

    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT amount FROM inventory WHERE user_id=? AND item_id=?", (message.from_user.id, item_id))
    row = c.fetchone()
    conn.close()

    if not row or row[0] <= 0:
        await message.reply("❌ У вас нет такого предмета.")
        return

    item = SHOP_ITEMS.get(item_id)
    if item and not item.get("usable", True):
        await message.reply("❌ Этот предмет нельзя использовать вручную.")
        return

    response = await _apply_item_effect(message, item_id)
    if response is None:
        return

    _remove_from_inventory(message.from_user.id, item_id)
    update_quest_progress(message.from_user.id, "use_item", 1)
    await message.reply(response, parse_mode="HTML")


async def _apply_item_effect(message: Message, item_id: int) -> Optional[str]:
    uid = message.from_user.id
    item = SHOP_ITEMS.get(item_id, {})
    if item_id == 1:
        return "🍎 Вы съели яблоко. Хруск! Настроение +100%"
    if item_id == 2:
        if not message.reply_to_message:
            await message.reply("🌹 Ответьте на сообщение того, кому хотите подарить розу.")
            return None
        target = message.reply_to_message.from_user
        ensure_user(target.id, target.username or target.full_name)
        add_xp(target.id, 5)
        return f"🌹 Вы подарили розу {mention(target.full_name, target.id)}! (+5 XP им)"
    if item_id == 3:
        gift = random.randint(10, 100)
        add_balance(uid, gift)
        return f"🎁 Открыт подарок! Внутри <b>{gift} монет</b>! 🎉"
    if item_id == 4:
        return "🧸 Вы обнимаете плюшевого мишку. Так уютно~"
    if item_id == 5:
        add_xp(uid, 15)
        return "💊 Выпито зелье здоровья. +15 XP! Чувствуешь себя лучше."
    if item_id == 6:
        if random.random() < 0.30:
            add_balance(uid, 100)
            return "🎫 Лотерея: 🎉 <b>Победа!</b> +100 монет!"
        return "🎫 Лотерея: 😔 Не повезло. Удачи в следующий раз."
    if item_id == 7:
        add_xp(uid, 50)
        return "📜 Свиток опыта использован. +50 XP! ✨"
    if item_id == 8:
        conn = get_conn(); c = conn.cursor()
        c.execute(
            "INSERT INTO item_effects (user_id, lucky_slots) VALUES (?, 1) ON CONFLICT(user_id) DO UPDATE SET lucky_slots=1",
            (uid,),
        )
        conn.commit(); conn.close()
        return "🍀 Четырёхлистный клевер активирован! Удача в /slots +10%."
    if item_id == 9:
        pred = random.choice(PREDICTIONS)
        return f"🔮 Хрустальный шар говорит:\n<i>«{pred}»</i>"
    if item_id == 10:
        return "🎩 Магическая шляпа уже работает пассивно. Используй /hat для получения предмета."
    if item_id == 11:
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT dragon_ts FROM item_effects WHERE user_id=?", (uid,))
        row = c.fetchone()
        conn.close()
        if row and (int(time.time()) - row[0]) >= 7 * 86400:
            prize_id = random.choice([3, 6, 7, 9, 14, 16, 17, 18])
            _add_to_inventory(uid, prize_id)
            prize_name = SHOP_ITEMS[prize_id]["name"]
            if check_achievement_dragon(uid):
                asyncio.create_task(message.reply(
                    "🏅 <b>Новое достижение!</b>\n🐉 <b>Властелин драконов</b>!\n🎁 Награда: редкий предмет",
                    parse_mode="HTML",
                ))
            return f"🐉 Яйцо вылупилось! Дракончик принёс тебе: <b>{prize_name}</b>! 🎉"
        if row:
            days_left = 7 - (int(time.time()) - row[0]) // 86400
            return f"🥚 Яйцо ещё не вылупилось. Осталось ~{days_left} дн."
        return "🥚 Нет активного яйца дракона."
    if item_id == 12:
        return "👑 Корона уже надета! Ваш статус «Властелин» виден в /leaderboard."
    if item_id == 13:
        return "🦊 Лисий хвост красиво развевается на ветру. Это редкий предмет!"
    if item_id in {14, 15, 16, 20, 21, 22}:
        add_active_effect(
            uid,
            item["effect_key"],
            item["effect_value"],
            duration_hours=item.get("duration_hours", 24),
            uses=item.get("uses", 1),
            source_item_id=item_id,
        )
        if item_id == 14:
            return "🎯 Амулет дуэлянта активирован! В следующей дуэли вы получите <b>+1 к инициативе</b>."
        if item_id == 15:
            return "🗡️ Клык берсерка активирован! В следующей дуэли вы получите <b>+2 к инициативе</b>."
        if item_id == 16:
            return "✨ Порошок удачи рассеян! Следующие <b>3</b> запуска /slots получат <b>+15%</b> к удаче."
        if item_id == 20:
            return "🩹 Боевой бинт подготовлен! В следующей дуэли у вас будет <b>+20 HP</b>."
        if item_id == 21:
            return "🛡️ Щит стаи активирован! В следующей дуэли входящий урон будет ниже на <b>15%</b>."
        return "🔥 Руна ярости активирована! В следующей дуэли ваши атаки получат <b>+4 урона</b>."
    if item_id == 17:
        coins = random.randint(60, 180)
        add_balance(uid, coins)
        return f"💰 Вы развязали мешочек и нашли <b>{coins} монет</b>!"
    if item_id == 18:
        add_xp(uid, 25)
        return "🍖 Сытный паёк съеден. +25 XP!"
    if item_id == 19:
        if random.random() < 0.5:
            add_balance(uid, 120)
            return "🧪 Зелье сработало в плюс: <b>+120 монет</b>!"
        add_xp(uid, 70)
        return "🧪 Зелье вспыхнуло опытом: <b>+70 XP</b>!"
    return "❓ Неизвестный предмет."


@router.message(Command("effects"))
async def cmd_effects(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    effects = get_active_effects(message.from_user.id)
    if not effects:
        await message.reply("✨ У вас нет активных эффектов.", parse_mode="HTML")
        return
    lines = ["✨ <b>Активные эффекты</b>", ""]
    for effect in effects:
        lines.append(format_effect_line(effect))
    await message.reply("\n".join(lines), parse_mode="HTML")


@router.message(Command("hat"))
async def cmd_hat(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    if not has_inventory_item(message.from_user.id, 10):
        await message.reply("🎩 У вас нет Магической шляпы. Купите в /shop!")
        return
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT hat_last_ts FROM item_effects WHERE user_id=?", (message.from_user.id,))
    row = c.fetchone()
    now = int(time.time())
    if row and (now - row[0]) < 86400:
        remaining = 86400 - (now - row[0])
        h, m = divmod(remaining // 60, 60)
        conn.close()
        await message.reply(f"🎩 Шляпа уже использована. Следующий предмет через {h}ч {m}м.")
        return
    gift_id = random.choice(hat_drop_pool())
    _add_to_inventory(message.from_user.id, gift_id)
    c.execute(
        "INSERT INTO item_effects (user_id, hat_last_ts) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET hat_last_ts=?",
        (message.from_user.id, now, now),
    )
    conn.commit()
    conn.close()
    item = SHOP_ITEMS[gift_id]
    await message.reply(
        f"🎩 Шляпа достала из себя: <b>{item['name']}</b>!\n{rarity_badge(item)} • {category_label(item)}",
        parse_mode="HTML",
    )


@router.message(Command("daily_bonus"))
async def cmd_daily_bonus(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    uid = message.from_user.id
    existing = get_active_bonus(uid)
    if existing:
        display = get_bonus_display(existing)
        await message.reply(
            f"🎁 Ваш бонус дня уже активен:\n<b>{display}</b>\n\nОн действует до 23:59 UTC сегодня.",
            parse_mode="HTML",
        )
        return
    bonus_type = activate_bonus(uid)
    if not bonus_type:
        await message.reply("⚠️ Не удалось активировать бонус. Попробуйте позже.")
        return
    display = get_bonus_display(bonus_type)
    await message.reply(
        f"🎁 <b>Бонус дня активирован!</b>\n\n{display}\n\nДействует до 23:59 UTC. Удачи! ✨",
        parse_mode="HTML",
    )


@router.message(Command("bonus_info"))
async def cmd_bonus_info(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    uid = message.from_user.id
    active = get_active_bonus(uid)
    now_utc = datetime.now(timezone.utc)
    midnight = now_utc.replace(hour=23, minute=59, second=59, microsecond=0)
    seconds_left = int((midnight - now_utc).total_seconds())
    h, remainder = divmod(seconds_left, 3600)
    m, _ = divmod(remainder, 60)
    if active:
        display = get_bonus_display(active)
        await message.reply(
            f"🎁 <b>Текущий бонус:</b>\n{display}\n\n⏰ До конца дня: <b>{h}ч {m}м</b>\n\nЗавтра у вас будет новый бонус!",
            parse_mode="HTML",
        )
    else:
        await message.reply(
            f"🎁 У вас нет активного бонуса.\n\nАктивировать: /daily_bonus\n⏰ До сброса: <b>{h}ч {m}м</b>",
            parse_mode="HTML",
        )
