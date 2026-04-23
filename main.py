import asyncio

from app.core import ADMIN_IDS, bot, dp, logger, router
from app.db import init_db
from app.handlers import scheduled_backup

dp.include_router(router)

async def main():
    init_db()
    if not ADMIN_IDS:
        logger.warning("⚠️  ADMIN_IDS не заданы! Добавь свой ID в .env: ADMIN_IDS=123456789")

    asyncio.create_task(scheduled_backup())

    logger.info("Бот v3.0 запускается...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
