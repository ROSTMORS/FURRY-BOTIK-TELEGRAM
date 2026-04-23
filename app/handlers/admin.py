from aiogram import F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.shared import *

# ─────────────────────────── АДМИН-КОМАНДЫ ────────────────────────

def admin_only(func):
    """Декоратор: только для администраторов."""
    async def wrapper(message: Message):
        if not is_admin(message.from_user.id):
            await message.reply("🚫 Нет доступа.")
            return
        await func(message)
    wrapper.__name__ = func.__name__
    return wrapper

@router.message(Command("add_money"))
@admin_only
async def cmd_add_money(message: Message):
    args = message.text.split()
    if len(args) < 3 or not args[2].lstrip("-").isdigit():
        await message.reply("Использование: /add_money @username [сумма]")
        return
    target_id = find_user_by_username(args[1])
    if not target_id:
        await message.reply("❌ Пользователь не найден.")
        return
    amount = int(args[2])
    add_balance(target_id, amount)
    log_admin_action(message.from_user.id, "add_money", target_id, str(amount))
    await message.reply(f"✅ Баланс {args[1]} изменён на {amount:+} 🪙")

@router.message(Command("remove_money"))
@admin_only
async def cmd_remove_money(message: Message):
    args = message.text.split()
    if len(args) < 3 or not args[2].isdigit():
        await message.reply("Использование: /remove_money @username [сумма]")
        return
    target_id = find_user_by_username(args[1])
    if not target_id:
        await message.reply("❌ Пользователь не найден.")
        return
    amount = int(args[2])
    add_balance(target_id, -amount)
    log_admin_action(message.from_user.id, "remove_money", target_id, f"-{amount}")
    await message.reply(f"✅ Снято {amount} 🪙 с {args[1]}")

@router.message(Command("add_xp"))
@admin_only
async def cmd_add_xp(message: Message):
    args = message.text.split()
    if len(args) < 3 or not args[2].isdigit():
        await message.reply("Использование: /add_xp @username [количество]")
        return
    target_id = find_user_by_username(args[1])
    if not target_id:
        await message.reply("❌ Пользователь не найден.")
        return
    amount = int(args[2])
    add_xp(target_id, amount)
    log_admin_action(message.from_user.id, "add_xp", target_id, str(amount))
    await message.reply(f"✅ +{amount} XP начислено {args[1]}")

@router.message(Command("reset_inventory"))
@admin_only
async def cmd_reset_inventory(message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.reply("Использование: /reset_inventory @username")
        return
    target_id = find_user_by_username(args[1])
    if not target_id:
        await message.reply("❌ Пользователь не найден.")
        return
    conn = get_conn(); c = conn.cursor()
    c.execute("DELETE FROM inventory WHERE user_id=?", (target_id,))
    conn.commit(); conn.close()
    log_admin_action(message.from_user.id, "reset_inventory", target_id)
    await message.reply(f"✅ Инвентарь {args[1]} очищен.")

@router.message(Command("reset_daily"))
@admin_only
async def cmd_reset_daily(message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.reply("Использование: /reset_daily @username")
        return
    target_id = find_user_by_username(args[1])
    if not target_id:
        await message.reply("❌ Пользователь не найден.")
        return
    conn = get_conn(); c = conn.cursor()
    c.execute("UPDATE users SET daily_ts=0 WHERE user_id=?", (target_id,))
    conn.commit(); conn.close()
    log_admin_action(message.from_user.id, "reset_daily", target_id)
    await message.reply(f"✅ Ежедневный бонус {args[1]} сброшен.")

@router.message(Command("broadcast"))
@admin_only
async def cmd_broadcast(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("Использование: /broadcast [текст сообщения]")
        return
    text = args[1]
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    all_users = [row[0] for row in c.fetchall()]
    conn.close()

    sent, failed = 0, 0
    for uid in all_users:
        try:
            await bot.send_message(uid, f"📢 <b>Сообщение от администратора:</b>\n\n{text}", parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1
    log_admin_action(message.from_user.id, "broadcast", 0, f"sent={sent}, failed={failed}")
    await message.reply(f"📢 Рассылка завершена. Отправлено: {sent}, ошибок: {failed}.")

# ─────────────────────────── АДМИН-ПАНЕЛЬ ─────────────────────────

def admin_panel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Статистика бота", callback_data="admin_stats"),
            InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin_users"),
        ],
        [
            InlineKeyboardButton(text="💰 Выдать монеты", callback_data="admin_give_money"),
            InlineKeyboardButton(text="🏅 Выдать достижение", callback_data="admin_give_ach"),
        ],
        [
            InlineKeyboardButton(text="📦 Выдать предмет", callback_data="admin_give_item"),
            InlineKeyboardButton(text="💾 Создать бэкап", callback_data="admin_backup"),
        ],
        [
            InlineKeyboardButton(text="📨 Рассылка", callback_data="admin_broadcast"),
        ],
    ])

@router.message(Command("admin_panel"))
@admin_only
async def cmd_admin_panel(message: Message):
    await message.reply("🛠️ <b>АДМИН-ПАНЕЛЬ</b>\n\nВыбери действие:", parse_mode="HTML", reply_markup=admin_panel_kb())


@router.callback_query(F.data == "admin_cancel")
async def admin_cancel(call: CallbackQuery):
    print(f"DEBUG: admin_cancel вызван для {call.from_user.id}")  # можно удалить после проверки
    if call.from_user.id in admin_actions:
        del admin_actions[call.from_user.id]
    await call.message.edit_text("🛠️ <b>АДМИН-ПАНЕЛЬ</b>\n\nВыбери действие:", parse_mode="HTML", reply_markup=admin_panel_kb())
    await call.answer()


@router.callback_query(F.data.startswith("admin_"))
async def admin_callback(call: CallbackQuery):
    # Пропускаем admin_cancel, чтобы его обработал отдельный хендлер
    if call.data == "admin_cancel":
        return

    if not is_admin(call.from_user.id):
        await call.answer("🚫 Нет доступа!", show_alert=True)
        return

    data = call.data  # e.g. "admin_give_ach_3" or "admin_stats"
    parts = data.split("_")  # ["admin", "give", "ach", "3"] or ["admin", "stats"]

    # ── Выдача конкретного достижения: admin_give_ach_<id> ──
    if data.startswith("admin_give_ach_") and len(parts) == 4 and parts[3].isdigit():
        ach_id = int(parts[3])
        if ach_id not in ACHIEVEMENTS:
            await call.answer("❌ Несуществующее достижение!", show_alert=True)
            return
        admin_actions[call.from_user.id] = {"action": "give_ach", "ach_id": ach_id, "step": 1}
        await call.message.edit_text(
            f"🏅 Введите @username пользователя, которому выдать достижение «{ACHIEVEMENTS[ach_id]['name']}»:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]])
        )
        await call.answer()
        return

    # ── Выдача конкретного предмета: admin_give_item_<id> ──
    if data.startswith("admin_give_item_") and len(parts) == 4 and parts[3].isdigit():
        item_id = int(parts[3])
        if item_id not in SHOP_ITEMS:
            await call.answer("❌ Несуществующий предмет!", show_alert=True)
            return
        admin_actions[call.from_user.id] = {"action": "give_item", "item_id": item_id, "step": 1}
        await call.message.edit_text(
            f"📦 Введите @username пользователя, которому выдать предмет «{SHOP_ITEMS[item_id]['name']}»:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]])
        )
        await call.answer()
        return

    # ── Остальные действия: action = часть после "admin_" ──
    action = "_".join(parts[1:])  # всё после "admin_"

    if action == "stats":
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM marriages")
        marriages = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM custom_rp")
        custom_rp = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM achievements")
        achievements = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM elo_ratings WHERE games_played > 0")
        duelists = c.fetchone()[0]
        conn.close()
        await call.message.edit_text(
            f"📊 <b>СТАТИСТИКА БОТА</b>\n\n"
            f"👥 Пользователей: <b>{users}</b>\n"
            f"💍 Браков: <b>{marriages}</b>\n"
            f"🎭 Кастомных РП: <b>{custom_rp}</b>\n"
            f"🏅 Достижений выдано: <b>{achievements}</b>\n"
            f"⚔️ Участников дуэлей: <b>{duelists}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]])
        )
    elif action == "users":
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT user_id, username, xp, level, balance FROM users ORDER BY xp DESC LIMIT 20")
        rows = c.fetchall()
        conn.close()
        text = "👥 <b>ТОП-20 ПОЛЬЗОВАТЕЛЕЙ (по XP)</b>\n\n"
        for i, (uid, name, xp, lvl, bal) in enumerate(rows, 1):
            display = name or str(uid)
            text += f"{i}. {display} — ур.{lvl} ({xp} XP) | {bal}🪙\n"
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]]))
    elif action == "back":
        await call.message.edit_text("🛠️ <b>АДМИН-ПАНЕЛЬ</b>\n\nВыбери действие:", parse_mode="HTML", reply_markup=admin_panel_kb())
    elif action == "backup":
        await call.message.edit_text("💾 Создаю бэкап...")
        if backup_database():
            await call.message.edit_text("✅ Бэкап успешно создан!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]]))
        else:
            await call.message.edit_text("❌ Ошибка при создании бэкапа!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]]))
    elif action == "give_money":
        admin_actions[call.from_user.id] = {"action": "give_money", "step": 1}
        await call.message.edit_text(
            "💰 Введите @username и сумму через пробел\nПример: @user 100\n\nИли нажмите Отмена.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]])
        )
    elif action == "give_ach":  # Список достижений
        buttons = []
        for ach_id, ach in ACHIEVEMENTS.items():
            buttons.append([InlineKeyboardButton(text=f"{ach['icon']} {ach['name']}", callback_data=f"admin_give_ach_{ach_id}")])
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")])
        await call.message.edit_text(
            "🏅 Выбери достижение для выдачи:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
    elif action == "give_item":  # Список предметов
        buttons = []
        for item_id, item in SHOP_ITEMS.items():
            if item_id == 13:
                continue
            buttons.append([InlineKeyboardButton(text=f"{item['name']}", callback_data=f"admin_give_item_{item_id}")])
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")])
        await call.message.edit_text(
            "📦 Выбери предмет для выдачи:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
    elif action == "broadcast":
        admin_actions[call.from_user.id] = {"action": "broadcast", "step": 1}
        await call.message.edit_text(
            "📨 Введите сообщение для рассылки (бот отправит его всем пользователям):\n\nИли нажмите Отмена.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]])
        )
    await call.answer()


@router.message(AdminInputFilter())
async def admin_input_handler(message: Message):
    """Обрабатывает ввод от админа в рамках админ-панели (только для админов с активным действием)."""
    user_id = message.from_user.id
    # Уже отфильтровано, что user_id в admin_actions
    action_data = admin_actions[user_id]
    action = action_data["action"]
    step = action_data.get("step", 1)
    print(f"DEBUG: admin_input_handler: action={action}, step={step}, text={message.text}")

    if action == "give_money" and step == 1:
        parts = message.text.split()
        if len(parts) != 2 or not parts[0].startswith("@") or not parts[1].isdigit():
            await message.reply("❌ Неверный формат. Нужно: @username сумма")
            return
        target_id = find_user_by_username(parts[0])
        if not target_id:
            await message.reply("❌ Пользователь не найден.")
            return
        amount = int(parts[1])
        add_balance(target_id, amount)
        log_admin_action(user_id, "add_money", target_id, str(amount))
        await message.reply(f"✅ Выдано {amount} монет пользователю {parts[0]}")
        del admin_actions[user_id]
        await message.answer("🛠️ <b>АДМИН-ПАНЕЛЬ</b>\n\nВыбери действие:", parse_mode="HTML", reply_markup=admin_panel_kb())

    elif action == "give_ach" and step == 1:
        username = message.text.strip()
        if not username.startswith("@"):
            await message.reply("❌ Введите username с @")
            return
        target_id = find_user_by_username(username)
        if not target_id:
            await message.reply("❌ Пользователь не найден.")
            return
        ach_id = action_data["ach_id"]
        if not has_achievement(target_id, ach_id):
            grant_achievement(target_id, ach_id)
            log_admin_action(user_id, "give_achievement", target_id, f"ach_{ach_id}")
            await message.reply(f"✅ Выдано достижение «{ACHIEVEMENTS[ach_id]['name']}» пользователю {username}")
        else:
            await message.reply(f"⚠️ У пользователя {username} уже есть это достижение.")
        del admin_actions[user_id]
        await message.answer("🛠️ <b>АДМИН-ПАНЕЛЬ</b>\n\nВыбери действие:", parse_mode="HTML", reply_markup=admin_panel_kb())

    elif action == "give_item" and step == 1:
        username = message.text.strip()
        if not username.startswith("@"):
            await message.reply("❌ Введите username с @")
            return
        target_id = find_user_by_username(username)
        if not target_id:
            await message.reply("❌ Пользователь не найден.")
            return
        item_id = action_data["item_id"]
        _add_to_inventory(target_id, item_id)
        log_admin_action(user_id, "give_item", target_id, f"item_{item_id}")
        await message.reply(f"✅ Выдан предмет «{SHOP_ITEMS[item_id]['name']}» пользователю {username}")
        del admin_actions[user_id]
        await message.answer("🛠️ <b>АДМИН-ПАНЕЛЬ</b>\n\nВыбери действие:", parse_mode="HTML", reply_markup=admin_panel_kb())

    elif action == "broadcast" and step == 1:
        text = message.text
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT user_id FROM users")
        users = [row[0] for row in c.fetchall()]
        conn.close()

        sent = 0
        for uid in users:
            try:
                await bot.send_message(uid, f"📢 <b>Сообщение от администратора:</b>\n\n{text}", parse_mode="HTML")
                sent += 1
                await asyncio.sleep(0.05)
            except:
                pass
        await message.reply(f"📢 Рассылка завершена. Отправлено: {sent} пользователям.")
        del admin_actions[user_id]
        await message.answer("🛠️ <b>АДМИН-ПАНЕЛЬ</b>\n\nВыбери действие:", parse_mode="HTML", reply_markup=admin_panel_kb())


@router.message(Command("backup"))
@admin_only
async def cmd_backup(message: Message):
    """Создать бэкап базы данных (только для админа)"""
    await message.reply("💾 Создаю бэкап базы данных...")
    if backup_database():
        await message.reply("✅ Бэкап успешно создан!")
    else:
        await message.reply("❌ Ошибка при создании бэкапа. Проверь логи.")

# ═══════════════════════════════════════════════════════════════════
