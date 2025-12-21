import os
import sqlite3
from datetime import datetime, time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    Defaults,
    MessageHandler,
    filters,
)

# =========================
# Config
# =========================
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("Missing BOT_TOKEN in .env")

TZ = ZoneInfo("Asia/Dhaka")
REMINDER_6PM = time(18, 0, tzinfo=TZ)     # 6:00 PM Dhaka
REMINDER_1150 = time(23, 50, tzinfo=TZ)   # 11:50 PM Dhaka

HELP_TEXT = (
    "✅ Commands:\n"
    "• /add <task>   — Add a task for today\n"
    "• /today        — View today’s tasks\n"
    "• /checkin      — Start final check-in now\n"
    "• /del <id>     — Delete a task by id\n"
    "• /reset        — Delete all tasks for today\n"
    "• /note <text>  — Save a short note (your own feedback)\n"
    "• /help         — Show help\n"
)

HOW_IT_WORKS_MD = (
    "✨ *Welcome to RemindMe Bot* 😊\n\n"
    "I help you plan your day and do a quick nightly check-in.\n\n"
    "🧩 *How to use:*\n"
    "1) Add tasks:  `/add <task>`\n"
    "2) View tasks: `/today`\n"
    "3) Night check-in: `/checkin` (or wait for 11:50 PM)\n\n"
    "⏰ *Daily reminders (Asia/Dhaka):*\n"
    "• 6:00 PM — Task reminder\n"
    "• 11:50 PM — Final check-in (tap buttons + Finalize)\n\n"
    "🚀 *Quick start:*\n"
    "• `/add Study 1 hour`\n"
    "• `/add Gym`\n"
    "• `/today`\n\n"
    "Type */help* to see the full command list."
)

TEXT_ONLY_NOTICE = (
    "⚠️ I’m a text-based bot.\n"
    "I can’t read photos, videos, files, or voice notes.\n\n"
    "Please use commands like:\n"
    "• /add <task>\n"
    "• /today\n"
    "• /checkin\n"
    "• /help"
)

# =========================
# DB (SQLite)
# =========================
conn = sqlite3.connect("data.db", check_same_thread=False)
conn.row_factory = sqlite3.Row

conn.executescript(
    """
CREATE TABLE IF NOT EXISTS users (
  user_id INTEGER PRIMARY KEY,
  chat_id INTEGER NOT NULL,
  last_6pm_date TEXT,
  last_1150_date TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
  task_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  date TEXT NOT NULL,          -- YYYY-MM-DD (Dhaka)
  text TEXT NOT NULL,
  done INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS notes (
  user_id INTEGER NOT NULL,
  date TEXT NOT NULL,
  note TEXT NOT NULL,
  PRIMARY KEY(user_id, date)
);

CREATE INDEX IF NOT EXISTS idx_tasks_user_date ON tasks(user_id, date);
"""
)
conn.commit()


# =========================
# Helpers
# =========================
def now_dhaka() -> datetime:
    return datetime.now(TZ)


def today_str() -> str:
    return now_dhaka().date().isoformat()


def upsert_user(user_id: int, chat_id: int) -> None:
    conn.execute(
        """
INSERT INTO users(user_id, chat_id) VALUES (?, ?)
ON CONFLICT(user_id) DO UPDATE SET chat_id=excluded.chat_id
""",
        (user_id, chat_id),
    )
    conn.commit()


def list_tasks(user_id: int, date_str: str):
    cur = conn.execute(
        "SELECT task_id, text, done FROM tasks WHERE user_id=? AND date=? ORDER BY task_id ASC",
        (user_id, date_str),
    )
    return cur.fetchall()


def add_task(user_id: int, date_str: str, text: str) -> None:
    conn.execute("INSERT INTO tasks(user_id, date, text) VALUES (?, ?, ?)", (user_id, date_str, text))
    conn.commit()


def delete_task(task_id: int) -> None:
    conn.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))
    conn.commit()


def delete_all_tasks_for_day(user_id: int, date_str: str) -> int:
    cur = conn.execute("DELETE FROM tasks WHERE user_id=? AND date=?", (user_id, date_str))
    conn.commit()
    return cur.rowcount


def toggle_task(task_id: int) -> None:
    conn.execute("UPDATE tasks SET done = CASE done WHEN 1 THEN 0 ELSE 1 END WHERE task_id=?", (task_id,))
    conn.commit()


def task_belongs_to_user_today(user_id: int, task_id: int, date_str: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM tasks WHERE user_id=? AND date=? AND task_id=? LIMIT 1",
        (user_id, date_str, task_id),
    )
    return cur.fetchone() is not None


def set_last_sent(user_id: int, which: str, date_str: str) -> None:
    if which == "6pm":
        conn.execute("UPDATE users SET last_6pm_date=? WHERE user_id=?", (date_str, user_id))
    elif which == "1150":
        conn.execute("UPDATE users SET last_1150_date=? WHERE user_id=?", (date_str, user_id))
    conn.commit()


def due_users(which: str, date_str: str):
    if which == "6pm":
        cur = conn.execute(
            "SELECT user_id, chat_id FROM users WHERE last_6pm_date IS NULL OR last_6pm_date <> ?",
            (date_str,),
        )
    else:
        cur = conn.execute(
            "SELECT user_id, chat_id FROM users WHERE last_1150_date IS NULL OR last_1150_date <> ?",
            (date_str,),
        )
    return cur.fetchall()


def set_note(user_id: int, date_str: str, note: str) -> None:
    conn.execute(
        """
INSERT INTO notes(user_id, date, note) VALUES (?, ?, ?)
ON CONFLICT(user_id, date) DO UPDATE SET note=excluded.note
""",
        (user_id, date_str, note),
    )
    conn.commit()


def get_note(user_id: int, date_str: str) -> str | None:
    cur = conn.execute("SELECT note FROM notes WHERE user_id=? AND date=?", (user_id, date_str))
    row = cur.fetchone()
    return row["note"] if row else None


def delete_note(user_id: int, date_str: str) -> None:
    conn.execute("DELETE FROM notes WHERE user_id=? AND date=?", (user_id, date_str))
    conn.commit()


def clamp(s: str, n: int = 32) -> str:
    s = s.strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def build_checkin_text(tasks, date_str: str) -> str:
    total = len(tasks)
    done = sum(1 for t in tasks if t["done"] == 1)
    return (
        f"🌙 Final Check-in — {date_str}\n"
        f"✅ Done: {done}/{total}\n\n"
        f"Tap buttons to toggle Done/Not done, then press Finalize."
    )


def build_checkin_keyboard(tasks) -> InlineKeyboardMarkup:
    rows = []
    for t in tasks:
        prefix = "✅" if t["done"] == 1 else "⬜"
        rows.append([InlineKeyboardButton(f"{prefix} {clamp(t['text'])}", callback_data=f"t:{t['task_id']}")])

    rows.append(
        [
            InlineKeyboardButton("📌 Finalize", callback_data="finalize"),
            InlineKeyboardButton("📋 Summary", callback_data="summary"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def feedback_text(done: int, total: int) -> str:
    if total == 0:
        return "No tasks were set today. Tomorrow, start with 1–2 small tasks 😊"
    if done == total:
        return "🔥 Amazing! You completed everything. Keep it up ✅"
    ratio = done / total
    if ratio >= 0.7:
        return "👏 Great job! You were very close — tomorrow you’ll crush it ✅"
    if ratio > 0:
        return "👍 Good effort. Try smaller tasks to build momentum 😊"
    return "💛 It’s okay. Tomorrow: start with one tiny task first, then build from there."


async def send_6pm_reminder(app, chat_id: int, user_id: int, date_str: str):
    tasks = list_tasks(user_id, date_str)
    if not tasks:
        await app.bot.send_message(
            chat_id,
            f"⏰ 6:00 PM Reminder ({date_str})\nYou have not added any tasks today.\nUse /add <task> to add tasks.",
        )
        return

    lines = [f"{t['task_id']}. {'✅' if t['done'] else '⬜'} {t['text']}" for t in tasks]
    await app.bot.send_message(chat_id, f"⏰ 6:00 PM Reminder ({date_str})\nHere are your tasks:\n" + "\n".join(lines))


async def send_1150_checkin(app, chat_id: int, user_id: int, date_str: str):
    tasks = list_tasks(user_id, date_str)
    if not tasks:
        await app.bot.send_message(chat_id, f"🌙 11:50 PM Check-in ({date_str})\nNo tasks were set today.")
        return

    await app.bot.send_message(chat_id, build_checkin_text(tasks, date_str), reply_markup=build_checkin_keyboard(tasks))


# =========================
# Commands
# =========================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    upsert_user(user_id, chat_id)
    await update.message.reply_text(HOW_IT_WORKS_MD, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT)


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    upsert_user(user_id, chat_id)

    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("Usage: /add <task>\nType /help to see commands.")
        return

    d = today_str()
    add_task(user_id, d, text)
    await update.message.reply_text(f"✅ Added for today ({d}): {text}\nType /help to see commands.")


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    d = today_str()
    tasks = list_tasks(user_id, d)

    if not tasks:
        await update.message.reply_text(f"Today ({d}) you have no tasks. Use /add <task>.\nType /help to see commands.")
        return

    lines = [f"{t['task_id']}. {'✅' if t['done'] else '⬜'} {t['text']}" for t in tasks]
    note = get_note(user_id, d)

    msg = f"🗓️ {d} — Your Tasks\n" + "\n".join(lines)
    if note:
        msg += f"\n\n📝 Your note: {note}"
    else:
        msg += "\n\nTip: add a note with /note <text>"
    msg += "\n\nType /help to see commands."

    await update.message.reply_text(msg)


async def del_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    upsert_user(user_id, chat_id)

    if not context.args:
        await update.message.reply_text("Usage: /del <task_id> (see /today)\nType /help to see commands.")
        return

    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Usage: /del <task_id> (must be a number)\nType /help to see commands.")
        return

    d = today_str()
    if not task_belongs_to_user_today(user_id, task_id, d):
        await update.message.reply_text("That task ID is not in today’s list. Use /today.\nType /help to see commands.")
        return

    delete_task(task_id)
    await update.message.reply_text(f"🗑️ Deleted task {task_id}.\nType /help to see commands.")


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    upsert_user(user_id, chat_id)

    d = today_str()
    deleted = delete_all_tasks_for_day(user_id, d)
    delete_note(user_id, d)
    await update.message.reply_text(f"🔄 Reset complete for {d}. Deleted {deleted} task(s).\nType /help to see commands.")


async def note_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    upsert_user(user_id, chat_id)

    note = " ".join(context.args).strip()
    if not note:
        await update.message.reply_text("Usage: /note <your short feedback>\nType /help to see commands.")
        return

    d = today_str()
    set_note(user_id, d, note)
    await update.message.reply_text(f"📝 Saved note for {d}.\nType /help to see commands.")


async def checkin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    upsert_user(user_id, chat_id)

    d = today_str()
    await send_1150_checkin(context.application, chat_id, user_id, d)


# =========================
# Buttons
# =========================
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    d = today_str()
    data = query.data or ""

    if data.startswith("t:"):
        task_id = int(data.split(":", 1)[1])

        if not task_belongs_to_user_today(user_id, task_id, d):
            await query.answer("Not allowed.", show_alert=True)
            return

        toggle_task(task_id)
        tasks = list_tasks(user_id, d)

        await query.edit_message_text(build_checkin_text(tasks, d), reply_markup=build_checkin_keyboard(tasks))
        return

    if data == "summary":
        tasks = list_tasks(user_id, d)
        total = len(tasks)
        done = sum(1 for t in tasks if t["done"] == 1)
        await query.answer(f"Done: {done}/{total}")
        return

    if data == "finalize":
        tasks = list_tasks(user_id, d)
        total = len(tasks)
        done = sum(1 for t in tasks if t["done"] == 1)
        note = get_note(user_id, d)

        msg = f"✅ Final result for {d}: {done}/{total}\n{feedback_text(done, total)}"
        if note:
            msg += f"\n\n📝 Your note: {note}"
        msg += "\n\nType /help to see commands."

        await query.message.reply_text(msg)
        return


# =========================
# Text-only enforcement handlers
# =========================
async def any_text_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HOW_IT_WORKS_MD, parse_mode="Markdown")


async def non_text_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(TEXT_ONLY_NOTICE)


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("I didn’t recognize that command.\n\nType /help to see commands.")


# =========================
# Scheduled jobs
# =========================
async def job_6pm(context: ContextTypes.DEFAULT_TYPE):
    app = context.application
    d = today_str()
    for u in due_users("6pm", d):
        try:
            await send_6pm_reminder(app, u["chat_id"], u["user_id"], d)
            set_last_sent(u["user_id"], "6pm", d)
        except Exception:
            pass


async def job_1150(context: ContextTypes.DEFAULT_TYPE):
    app = context.application
    d = today_str()
    for u in due_users("1150", d):
        try:
            await send_1150_checkin(app, u["chat_id"], u["user_id"], d)
            set_last_sent(u["user_id"], "1150", d)
        except Exception:
            pass


# =========================
# Main
# =========================
def main():
    defaults = Defaults(tzinfo=TZ)
    app = ApplicationBuilder().token(TOKEN).defaults(defaults).build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("add", add_command))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("del", del_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("note", note_command))
    app.add_handler(CommandHandler("checkin", checkin_command))

    # Buttons
    app.add_handler(CallbackQueryHandler(on_button))

    # Non-text content -> show text-only notice (PTB v22+ compatible)
    app.add_handler(
        MessageHandler(
            (
                filters.PHOTO
                | filters.VIDEO
                | filters.VOICE
                | filters.AUDIO
                | filters.Document.ALL
                | filters.Sticker.ALL
                | filters.ANIMATION
                | filters.VIDEO_NOTE
                | filters.CONTACT
                | filters.LOCATION
            ),
            non_text_reply,
        )
    )

    # Normal text (non-commands) -> guide
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, any_text_reply))

    # Unknown commands (must be LAST)
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # Jobs
    app.job_queue.run_daily(job_6pm, time=REMINDER_6PM)
    app.job_queue.run_daily(job_1150, time=REMINDER_1150)

    run_mode = os.getenv("RUN_MODE", "polling").lower().strip()

    if run_mode == "webhook":
        port = int(os.getenv("PORT", "8000"))
        webhook_path = os.getenv("WEBHOOK_PATH", "remindme-hook").strip().strip("/")
        base_url = os.getenv("WEBHOOK_BASE_URL", "").rstrip("/")

        if not base_url:
            raise RuntimeError("Missing WEBHOOK_BASE_URL")

        webhook_url = f"{base_url}/{webhook_path}"

        print(f"Starting webhook on 0.0.0.0:{port} path=/{webhook_path}")
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=webhook_path,
            webhook_url=webhook_url,
        )
    else:
        print("Starting polling...")
        app.run_polling()


if __name__ == "__main__":
    main()
