"""
Админ-бот для статистики @AnalyticEmir_bot
Запускать отдельно: python admin_bot.py
"""
import asyncio
import logging
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.fsm.storage.memory import MemoryStorage

from stats import get_stats

logging.basicConfig(level=logging.INFO)

ADMIN_BOT_TOKEN = "8533532660:AAFhdVwLT0PsfVsCoU_QTX7JE8wHTruVbNQ"
ADMIN_ID        = 7520383376  # только ты

router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        "👋 Привет, Эмир!\n\n"
        "Команды:\n"
        "/stats — полная статистика\n"
        "/today — только за сегодня"
    )

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    text = get_stats()
    await message.answer(text, parse_mode="Markdown")

@router.message(Command("today"))
async def cmd_today(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    from stats import _conn
    from datetime import datetime
    conn = _conn()
    today = datetime.now().replace(hour=0, minute=0, second=0)
    rows = conn.execute(
        "SELECT service, COUNT(*) FROM events WHERE created_at >= ? GROUP BY service ORDER BY COUNT(*) DESC",
        (today.strftime("%Y-%m-%d %H:%M:%S"),)
    ).fetchall()
    total = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT user_id) FROM events WHERE created_at >= ?",
        (today.strftime("%Y-%m-%d %H:%M:%S"),)
    ).fetchone()
    conn.close()

    SERVICE_NAMES = {
        "restr":            "∞ Реструктуризация",
        "cancel_in":        "📝 Отмена ИН",
        "cancel_court":     "⚖️ Отмена суда",
        "bankruptcy_out":   "🏳️ Внесудебное банкротство",
        "bankruptcy_court": "⚖️ Судебное банкротство",
        "zero_change":      "📄 Изменение нуля",
        "start":            "👋 Старт /start",
    }

    lines = [f"📅 *Сегодня: {total[0]} обращений, {total[1]} пользователей*\n"]
    for svc, cnt in rows:
        lines.append(f"  {SERVICE_NAMES.get(svc, svc)}: {cnt}")
    await message.answer("\n".join(lines), parse_mode="Markdown")

async def main():
    bot = Bot(token=ADMIN_BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    print("✅ Админ-бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
