from keep_alive import keep_alive
keep_alive()

from dotenv import load_dotenv
load_dotenv()
import os
import json
import asyncio
import aiofiles
from datetime import datetime, date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, filters, ConversationHandler, CallbackQueryHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import nest_asyncio
import pytz
import logging

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# File to store goals and check-ins
GOAL_FILE = "goals.json"

# Conversation states
ADDING_GOALS, WAITING_FOR_GOAL, SETTING_REMINDER_TIME = range(3)

# === Data Management ===
async def load_data():
    """Load all user data"""
    try:
        async with aiofiles.open(GOAL_FILE, "r") as f:
            contents = await f.read()
            return json.loads(contents)
    except FileNotFoundError:
        return {}

async def save_data(data):
    """Save all user data"""
    async with aiofiles.open(GOAL_FILE, "w") as f:
        await f.write(json.dumps(data, indent=4))

async def get_user_data(user_id):
    """Get data for specific user"""
    data = await load_data()
    if str(user_id) not in data:
        data[str(user_id)] = {
            "goals": [],
            "checkins": {},  # date -> {goal: True/False}
            "reminders": {},  # goal -> time
            "chat_id": None  # Store chat_id for reminders
        }
        await save_data(data)
    return data[str(user_id)]

async def save_user_data(user_id, user_data):
    """Save data for specific user"""
    data = await load_data()
    data[str(user_id)] = user_data
    await save_data(data)

# === Bot Commands ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Save chat_id for this user
    user_data = await get_user_data(user_id)
    user_data['chat_id'] = chat_id
    await save_user_data(user_id, user_data)
    
    logger.info(f"User {user_id} started bot, chat_id: {chat_id}")
    
    await update.message.reply_text(
        "👋 Welcome to Your Accountability Bot!\n\n"
        "🎯 Track your daily goals and build consistency!\n\n"
        "Commands:\n"
        "• /goals - Set up your goals\n"
        "• /checkin - Mark today's progress\n"
        "• /progress - See your stats\n"
        "• /reminders - Set goal reminders\n"
        "• /debug - Check scheduled reminders\n"
        "• /help - Show all commands\n\n"
        "Start by setting your goals with /goals"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help message"""
    await update.message.reply_text(
        "🤖 *Accountability Bot Help*\n\n"
        "*Commands:*\n"
        "/goals - Set or modify your daily goals\n"
        "/checkin - Mark which goals you completed today\n"
        "/progress - View your 7-day progress and streak\n"
        "/reminders - Set time reminders for your goals\n"
        "/debug - Check scheduled reminders (testing)\n"
        "/test\\_reminder - Test reminder immediately\n"
        "/help - Show this help message\n\n"
        "*How it works:*\n"
        "1️⃣ Set your goals with /goals\n"
        "2️⃣ Check in daily with /checkin\n"
        "3️⃣ Track your progress with /progress\n"
        "4️⃣ Stay on track with /reminders",
        parse_mode="Markdown"
    )

async def debug_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug command to check scheduled jobs"""
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id)
    
    scheduler = context.application.bot_data.get("scheduler")
    if not scheduler:
        await update.message.reply_text("❌ Scheduler not found!")
        return
    
    # Get current IST time
    ist = pytz.timezone('Asia/Kolkata')
    current_time = datetime.now(ist)
    
    msg = f"🔍 *Debug Info*\n\n"
    msg += f"Current IST Time: {current_time.strftime('%H:%M:%S')}\n"
    msg += f"Your Chat ID: {update.effective_chat.id}\n"
    msg += f"Your User ID: {user_id}\n\n"
    
    msg += f"*Saved Reminders in DB:*\n"
    if user_data.get('reminders'):
        for goal, time_str in user_data['reminders'].items():
            msg += f"• {goal}: {time_str}\n"
    else:
        msg += "None\n"
    
    msg += f"\n*Active Scheduler Jobs:*\n"
    jobs = scheduler.get_jobs()
    if jobs:
        for job in jobs:
            if str(user_id) in job.id:
                msg += f"• {job.id}\n"
                msg += f"  Next: {job.next_run_time}\n"
    else:
        msg += "No jobs scheduled!\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def test_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test sending a reminder immediately"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    logger.info(f"Testing reminder for user {user_id}, chat {chat_id}")
    
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🧪 *TEST REMINDER*\n\n"
                 f"This is a test reminder!\n"
                 f"If you see this, reminders are working! ✅",
            parse_mode="Markdown"
        )
        await update.message.reply_text("✅ Test reminder sent!")
        logger.info(f"Test reminder sent successfully to {chat_id}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
        logger.error(f"Error sending test reminder: {e}")

async def goals_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start goal setting process"""
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id)
    
    if user_data["goals"]:
        # Show existing goals
        goals_list = "\n".join([f"• {goal}" for goal in user_data["goals"]])
        keyboard = [
            [InlineKeyboardButton("➕ Add More Goals", callback_data="add_goals")],
            [InlineKeyboardButton("🗑️ Clear All Goals", callback_data="clear_goals")],
            [InlineKeyboardButton("✅ Keep Current Goals", callback_data="keep_goals")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"📋 Your Current Goals:\n\n{goals_list}\n\n"
            f"What would you like to do?",
            reply_markup=reply_markup
        )
        return ConversationHandler.END
    else:
        # Start fresh
        context.user_data['temp_goals'] = []
        await update.message.reply_text(
            "🎯 Let's set up your goals!\n\n"
            "📝 Send me your first goal:\n"
            "Example: AIML, Study DSA, Go to Gym\n\n"
            "Send /done when finished"
        )
        return ADDING_GOALS

async def add_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a goal to temporary list"""
    goal = update.message.text.strip()
    
    if 'temp_goals' not in context.user_data:
        context.user_data['temp_goals'] = []
    
    context.user_data['temp_goals'].append(goal)
    goal_num = len(context.user_data['temp_goals'])
    
    goals_so_far = "\n".join([f"✅ {g}" for g in context.user_data['temp_goals']])
    
    await update.message.reply_text(
        f"✅ Goal {goal_num} added: {goal}\n\n"
        f"Goals so far:\n{goals_so_far}\n\n"
        f"📝 Send next goal or /done to finish"
    )
    return ADDING_GOALS

async def done_adding_goals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finish adding goals"""
    user_id = update.effective_user.id
    
    if 'temp_goals' not in context.user_data or not context.user_data['temp_goals']:
        await update.message.reply_text("❌ No goals added! Use /goals to start again.")
        return ConversationHandler.END
    
    user_data = await get_user_data(user_id)
    user_data['goals'] = context.user_data['temp_goals']
    await save_user_data(user_id, user_data)
    
    goals_list = "\n".join([f"• {goal}" for goal in user_data['goals']])
    
    await update.message.reply_text(
        f"🎉 Goals saved successfully!\n\n{goals_list}\n\n"
        f"Now you can:\n"
        f"• /checkin - Mark today's progress\n"
        f"• /reminders - Set reminders for each goal"
    )
    
    context.user_data.pop('temp_goals', None)
    return ConversationHandler.END

async def show_checkin_status(query, user_id, user_data, today):
    """Show check-in buttons with current status"""
    keyboard = []
    
    for goal in user_data['goals']:
        completed = user_data['checkins'].get(today, {}).get(goal, False)
        emoji = "✅" if completed else "⭕"
        keyboard.append([InlineKeyboardButton(
            f"{emoji} {goal}",
            callback_data=f"checkin_{goal}"
        )])
    
    keyboard.append([InlineKeyboardButton("⏭️ Done for today", callback_data="skip_checkin")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    completed_count = sum(user_data['checkins'].get(today, {}).values())
    total = len(user_data['goals'])
    
    await query.edit_message_text(
        f"📋 Today's Check-in ({completed_count}/{total} completed)\n\n"
        f"Tap goals to mark as done:",
        reply_markup=reply_markup
    )

async def checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show check-in interface"""
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id)
    
    if not user_data['goals']:
        await update.message.reply_text(
            "⚠️ No goals set! Use /goals to set them first."
        )
        return
    
    today = str(date.today())
    keyboard = []
    
    for goal in user_data['goals']:
        completed = user_data['checkins'].get(today, {}).get(goal, False)
        emoji = "✅" if completed else "⭕"
        keyboard.append([InlineKeyboardButton(
            f"{emoji} {goal}",
            callback_data=f"checkin_{goal}"
        )])
    
    keyboard.append([InlineKeyboardButton("⏭️ Done for today", callback_data="skip_checkin")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    completed_count = sum(user_data['checkins'].get(today, {}).values())
    total = len(user_data['goals'])
    
    await update.message.reply_text(
        f"📋 Today's Check-in ({completed_count}/{total} completed)\n\n"
        f"Tap goals to mark as done:",
        reply_markup=reply_markup
    )

async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed progress"""
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id)
    
    if not user_data['goals']:
        await update.message.reply_text("⚠️ No goals set! Use /goals first.")
        return
    
    # Calculate stats for last 7 days
    today = date.today()
    dates = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    
    progress_text = "📊 *Your Progress (Last 7 Days)*\n\n"
    
    total_completed = 0
    total_possible = len(user_data['goals']) * 7
    
    for goal in user_data['goals']:
        week_status = ""
        goal_completed = 0
        
        for date_str in dates:
            if user_data['checkins'].get(date_str, {}).get(goal, False):
                week_status += "✅"
                goal_completed += 1
            else:
                week_status += "⭕"
        
        total_completed += goal_completed
        percentage = int((goal_completed / 7) * 100)
        progress_text += f"🎯 *{goal}*\n{week_status} ({goal_completed}/7 - {percentage}%)\n\n"
    
    # Overall stats
    overall = int((total_completed / total_possible) * 100) if total_possible > 0 else 0
    progress_text += f"📈 *Overall: {total_completed}/{total_possible} ({overall}%)*\n\n"
    
    # Current streak
    streak = calculate_streak(user_data)
    progress_text += f"🔥 *Current Streak: {streak} days*"
    
    await update.message.reply_text(progress_text, parse_mode="Markdown")

def calculate_streak(user_data):
    """Calculate current streak"""
    if not user_data['goals']:
        return 0
    
    streak = 0
    today = date.today()
    
    for i in range(365):  # Check up to 1 year back
        check_date = (today - timedelta(days=i)).isoformat()
        day_checkins = user_data['checkins'].get(check_date, {})
        
        # Check if at least one goal was completed
        if any(day_checkins.values()):
            streak += 1
        else:
            break
    
    return streak

async def reminders_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show reminders menu"""
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id)
    
    # Save chat_id
    chat_id = update.effective_chat.id
    user_data['chat_id'] = chat_id
    await save_user_data(user_id, user_data)
    
    if not user_data['goals']:
        await update.message.reply_text("⚠️ No goals set! Use /goals first.")
        return ConversationHandler.END
    
    keyboard = []
    for goal in user_data['goals']:
        time = user_data['reminders'].get(goal, "Not set")
        button_text = f"{'⏰' if time != 'Not set' else '⭕'} {goal} - {time}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"remind_{goal}")])
    
    keyboard.append([InlineKeyboardButton("🔕 Clear All Reminders", callback_data="clear_reminders")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "⏰ *Set Reminders for Your Goals*\n\n"
        "Click a goal to set reminder time:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )
    
    return SETTING_REMINDER_TIME  # Keep in conversation

async def save_goal_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save reminder time for goal"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    goal = context.user_data.get('setting_reminder_for')
    
    logger.info(f"save_goal_reminder called for user {user_id}, goal: {goal}")
    
    if not goal:
        await update.message.reply_text("❌ Error: No goal selected. Use /reminders to start again.")
        return ConversationHandler.END
    
    time_text = update.message.text.strip()
    
    try:
        hour, minute = map(int, time_text.split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("Time out of range")
        
        # Save reminder time and chat_id
        user_data = await get_user_data(user_id)
        user_data['reminders'][goal] = f"{hour:02d}:{minute:02d}"
        user_data['chat_id'] = chat_id
        await save_user_data(user_id, user_data)
        
        logger.info(f"💾 Saved reminder for user {user_id}, goal '{goal}' at {hour:02d}:{minute:02d}")
        
        # Schedule with APScheduler
        scheduler = context.application.bot_data.get("scheduler")
        if scheduler:
            # Remove old job if exists
            job_id = f"reminder_{user_id}_{goal.replace(' ', '_')}"
            
            for job in list(scheduler.get_jobs()):
                if job.id == job_id:
                    job.remove()
                    logger.info(f"🗑️ Removed old job: {job_id}")
            
            # Add new job
            ist = pytz.timezone('Asia/Kolkata')
            scheduler.add_job(
                goal_reminder_job,
                trigger='cron',
                hour=hour,
                minute=minute,
                timezone=ist,
                id=job_id,
                args=[chat_id, context.application, goal],
                replace_existing=True
            )
            logger.info(f"✅ Scheduled job: {job_id} at {hour:02d}:{minute:02d} IST for chat {chat_id}")
            logger.info(f"📋 Total active jobs: {len(scheduler.get_jobs())}")
        else:
            logger.error("❌ Scheduler not found!")
        
        await update.message.reply_text(
            f"✅ Reminder set for *{goal}* at {hour:02d}:{minute:02d} IST\n\n"
            f"You'll receive a notification at this time every day.\n\n"
            f"Use /reminders to manage reminders\n"
            f"Use /debug to verify it's scheduled",
            parse_mode="Markdown"
        )
        
        context.user_data.pop('setting_reminder_for', None)
        return ConversationHandler.END
        
    except ValueError as e:
        logger.warning(f"Invalid time format: {time_text}, error: {e}")
        await update.message.reply_text(
            "❌ Invalid format. Please use HH:MM (24-hour)\n"
            "Example: 09:00 or 21:30\n\n"
            "Send /cancel to go back"
        )
        return SETTING_REMINDER_TIME

async def goal_reminder_job(chat_id, application, goal):
    """Send reminder for specific goal"""
    try:
        logger.info(f"🔔 Executing reminder job for goal '{goal}' to chat {chat_id}")
        await application.bot.send_message(
            chat_id=chat_id,
            text=f"⏰ *Reminder: {goal}*\n\n"
                 f"Time to work on your goal! 🔥\n"
                 f"Use /checkin when done.",
            parse_mode="Markdown"
        )
        logger.info(f"✅ Reminder sent for goal '{goal}' to chat {chat_id}")
    except Exception as e:
        logger.error(f"❌ Error sending reminder to chat {chat_id}: {e}")

async def reload_all_reminders(application):
    """Reload all reminders from storage on bot startup"""
    try:
        logger.info("🔄 Starting to reload reminders...")
        data = await load_data()
        scheduler = application.bot_data.get("scheduler")
        
        if not scheduler:
            logger.error("❌ No scheduler found for reload")
            return
        
        reminder_count = 0
        for user_id, user_data in data.items():
            reminders = user_data.get('reminders', {})
            chat_id = user_data.get('chat_id')
            
            if not chat_id:
                logger.warning(f"⚠️ No chat_id for user {user_id}, skipping reminders")
                continue
            
            for goal, time_str in reminders.items():
                try:
                    hour, minute = map(int, time_str.split(":"))
                    job_id = f"reminder_{user_id}_{goal.replace(' ', '_')}"
                    
                    ist = pytz.timezone('Asia/Kolkata')
                    scheduler.add_job(
                        goal_reminder_job,
                        trigger='cron',
                        hour=hour,
                        minute=minute,
                        timezone=ist,
                        id=job_id,
                        args=[chat_id, application, goal],
                        replace_existing=True
                    )
                    reminder_count += 1
                    logger.info(f"✅ Reloaded: {job_id} at {time_str} IST for chat {chat_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to reload {user_id}/{goal}: {e}")
        
        logger.info(f"🔄 Reloaded {reminder_count} reminders. Total jobs: {len(scheduler.get_jobs())}")
    except Exception as e:
        logger.error(f"❌ Error reloading reminders: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    logger.info(f"Button callback: {query.data} from user {user_id}")
    
    if query.data == "add_goals":
        context.user_data['temp_goals'] = []
        await query.edit_message_text(
            "📝 Send me your next goal:\n\n"
            "Send /done when finished"
        )
        return ADDING_GOALS
    
    elif query.data == "clear_goals":
        user_data = await get_user_data(user_id)
        user_data['goals'] = []
        user_data['checkins'] = {}
        user_data['reminders'] = {}
        await save_user_data(user_id, user_data)
        await query.edit_message_text(
            "🗑️ All goals cleared!\n\nUse /goals to set new goals."
        )
    
    elif query.data == "keep_goals":
        await query.edit_message_text("✅ Goals kept! Use /checkin to track progress.")
    
    elif query.data.startswith("checkin_"):
        # Handle check-in for specific goal
        goal = query.data.replace("checkin_", "")
        user_data = await get_user_data(user_id)
        today = str(date.today())
        
        if today not in user_data['checkins']:
            user_data['checkins'][today] = {}
        
        # Toggle completion
        current = user_data['checkins'][today].get(goal, False)
        user_data['checkins'][today][goal] = not current
        await save_user_data(user_id, user_data)
        
        # Refresh the check-in view
        await show_checkin_status(query, user_id, user_data, today)
    
    elif query.data == "skip_checkin":
        await query.edit_message_text("⏭️ Check-in skipped. See you tomorrow! 💪")
    
    elif query.data.startswith("remind_"):
        # Handle reminder setting for specific goal
        goal = query.data.replace("remind_", "")
        context.user_data['setting_reminder_for'] = goal
        logger.info(f"User {user_id} setting reminder for goal: {goal}")
        await query.edit_message_text(
            f"⏰ Set reminder for: *{goal}*\n\n"
            f"Send time in HH:MM format (24-hour, IST)\n"
            f"Example: 09:00 or 21:30\n\n"
            f"Send /cancel to go back",
            parse_mode="Markdown"
        )
        return SETTING_REMINDER_TIME
    
    elif query.data == "clear_reminders":
        user_data = await get_user_data(user_id)
        user_data['reminders'] = {}
        await save_user_data(user_id, user_data)
        
        # Remove all scheduled jobs for this user
        scheduler = context.bot_data.get("scheduler")
        if scheduler:
            for job in list(scheduler.get_jobs()):
                if f"reminder_{user_id}_" in job.id:
                    job.remove()
                    logger.info(f"Removed job: {job.id}")
        
        await query.edit_message_text("🔕 All reminders cleared!")
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel any operation"""
    await update.message.reply_text("❌ Operation cancelled.")
    context.user_data.pop('setting_reminder_for', None)
    context.user_data.pop('temp_goals', None)
    return ConversationHandler.END

# === Main Function ===

async def main():
    """Start the bot"""
    try:
        token = os.environ.get("BOT_TOKEN")
        if not token:
            logger.error("❌ BOT_TOKEN not set.")
            return

        logger.info("🚀 Starting bot initialization...")
        app = ApplicationBuilder().token(token).build()

        # Scheduler setup
        logger.info("📅 Setting up scheduler...")
        scheduler = AsyncIOScheduler(timezone=pytz.timezone('Asia/Kolkata'))
        scheduler.start()
        app.bot_data["scheduler"] = scheduler
        
        # Reload existing reminders
        logger.info("🔄 Reloading existing reminders...")
        await reload_all_reminders(app)

        # Command handlers
        logger.info("🔧 Adding command handlers...")
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("help", help_command))
        app.add_handler(CommandHandler("checkin", checkin))
        app.add_handler(CommandHandler("progress", progress))
        app.add_handler(CommandHandler("debug", debug_reminders))
        app.add_handler(CommandHandler("test_reminder", test_reminder))
        
        # Goals conversation
        goals_handler = ConversationHandler(
            entry_points=[CommandHandler("goals", goals_start)],
            states={
                ADDING_GOALS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, add_goal),
                    CommandHandler("done", done_adding_goals)
                ]
            },
            fallbacks=[CommandHandler("cancel", cancel)],
            per_message=False
        )
        app.add_handler(goals_handler)
        
        # Reminders conversation - MUST include callback handler in entry points AND states
        reminders_handler = ConversationHandler(
            entry_points=[
                CommandHandler("reminders", reminders_menu),
                CallbackQueryHandler(button_callback, pattern="^remind_")
            ],
            states={
                SETTING_REMINDER_TIME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_goal_reminder),
                    CallbackQueryHandler(button_callback, pattern="^remind_")
                ]
            },
            fallbacks=[CommandHandler("cancel", cancel)],
            per_message=False,
            allow_reentry=True
        )
        app.add_handler(reminders_handler)
        
        # Button callbacks - exclude remind_ buttons to avoid conflicts
        app.add_handler(CallbackQueryHandler(button_callback, pattern="^(?!remind_).*$"))

        logger.info("✅ Bot is running and ready!")
        logger.info(f"📊 Scheduler has {len(scheduler.get_jobs())} jobs loaded")
        await app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"❌ Error starting bot: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    nest_asyncio.apply()
    asyncio.run(main())
