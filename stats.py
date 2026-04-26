import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats.db")


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   INTEGER,
            service   TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    return conn


def log_event(user_id: int, service: str):
    """Записываем обращение пользователя."""
    try:
        conn = _conn()
        conn.execute(
            "INSERT INTO events (user_id, service, created_at) VALUES (?, ?, ?)",
            (user_id, service, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"stats log_event error: {e}")


def get_stats() -> str:
    """Возвращает текстовый отчёт."""
    try:
        conn = _conn()
        now = datetime.now()

        def count(since: datetime):
            cur = conn.execute(
                "SELECT COUNT(*) FROM events WHERE created_at >= ?",
                (since.strftime("%Y-%m-%d %H:%M:%S"),)
            )
            return cur.fetchone()[0]

        def unique(since: datetime):
            cur = conn.execute(
                "SELECT COUNT(DISTINCT user_id) FROM events WHERE created_at >= ?",
                (since.strftime("%Y-%m-%d %H:%M:%S"),)
            )
            return cur.fetchone()[0]

        today     = now.replace(hour=0, minute=0, second=0)
        week_ago  = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)
        year_ago  = now - timedelta(days=365)

        # Общая статистика
        total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        total_u = conn.execute("SELECT COUNT(DISTINCT user_id) FROM events").fetchone()[0]

        services = conn.execute("""
            SELECT service, COUNT(*) as cnt
            FROM events
            GROUP BY service
            ORDER BY cnt DESC
        """).fetchall()

        top_users = conn.execute("""
            SELECT user_id, COUNT(*) as cnt
            FROM events
            GROUP BY user_id
            ORDER BY cnt DESC
            LIMIT 5
        """).fetchall()

        conn.close()

        SERVICE_NAMES = {
            "restr":            "∞ Реструктуризация",
            "cancel_in":        "📝 Отмена ИН",
            "cancel_court":     "⚖️ Отмена суда",
            "bankruptcy_out":   "🏳️ Внесудебное банкротство",
            "bankruptcy_court": "⚖️ Судебное банкротство",
            "zero_change":      "📄 Изменение нуля",
            "ai_lawyer":        "🤖 AI-юрист (вход)",
            "ai_lawyer_msg":    "🤖 AI-юрист (сообщение)",
            "start":            "👋 Старт /start",
        }

        lines = ["📊 *Статистика бота @Qaryzsyz_qoqam_Bot*\n"]
        lines.append(f"📅 Сегодня: *{count(today)}* обращений ({unique(today)} польз.)")
        lines.append(f"📆 За 7 дней: *{count(week_ago)}* обращений ({unique(week_ago)} польз.)")
        lines.append(f"🗓 За 30 дней: *{count(month_ago)}* обращений ({unique(month_ago)} польз.)")
        lines.append(f"📈 За год: *{count(year_ago)}* обращений ({unique(year_ago)} польз.)")
        lines.append(f"🏆 За всё время: *{total}* обращений, *{total_u}* уникальных пользователей")

        if services:
            lines.append("\n*По услугам (всё время):*")
            for svc, cnt in services:
                name = SERVICE_NAMES.get(svc, svc)
                lines.append(f"  {name}: {cnt}")

        if top_users:
            lines.append("\n*Топ-5 активных пользователей:*")
            for uid, cnt in top_users:
                lines.append(f"  ID {uid}: {cnt} обращений")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Ошибка получения статистики: {e}"
