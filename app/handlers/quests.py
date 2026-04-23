from aiogram.filters import Command
from aiogram.types import Message

from app.shared import *


@router.message(Command("quests"))
async def cmd_quests(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    quest_map = get_user_quests(message.from_user.id)
    lines = ["🧩 <b>Ваши квесты</b>", "", "<b>📅 Ежедневные</b>"]
    lines.extend(format_quest_lines(quest_map["daily"]))
    lines.append("")
    lines.append("<b>🗓️ Недельные</b>")
    lines.extend(format_quest_lines(quest_map["weekly"]))
    lines.append("")
    lines.append("Забрать награды: /claim")
    await message.reply("\n".join(lines), parse_mode="HTML")


@router.message(Command("claim"))
async def cmd_claim(message: Message):
    ensure_user(message.from_user.id, message.from_user.username or message.from_user.full_name)
    claimed = claim_ready_quests(message.from_user.id)
    if not claimed:
        await message.reply("🎁 У вас пока нет готовых наград. Посмотреть квесты: /quests", parse_mode="HTML")
        return
    lines = ["🎁 <b>Награды за квесты получены!</b>", ""]
    for item in claimed:
        line = f"• <b>{item['title']}</b> — 💰 {item['reward_coins']} | ⭐ {item['reward_xp']}"
        if item["reward_item_id"]:
            reward_item = SHOP_ITEMS.get(item["reward_item_id"], {})
            line += f" | 🎒 {reward_item.get('name', 'Предмет')}"
        lines.append(line)
    await message.reply("\n".join(lines), parse_mode="HTML")
    await check_achievements(message.from_user.id, message)
