
import random
from aiogram import F
from aiogram.types import Message
from aiogram.filters import Command

from app.core import router
from app.shared import add_xp, get_marriage

# ───────── SETTINGS ─────────
NSFW_ENABLED = set()

NSFW_ACTIONS = {
    "секс","трахнуть","отдаться","интим","близость"
}

RARE_CHANCE = 0.05

MARRIAGE_BONUS = {
    "обнять":10,
    "поцеловать":12,
    "прижать":10,
    "погладить":8
}

rp_combo = {}

# ───────── ACTIONS ─────────
RP_ACTIONS = {
    "обнять":["нежно обнял","крепко обнял","обнял со спины"],
    "поцеловать":["нежно поцеловал","тепло поцеловал"],
    "погладить":["ласково погладил","мягко погладил"],
    "прижать":["прижал к себе","сильно прижал"],
    "похвалить":["тепло похвалил","искренне похвалил"],
    "пнуть":["пнул"],
    "ударить":["ударил"]
}

NSFW_TEXTS = [
    "провёл страстный момент с",
    "оказался в очень близкой ситуации с",
    "погрузился в атмосферу вместе с",
    "разделил тёплый и интимный момент с"
]

# ───────── NSFW ─────────
@router.message(Command("nsfw_on"))
async def nsfw_on(message: Message):
    NSFW_ENABLED.add(message.chat.id)
    await message.reply("🔞 NSFW включён")

@router.message(Command("nsfw_off"))
async def nsfw_off(message: Message):
    NSFW_ENABLED.discard(message.chat.id)
    await message.reply("🔕 NSFW отключён")

# ───────── HANDLER ─────────
@router.message(F.text)
async def rp_handler(message: Message):
    word = message.text.lower().split()[0]

    if word not in RP_ACTIONS and word not in NSFW_ACTIONS:
        return

    target = None

    if message.reply_to_message:
        target = message.reply_to_message.from_user
    elif message.entities:
        for e in message.entities:
            if e.type == "mention":
                target = message.text[e.offset:e.offset+e.length]
                break

    if not target:
        return await message.reply("❗ Укажи цель (reply или @user)")

    actor = message.from_user

    # NSFW
    if word in NSFW_ACTIONS:
        if message.chat.id not in NSFW_ENABLED:
            return await message.reply("🔞 NSFW отключён")
        action = random.choice(NSFW_TEXTS)
    else:
        action = random.choice(RP_ACTIONS[word])

    xp = random.randint(3,6)

    # marriage bonus
    marriage = get_marriage(actor.id)
    if marriage:
        partner = marriage["user2_id"] if marriage["user1_id"]==actor.id else marriage["user1_id"]
        if hasattr(target,"id") and target.id == partner:
            xp += MARRIAGE_BONUS.get(word,0)

    # rare
    rare = ""
    if random.random() < RARE_CHANCE:
        bonus = random.randint(10,20)
        xp += bonus
        rare = f"\n✨ Особое взаимодействие! +{bonus} XP"

    # combo
    key = (actor.id, getattr(target,"id",0))
    rp_combo.setdefault(key,[]).append(word)

    combo = ""
    if len(rp_combo[key])>=3:
        xp += 15
        combo = "\n💞 Комбо! +15 XP"
        rp_combo[key]=[]

    add_xp(actor.id,xp)

    actor_name = actor.first_name
    target_name = target.first_name if hasattr(target,"first_name") else target

    await message.reply(
        f"🤝 {actor_name} {action} {target_name}\n"
        f"💫 +{xp} XP{rare}{combo}"
    )
