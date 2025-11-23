from keep_alive import keep_alive

keep_alive()
from dotenv import load_dotenv
load_dotenv()
import os
import json
import asyncio
import aiofiles
from datetime import date
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import nest_asyncio

# File to store goals and check-ins
GOAL_FILE = "goals.json"

# === Async Load/Save Helpers ===
async def load_data():
    """Load goals data from JSON file"""
    try:
        async with aiofiles.open(GOAL_FILE, "r") as f:
            contents = await f.read()
            return json.loads(contents)
    except FileNotFoundError:
        return {}

async def save_data(data):
    """Save goals data to JSON file"""
    async with aiofiles.open(GOAL_FILE, "w") as f:
        await f.write(json.dumps(data, indent=4))

# === Bot Command Handlers ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message with all commands"""
    await update.message.reply_text(
        "👋 Hi! I'm your accountability bot.\n\n"
        "📋 Commands:\n"
        "• /setgoals AIML DSA Gym - Set your daily goals\n"
        "• /checkin - Mark today as complete\n"
        "• /progress - See your progress\n"
        "• /setreminder - Set daily reminder time\n\n"
        "Let's get started with /setgoals!"
    )

async def set_goals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set user's daily goals"""
    user_id = str(update.effective_user.id)
    goals = context.args
    
    if not goals or all(g.strip() == "" for g in goals):
        await update.message.reply_text(
            "⚠️ Please specify your goals like:\n/setgoals AIML DSA Gym"
        )
        return
    
    data = await load_data()
    data[user_id] = {
        "goals": goals,
        "checkins": data.get(user_id, {}).get("checkins", {})
    }
    await save_data(data)
    await update.message.reply_text(f"🎯 Goals set: {', '.join(goals)}")

async def checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mark today as checked in"""
    user_id = str(update.effective_user.id)
    today = str(date.today())
    data = await load_data()

    if user_id not in data:
        await update.message.reply_text(
            "⚠️ You haven't set goals yet. Use /setgoals first."
        )
        return

    if today in data[user_id]["checkins"]:
        await update.message.reply_text("✅ You've already checked in today!")
    else:
        data[user_id]["checkins"][today] = "✅"
        await save_data(data)
        await update.message.reply_text(
            "🔥 Check-in saved for today! Keep it up!"
        )

async def show_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's progress and stats"""
    user_id = str(update.effective_user.id)
    data = await load_data()

    if user_id not in data:
        await update.message.reply_text(
            "⚠️ You haven't set any goals yet. Use /setgoals first."
        )
        return

    user_data = data[user_id]
    goals = ', '.join(user_data['goals'])
    checkins = user_data.get("checkins", {})
    days_checked_in = len(checkins)
    
    checkin_dates = "\n".join(
        f"✅ {d}" for d in sorted(checkins.keys(), reverse=True)[:10]
    )

    message = (
        f"📊 *Your Progress*\n\n"
        f"🎯 Goals: {goals}\n"
        f"🔥 Days Checked In: {days_checked_in}\n\n"
        f"*Recent Check-ins:*\n{checkin_dates if checkin_dates else 'No check-ins yet'}"
    )

    await update.message.reply_text(message, parse_mode="Markdown")

# === Reminder Feature ===

pending_reminders = {}

async def set_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask user for reminder time"""
    await update.message.reply_text(
        "⏰ At what time should I remind you daily?\n"
        "Send time in 24-hour format: HH:MM\n"
        "Example: 09:00 or 21:30"
    )
    pending_reminders[update.effective_chat.id] = True

async def handle_time_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process the time input from user"""
    chat_id = update.effective_chat.id

    if not pending_reminders.get(chat_id):
        return

    time_text = update.message.text.strip()
    try:
        hour, minute = map(int, time_text.split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError

        scheduler = context.application.bot_data["scheduler"]
        scheduler.add_job(
            reminder_job,
            trigger='cron',
            hour=hour,
            minute=minute,
            args=[chat_id, context.application]
        )

        await update.message.reply_text(
            f"✅ Daily reminder set for {hour:02d}:{minute:02d}\n"
            f"I'll remind you every day at this time!"
        )
        pending_reminders.pop(chat_id)
    except:
        await update.message.reply_text(
            "❌ Invalid format. Please use HH:MM in 24-hour format.\n"
            "Example: 09:00 or 21:30"
        )

async def reminder_job(chat_id, application):
    """Send daily reminder message"""
    await application.bot.send_message(
        chat_id=chat_id, 
        text="⏰ Time for your daily /checkin! Don't break the streak! 🔥"
    )

# === Main Function ===

async def main():
    """Start the bot"""
    token = os.environ.get("BOT_TOKEN")
    if not token:
        print("❌ BOT_TOKEN environment variable not set.")
        return

    app = ApplicationBuilder().token(token).build()

    # Scheduler setup
    scheduler = AsyncIOScheduler()
    scheduler.start()
    app.bot_data["scheduler"] = scheduler

    # Add Command Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setgoals", set_goals))
    app.add_handler(CommandHandler("checkin", checkin))
    app.add_handler(CommandHandler("progress", show_progress))
    app.add_handler(CommandHandler("setreminder", set_reminder))
    
    # Handle text messages (for time input)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_time_input))

    print("✅ Bot is running...")
    await app.run_polling()

# === Start the bot ===
if __name__ == "__main__":
    nest_asyncio.apply()
    asyncio.run(main())
