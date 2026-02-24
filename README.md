# RemindMe Telegram Bot (Daily Tasks + Nightly Check-in)

A lightweight **Telegram bot** (Python) to help you plan your day, get an evening reminder, and do a quick **end-of-day check-in**.

It stores your tasks in a local **SQLite** database (`data.db`) and uses `python-telegram-bot`’s **job queue** to schedule daily reminders.

---

## Features

- Add tasks for **today** and list them anytime
- Mark tasks as done during a **nightly check-in** using inline buttons
- Two automated reminders (Asia/Dhaka):
  - **6:00 PM** — task reminder (shows today’s tasks)
  - **11:50 PM** — final check-in (toggle done + finalize)
- Save a short daily note (`/note ...`)
- Ignores non-text messages (photos/voice/files) with a friendly notice

---

## Commands

- `/start` — Start the bot / register your chat
- `/help` — Show help + usage
- `/add <task>` — Add a task for today  
  Example: `/add Study 1 hour`
- `/today` — Show today’s tasks (with IDs)
- `/del <id>` — Delete a task by task ID  
  Example: `/del 3`
- `/reset` — Delete all tasks for today
- `/checkin` — Start final check-in now (also runs automatically at 11:50 PM)
- `/note <text>` — Save a short note for today

---
#Project structure
bot/
├─ bot.py # Telegram bot source
├─ requirements.txt # Python dependencies
├─ Dockerfile # Container setup
├─ data.db # SQLite database (auto-created/updated)

> **Tip:** Don’t commit real secrets. Keep `.env` local or use deployment secrets.

---

## Setup

### 1) Create a Telegram Bot Token
Create a bot via **@BotFather** on Telegram and copy the token.

### 2) Configure environment variables
Create/edit `.env` in the `bot/` folder:

```env
BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN_HERE
```

---

## Run Locally

### Option A — Run with Python

```bash
cd bot
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows (PowerShell)
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt
python bot.py
```

### Option B — Run with Docker

```bash
cd bot
docker build -t remindme-bot .
docker run --rm --env-file .env remindme-bot
```

---

## How Scheduling Works

- The bot uses **Asia/Dhaka** timezone.
- It schedules two daily jobs via the `python-telegram-bot` **job queue**:
  - 6:00 PM reminder (lists today’s tasks)
  - 11:50 PM nightly check-in (inline buttons to mark done + finalize)

---

## Database

SQLite file: `data.db` (created automatically).

Tables:

- `users` — stores `user_id`, `chat_id`, and last reminder/check-in dates
- `tasks` — tasks per user per date (YYYY-MM-DD in Dhaka), with `done` status
- `notes` — one note per user per date

---

## Troubleshooting

- **Missing token error:** Make sure `.env` exists and contains `BOT_TOKEN=...`
- **No reminders delivered:** The bot must be running continuously for scheduled jobs to fire.
- **Time seems off:** This bot is pinned to **Asia/Dhaka** (`ZoneInfo("Asia/Dhaka")`).

---

## License
@copyright Mussharat Monir Prottasha
