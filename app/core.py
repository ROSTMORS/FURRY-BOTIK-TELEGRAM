import logging
import os

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import BaseFilter
from aiogram.types import Message
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN is None! Check Railway Variables")

_admin_env = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: list[int] = [int(x.strip()) for x in _admin_env.split(",") if x.strip().isdigit()]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()

DB_FILE = "/app/data/database.db"

admin_actions = {}

class AdminInputFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id in admin_actions
