import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault
from handlers import router

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = "8783471683:AAHOD8ihKIXAlRhnWW48BP88I0Ll6_KIw0A"

async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    # Убираем кнопку Menu — она мешает интерфейсу
    await bot.delete_my_commands(scope=BotCommandScopeDefault())

    print("✅ Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
