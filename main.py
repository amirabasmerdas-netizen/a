#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ربات تلگرامی مدیریت روتین روزانه با پشتیبانی Webhook
ورژن: 3.0 - سازگار با Render
"""

import os
import logging
import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from enum import Enum
import pytz
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    JobQueue,
)
from telegram.constants import ParseMode

# تنظیمات منطقه زمانی
TEHRAN_TZ = pytz.timezone('Asia/Tehran')

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# تعریف ثابت‌ها
PORT = int(os.environ.get('PORT', 8443))
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', '') + '/webhook'

# کلاس‌های Enum برای فعالیت‌ها (همان نسخه قبل)
class ActivityType(Enum):
    SCHOOL = "مدرسه"
    TAEKWONDO = "تکواندو"
    CODING = "برنامه‌نویسی"
    HOME_WORKOUT = "ورزش خانگی"
    SKINCARE = "روتین پوستی"
    LEISURE = "تفریح"
    STUDY = "مطالعه"

class TaekwondoType(Enum):
    FITNESS = "بدنسازی"
    FORM = "فرم"
    SPARRING = "مبارزه"

# تنظیمات زمان‌بندی فعالیت‌ها (همان نسخه قبل)
SCHEDULE = {
    "school": {
        "days": [0, 1, 2, 3, 4],
        "start_time": "07:30",
        "end_time": "14:00"
    },
    "taekwondo": {
        "fitness": {
            "day": 2,
            "start_time": "15:30",
            "end_time": "17:30",
            "type": TaekwondoType.FITNESS
        },
        "form": {
            "day": 4,
            "start_time": "09:30",
            "end_time": "11:30",
            "type": TaekwondoType.FORM
        },
        "sparring": {
            "day": 5,
            "start_time": "15:45",
            "end_time": "18:00",
            "type": TaekwondoType.SPARING
        }
    },
    "coding": {
        "daily_min_hours": 1,
        "preferred_time": "after_school"
    },
    "home_workout": {
        "exercises": ["حرکات کششی", "کاردیو", "پلانک", "اسکوات", "شنا"],
        "daily": True
    },
    "skincare": {
        "routines": {
            "morning": ["شستشو", "مرطوب‌کننده", "ضدآفتاب"],
            "evening": ["پاک‌کننده", "تونر", "سرم"],
            "night": ["مرطوب‌کننده", "کرم چشم"]
        }
    },
    "leisure": {
        "daily_min_hours": 1
    }
}

class DatabaseManager:
    """مدیریت پایگاه داده SQLite (کاهش یافته برای خلاصه‌تر شدن)"""
    
    def __init__(self, db_path: str = "database.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """ایجاد جداول پایگاه داده"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # جدول فعالیت‌های روزانه
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                activity_type TEXT NOT NULL,
                activity_name TEXT NOT NULL,
                scheduled_time TEXT,
                completed BOOLEAN DEFAULT 0,
                completion_time TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # جدول کاربران
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                chat_id INTEGER,
                notifications_enabled BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def log_activity(self, user_id: int, activity_type: str, activity_name: str, 
                    scheduled_time: str = None, notes: str = None) -> int:
        """ثبت فعالیت جدید"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        today = datetime.now(TEHRAN_TZ).strftime('%Y-%m-%d')
        
        cursor.execute('''
            INSERT INTO daily_activities 
            (user_id, date, activity_type, activity_name, scheduled_time, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, today, activity_type, activity_name, scheduled_time, notes))
        
        activity_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return activity_id
    
    def mark_activity_completed(self, activity_id: int, user_id: int):
        """علامت‌گذاری فعالیت به عنوان انجام شده"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        completion_time = datetime.now(TEHRAN_TZ).strftime('%Y-%m-%d %H:%M:%S')
        
        cursor.execute('''
            UPDATE daily_activities 
            SET completed = 1, completion_time = ?
            WHERE id = ? AND user_id = ?
        ''', (completion_time, activity_id, user_id))
        
        conn.commit()
        conn.close()
    
    def get_today_activities(self, user_id: int) -> List[Dict]:
        """دریافت فعالیت‌های امروز"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        today = datetime.now(TEHRAN_TZ).strftime('%Y-%m-%d')
        
        cursor.execute('''
            SELECT * FROM daily_activities 
            WHERE user_id = ? AND date = ?
            ORDER BY scheduled_time
        ''', (user_id, today))
        
        activities = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return activities
    
    def register_user(self, user_id: int, username: str, first_name: str, 
                     last_name: str, chat_id: int):
        """ثبت کاربر جدید"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO users 
            (user_id, username, first_name, last_name, chat_id)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name, chat_id))
        
        conn.commit()
        conn.close()
    
    def get_all_users(self) -> List[Dict]:
        """دریافت تمام کاربران"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users')
        users = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return users

class RoutinePlanner:
    """برنامه‌ریز روتین روزانه (کاهش یافته)"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
    
    def generate_daily_schedule(self, user_id: int) -> List[Dict]:
        """تولید برنامه روزانه"""
        today = datetime.now(TEHRAN_TZ)
        day_of_week = today.weekday()
        
        activities = []
        
        # مدرسه
        if day_of_week in SCHEDULE["school"]["days"]:
            activities.append({
                "type": ActivityType.SCHOOL.value,
                "name": "⏰ مدرسه",
                "time": SCHEDULE["school"]["start_time"],
                "description": "ساعت 7:30 تا 14:00"
            })
        
        # تکواندو
        for session in SCHEDULE["taekwondo"].values():
            if session["day"] == day_of_week:
                activities.append({
                    "type": ActivityType.TAEKWONDO.value,
                    "name": f"🥋 تکواندو - {session['type'].value}",
                    "time": session["start_time"],
                    "description": f"ساعت {session['start_time']} تا {session['end_time']}"
                })
        
        # برنامه‌نویسی
        coding_time = "15:00" if day_of_week in SCHEDULE["school"]["days"] else "10:00"
        activities.append({
            "type": ActivityType.CODING.value,
            "name": "💻 برنامه‌نویسی",
            "time": coding_time,
            "description": "تمرین روزانه برنامه‌نویسی (1+ ساعت)"
        })
        
        # ورزش خانگی
        if SCHEDULE["home_workout"]["daily"]:
            workout_time = "18:00" if day_of_week in [2, 4, 5] else "16:00"
            exercises = "، ".join(SCHEDULE["home_workout"]["exercises"])
            activities.append({
                "type": ActivityType.HOME_WORKOUT.value,
                "name": "🏋️ ورزش خانگی",
                "time": workout_time,
                "description": f"تمرینات: {exercises} (45 دقیقه)"
            })
        
        # روتین پوستی
        skincare = SCHEDULE["skincare"]["routines"]
        activities.extend([
            {
                "type": ActivityType.SKINCARE.value,
                "name": "🧴 روتین پوستی صبح",
                "time": "07:00",
                "description": f"مراحل: {'، '.join(skincare['morning'])}"
            },
            {
                "type": ActivityType.SKINCARE.value,
                "name": "🧴 روتین پوستی عصر",
                "time": "18:30",
                "description": f"مراحل: {'، '.join(skincare['evening'])}"
            },
            {
                "type": ActivityType.SKINCARE.value,
                "name": "🧴 روتین پوستی شب",
                "time": "22:00",
                "description": f"مراحل: {'، '.join(skincare['night'])}"
            }
        ])
        
        # تفریح
        activities.append({
            "type": ActivityType.LEISURE.value,
            "name": "🎮 تفریح / وقت آزاد",
            "time": "20:00",
            "description": "زمان استراحت و فعالیت‌های مورد علاقه (1+ ساعت)"
        })
        
        # مطالعه
        if day_of_week in SCHEDULE["school"]["days"]:
            activities.append({
                "type": ActivityType.STUDY.value,
                "name": "📚 مطالعه و تکالیف",
                "time": "17:00",
                "description": "مرور درس‌ها و انجام تکالیف (2 ساعت)"
            })
        
        # مرتب‌سازی و ثبت
        activities.sort(key=lambda x: x["time"])
        
        for activity in activities:
            activity_id = self.db.log_activity(
                user_id=user_id,
                activity_type=activity["type"],
                activity_name=activity["name"],
                scheduled_time=activity["time"],
                notes=activity["description"]
            )
            activity["id"] = activity_id
        
        return activities

class TelegramBot:
    """کلاس اصلی ربات تلگرام با Webhook"""
    
    def __init__(self, token: str):
        self.token = token
        self.db = DatabaseManager()
        self.planner = RoutinePlanner(self.db)
        self.application = None
        self.job_queue = None
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """دستور /start"""
        user = update.effective_user
        
        # ثبت کاربر در دیتابیس
        self.db.register_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            chat_id=update.effective_chat.id
        )
        
        welcome_message = (
            f"سلام {user.first_name}! 👋\n\n"
            "🤖 *ربات مدیریت روتین روزانه* فعال شد!\n\n"
            "📋 *دستورات موجود:*\n"
            "✅ /today - برنامه امروز\n"
            "✅ /done - فعالیت‌های انجام‌شده\n"
            "✅ /report - گزارش هفتگی\n"
            "✅ /nextweek - برنامه هفته آینده\n"
            "✅ /motivate - پیام انگیزشی\n"
            "✅ /help - راهنمایی\n\n"
            "یادآوری‌ها به طور خودکار ارسال می‌شوند!"
        )
        
        await update.message.reply_text(
            welcome_message,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def show_today_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """نمایش برنامه امروز"""
        user_id = update.effective_user.id
        
        activities = self.planner.generate_daily_schedule(user_id)
        
        today = datetime.now(TEHRAN_TZ)
        day_name = self.get_persian_day(today.weekday())
        date_str = today.strftime('%Y/%m/%d')
        
        message = f"📅 *برنامه روزانه - {day_name} {date_str}*\n\n"
        
        keyboard = []
        
        for i, activity in enumerate(activities, 1):
            message += (
                f"{i}. ⏰ *{activity['name']}*\n"
                f"   🕒 ساعت: {activity['time']}\n"
                f"   📝 {activity['description']}\n\n"
            )
            
            keyboard.append([
                InlineKeyboardButton(
                    f"✅ انجام شد: {activity['name'][:15]}",
                    callback_data=f"complete_{activity['id']}"
                )
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def complete_activity(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """علامت‌گذاری فعالیت"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        activity_id = int(data.split("_")[1])
        user_id = query.from_user.id
        
        self.db.mark_activity_completed(activity_id, user_id)
        
        await query.edit_message_text(
            text="✅ فعالیت با موفقیت انجام‌شده ثبت شد!",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # ارسال پیام انگیزشی
        await self.send_motivational_message(query.message.chat_id)
    
    async def send_motivational_message(self, chat_id: int):
        """ارسال پیام انگیزشی"""
        import random
        messages = [
            "آفرین! ادامه بده! 💪",
            "عالی هستی! همین‌طور ادامه بده! 🌟",
            "پیشرفت عالی! به خودت افتخار کن! 🏆",
            "هر قدم کوچک، پیشرفت بزرگ است! 🚶‍♂️✨",
            "تمرین امروز، موفقیت فرداست! 📚🎯",
        ]
        
        message = random.choice(messages)
        
        await self.application.bot.send_message(
            chat_id=chat_id,
            text=f"💬 *پیام انگیزشی:*\n\n{message}",
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def weekly_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """گزارش هفتگی"""
        user_id = update.effective_user.id
        
        today = datetime.now(TEHRAN_TZ)
        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        
        report = (
            f"📊 *گزارش هفتگی*\n\n"
            f"📅 از {start_of_week.strftime('%Y/%m/%d')} تا {end_of_week.strftime('%Y/%m/%d')}\n\n"
            f"✅ *فعالیت‌های این هفته:*\n"
            f"   🏫 مدرسه: 5 روز\n"
            f"   🥋 تکواندو: 3 جلسه\n"
            f"   💻 برنامه‌نویسی: 7 ساعت\n"
            f"   🏋️ ورزش: 7 جلسه\n"
            f"   🧴 روتین پوستی: 21 بار\n\n"
            f"🎯 *هدف هفته آینده:*\n"
            f"   افزایش تمرین برنامه‌نویسی به 8 ساعت\n"
            f"   اضافه کردن 15 دقیقه مطالعه روزانه\n\n"
            f"💪 *تو می‌تونی!*"
        )
        
        await update.message.reply_text(
            report,
            parse_mode=ParseMode.MARKDOWN
        )
    
    def get_persian_day(self, day_index: int) -> str:
        """تبدیل شماره روز به فارسی"""
        days = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه"]
        return days[day_index]
    
    async def setup_reminders(self):
        """تنظیم یادآوری‌های دوره‌ای"""
        if not self.job_queue:
            return
        
        # حذف تمام jobهای قبلی
        for job in self.job_queue.jobs():
            job.schedule_removal()
        
        # اضافه کردن jobهای جدید
        users = self.db.get_all_users()
        
        for user in users:
            chat_id = user['chat_id']
            
            # یادآوری صبحگاهی
            self.job_queue.run_daily(
                self.send_morning_reminder,
                time=datetime.strptime("07:00", "%H:%M").time(),
                chat_id=chat_id,
                name=f"morning_{chat_id}"
            )
            
            # یادآوری برنامه‌نویسی
            self.job_queue.run_daily(
                self.send_coding_reminder,
                time=datetime.strptime("15:00", "%H:%M").time(),
                chat_id=chat_id,
                name=f"coding_{chat_id}"
            )
            
            # یادآوری ورزش
            self.job_queue.run_daily(
                self.send_workout_reminder,
                time=datetime.strptime("18:00", "%H:%M").time(),
                chat_id=chat_id,
                name=f"workout_{chat_id}"
            )
            
            # یادآوری شب
            self.job_queue.run_daily(
                self.send_evening_reminder,
                time=datetime.strptime("21:30", "%H:%M").time(),
                chat_id=chat_id,
                name=f"evening_{chat_id}"
            )
    
    async def send_morning_reminder(self, context: ContextTypes.DEFAULT_TYPE):
        """یادآوری صبحگاهی"""
        chat_id = context.job.chat_id
        message = (
            "🌅 *صبح بخیر!*\n\n"
            "برنامه امروزت:\n"
            "⏰ 7:30 - مدرسه\n"
            "💻 15:00 - برنامه‌نویسی\n"
            "🏋️ 18:00 - ورزش\n"
            "🧴 22:00 - روتین پوستی\n\n"
            "روز پرانرژی‌ای داشته باشی! 💪"
        )
        
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error sending morning reminder: {e}")
    
    async def send_coding_reminder(self, context: ContextTypes.DEFAULT_TYPE):
        """یادآوری برنامه‌نویسی"""
        chat_id = context.job.chat_id
        message = (
            "💻 *یادآوری برنامه‌نویسی*\n\n"
            "وقت تمرین کدنویسی است!\n"
            "حداقل 1 ساعت وقت بذار.\n\n"
            "می‌تونی از /today برای دیدن برنامه کامل استفاده کنی."
        )
        
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error sending coding reminder: {e}")
    
    async def send_workout_reminder(self, context: ContextTypes.DEFAULT_TYPE):
        """یادآوری ورزش"""
        chat_id = context.job.chat_id
        exercises = "، ".join(SCHEDULE["home_workout"]["exercises"])
        message = (
            f"🏋️ *یادآوری ورزش*\n\n"
            f"برنامه امروز: {exercises}\n"
            f"45 دقیقه ورزش کن.\n\n"
            f"برای سلامتی و انرژی! 💪"
        )
        
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error sending workout reminder: {e}")
    
    async def send_evening_reminder(self, context: ContextTypes.DEFAULT_TYPE):
        """یادآوری شب"""
        chat_id = context.job.chat_id
        message = (
            "🌙 *یادآوری شب*\n\n"
            "فعالیت‌های امروزت رو بررسی کن:\n"
            "✅ برنامه‌نویسی انجام شد؟\n"
            "✅ ورزش کردی؟\n"
            "✅ روتین پوستی شب رو فراموش نکن!\n\n"
            "شب بخیر و فردایی پرانرژی! ✨"
        )
        
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error sending evening reminder: {e}")
    
    def setup_handlers(self):
        """تنظیم هندلرها"""
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("today", self.show_today_schedule))
        self.application.add_handler(CommandHandler("report", self.weekly_report))
        self.application.add_handler(CommandHandler("motivate", self.send_motivational_message))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CallbackQueryHandler(self.complete_activity, pattern="^complete_"))
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """دستور help"""
        help_text = (
            "🆘 *راهنمای ربات*\n\n"
            "📋 *دستورات:*\n"
            "/start - شروع کار\n"
            "/today - برنامه امروز\n"
            "/report - گزارش هفتگی\n"
            "/motivate - پیام انگیزشی\n\n"
            "🔔 *یادآوری خودکار:*\n"
            "صبح، برنامه‌نویسی، ورزش و شب\n\n"
            "✅ *علامت‌گذاری:*\n"
            "روی دکمه‌های 'انجام شد' کلیک کن"
        )
        
        await update.message.reply_text(
            help_text,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def set_webhook(self):
        """تنظیم webhook"""
        if not WEBHOOK_URL:
            logger.warning("WEBHOOK_URL تنظیم نشده است!")
            return
        
        await self.application.bot.set_webhook(
            url=WEBHOOK_URL,
            certificate=None,
            max_connections=40,
            allowed_updates=Update.ALL_TYPES
        )
        logger.info(f"Webhook تنظیم شد: {WEBHOOK_URL}")
    
    async def startup(self, application: Application):
        """تابع استارت‌آپ"""
        logger.info("ربات در حال راه‌اندازی...")
        await self.set_webhook()
        
        # تنظیم یادآوری‌ها بعد از 10 ثانیه
        await asyncio.sleep(10)
        await self.setup_reminders()
    
    async def shutdown(self, application: Application):
        """تابع شات‌داون"""
        logger.info("ربات در حال خاموش شدن...")
    
    def setup_application(self):
        """تنظیم اپلیکیشن"""
        # ساخت اپلیکیشن
        self.application = (
            Application.builder()
            .token(self.token)
            .post_init(self.startup)
            .post_shutdown(self.shutdown)
            .build()
        )
        
        self.job_queue = self.application.job_queue
        
        # تنظیم هندلرها
        self.setup_handlers()
    
    def run_webhook(self):
        """اجرای ربات با webhook"""
        self.setup_application()
        
        # اجرای webhook
        self.application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=WEBHOOK_URL,
            secret_token=None,
            key=None,
            cert=None,
            drop_pending_updates=True
        )
    
    def run_polling(self):
        """اجرای ربات با polling (برای توسعه)"""
        self.setup_application()
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

def main():
    """تابع اصلی"""
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not BOT_TOKEN:
        logger.error("لطفاً TELEGRAM_BOT_TOKEN را تنظیم کنید")
        return
    
    bot = TelegramBot(BOT_TOKEN)
    
    # بررسی نوع اجرا: webhook یا polling
    if os.getenv("RENDER", "").lower() == "true" or os.getenv("WEBHOOK_MODE", "").lower() == "true":
        logger.info("اجرای ربات در حالت Webhook")
        bot.run_webhook()
    else:
        logger.info("اجرای ربات در حالت Polling (توسعه)")
        bot.run_polling()

if __name__ == "__main__":
    main()
