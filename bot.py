from keep_alive import keep_alive

keep_alive()
from dotenv import load_dotenv
load_dotenv()
import os
import json
import asyncio
import aiofiles
from datetime import datetime, date
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, filters, ConversationHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import nest_asyncio
import pytz

# File to store goals and check-ins
GOAL_FILE = "goals.json"

# Conversation state for reminder
WAITING_FOR_TIME = 1

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

# === Reminder Feature (IMPROVED) ===

async def set_reminder_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask user for reminder time"""
    await update.message.reply_text(
        "⏰ At what time should I remind you daily? (IST - India Standard Time)\n"
        "Send time in 24-hour format: HH:MM\n"
        "Example: 09:00 or 21:30\n\n"
        "Send /cancel to cancel."
    )
    return WAITING_FOR_TIME

async def set_reminder_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process the time input from user"""
    chat_id = update.effective_chat.id
    time_text = update.message.text.strip()
    
    try:
        # Parse the time
        hour, minute = map(int, time_text.split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        
        # Get scheduler
        scheduler = context.application.bot_data.get("scheduler")
        if not scheduler:
            await update.message.reply_text("❌ Scheduler not available. Please try again later.")
            return ConversationHandler.END
        
        # Remove any existing jobs for this chat
        existing_jobs = scheduler.get_jobs()
        for job in existing_jobs:
            if job.id == f"reminder_{chat_id}":
                job.remove()
        
        # Add new reminder job with IST timezone
        ist = pytz.timezone('Asia/Kolkata')
        scheduler.add_job(
            reminder_job,
            trigger='cron',
            hour=hour,
            minute=minute,
            timezone=ist,
            id=f"reminder_{chat_id}",
            args=[chat_id, context.application],
            replace_existing=True
        )
        
        print(f"✅ Reminder set for chat {chat_id} at {hour:02d}:{minute:02d} IST")
        
        await update.message.reply_text(
            f"✅ Daily reminder set for {hour:02d}:{minute:02d} IST\n"
            f"I'll remind you every day at this time! 🔥\n\n"
            f"Note: Reminders are lost when the bot restarts."
        )
        
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid format. Please use HH:MM in 24-hour format.\n"
            "Example: 09:00 or 21:30\n\n"
            "Send /cancel to cancel."
        )
        return WAITING_FOR_TIME
    except Exception as e:
        print(f"❌ Error setting reminder: {e}")
        await update.message.reply_text(
            "❌ Sorry, there was an error setting the reminder. Please try again."
        )
        return ConversationHandler.END

async def cancel_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel reminder setup"""
    await update.message.reply_text("❌ Reminder setup cancelled.")
    return ConversationHandler.END

async def reminder_job(chat_id, application):
    """Send daily reminder message"""
    try:
        await application.bot.send_message(
            chat_id=chat_id, 
            text="⏰ Time for your daily /checkin! Don't break the streak! 🔥"
        )
        print(f"✅ Reminder sent to chat {chat_id}")
    except Exception as e:
        print(f"❌ Error sending reminder to {chat_id}: {e}")

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
    print("✅ Scheduler started")

    # Add Command Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setgoals", set_goals))
    app.add_handler(CommandHandler("checkin", checkin))
    app.add_handler(CommandHandler("progress", show_progress))
    
    # Reminder conversation handler
    reminder_handler = ConversationHandler(
        entry_points=[CommandHandler("setreminder", set_reminder_start)],
        states={
            WAITING_FOR_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_reminder_time)]
        },
        fallbacks=[CommandHandler("cancel", cancel_reminder)]
    )
    app.add_handler(reminder_handler)

    print("✅ Bot is running...")
    await app.run_polling()

# === Start the bot ===
if __name__ == "__main__":
    nest_asyncio.apply()
    asyncio.run(main())
