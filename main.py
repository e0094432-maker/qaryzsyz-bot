import asyncio
import logging
import os

# Загружаем переменные из .env файла (если он есть)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Если python-dotenv не установлен — не критично, переменные могут быть заданы напрямую
    pass

from aiohttp import web
from aiogram import Bot, Dispatcher, Router as AiogramRouter
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommandScopeDefault, Message
from aiogram.filters import Command, CommandStart
from handlers import router as main_router
from stats import get_stats, _conn
from datetime import datetime

logging.basicConfig(level=logging.INFO)

BOT_TOKEN       = "8783471683:AAHOD8ihKIXAlRhnWW48BP88I0Ll6_KIw0A"
ADMIN_BOT_TOKEN = "8533532660:AAFhdVwLT0PsfVsCoU_QTX7JE8wHTruVbNQ"
ADMIN_ID        = 7520383376
PORT            = int(os.environ.get("PORT", 8080))

# Проверяем наличие API-ключа Anthropic
if not os.environ.get("ANTHROPIC_API_KEY"):
    print("⚠️  ВНИМАНИЕ: ANTHROPIC_API_KEY не задан!")
    print("   AI-юрист работать не будет.")
    print("   Создайте файл .env с содержимым:")
    print("   ANTHROPIC_API_KEY=sk-ant-api03-ВАШ_КЛЮЧ")
else:
    print("✅ ANTHROPIC_API_KEY загружен")


# ── Веб-сервер для UptimeRobot ─────────────────────────────────
async def handle(request):
    return web.Response(text="OK")


async def run_web():
    app = web.Application()
    app.router.add_get("/", handle)
    app.router.add_get("/ping", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"✅ Веб-сервер запущен на порту {PORT}")


# ── Админ-бот ──────────────────────────────────────────────────
admin_router = AiogramRouter()

SERVICE_NAMES = {
    "restr": "∞ Реструктуризация", "cancel_in": "📝 Отмена ИН",
    "cancel_court": "⚖️ Отмена суда", "bankruptcy_out": "🏳️ Внесудебное",
    "bankruptcy_court": "⚖️ Судебное", "zero_change": "📄 Изменение нуля",
    "ai_lawyer": "🤖 AI-юрист", "ai_lawyer_msg": "🤖 AI-сообщение",
    "start": "👋 Старт",
}


@admin_router.message(CommandStart())
async def admin_start(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("👋 Привет, Эмир!\n\nКоманды:\n/stats — полная статистика\n/today — только за сегодня")


@admin_router.message(Command("stats"))
async def admin_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(get_stats(), parse_mode="Markdown")


@admin_router.message(Command("today"))
async def admin_today(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
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
    lines = [f"📅 *Сегодня: {total[0]} обращений, {total[1]} польз.*\n"]
    for svc, cnt in rows:
        lines.append(f"  {SERVICE_NAMES.get(svc, svc)}: {cnt}")
    await message.answer("\n".join(lines), parse_mode="Markdown")


# ── Запуск всего ───────────────────────────────────────────────
async def run_main_bot():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(main_router)
    await bot.delete_my_commands(scope=BotCommandScopeDefault())
    print("✅ Основной бот запущен!")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


async def run_admin_bot():
    bot = Bot(token=ADMIN_BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin_router)
    print("✅ Админ-бот запущен!")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


async def main():
    await asyncio.gather(
        run_web(),
        run_main_bot(),
        run_admin_bot(),
    )


if __name__ == "__main__":
    asyncio.run(main())
