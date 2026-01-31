#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ربات تلگرامی مدیریت روتین روزانه
ورژن: 2.0
توسعه‌دهنده: مدیریت روتین شخصی
"""

import os
import logging
import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from enum import Enum
import pytz

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

# کلاس‌های Enum برای فعالیت‌ها
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

# تنظیمات زمان‌بندی فعالیت‌ها
SCHEDULE = {
    "school": {
        "days": [0, 1, 2, 3, 4],  # شنبه تا چهارشنبه
        "start_time": "07:30",
        "end_time": "14:00"
    },
    "taekwondo": {
        "fitness": {
            "day": 2,  # سه‌شنبه
            "start_time": "15:30",
            "end_time": "17:30",
            "type": TaekwondoType.FITNESS
        },
        "form": {
            "day": 4,  # پنج‌شنبه
            "start_time": "09:30",
            "end_time": "11:30",
            "type": TaekwondoType.FORM
        },
        "sparring": {
            "day": 5,  # جمعه
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
    """مدیریت پایگاه داده SQLite"""
    
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
        
        # جدول پیشرفت هفتگی
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS weekly_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                week_start TEXT NOT NULL,
                week_end TEXT NOT NULL,
                activity_type TEXT NOT NULL,
                completed_days INTEGER DEFAULT 0,
                total_hours REAL DEFAULT 0,
                goals_met BOOLEAN DEFAULT 0,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # جدول تنظیمات کاربر
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                notifications_enabled BOOLEAN DEFAULT 1,
                reminder_times TEXT, -- JSON formatted list of reminder times
                custom_activities TEXT, -- JSON formatted custom activities
                timezone TEXT DEFAULT 'Asia/Tehran',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # جدول یادآوری‌ها
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                activity_type TEXT NOT NULL,
                reminder_time TEXT NOT NULL,
                active BOOLEAN DEFAULT 1,
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
        
        # بررسی و به‌روزرسانی پیشرفت هفتگی
        self.update_weekly_progress(user_id)
        
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
    
    def get_weekly_progress(self, user_id: int) -> Dict:
        """دریافت پیشرفت هفتگی"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # تاریخ شروع و پایان هفته جاری
        today = datetime.now(TEHRAN_TZ)
        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        
        start_str = start_of_week.strftime('%Y-%m-%d')
        end_str = end_of_week.strftime('%Y-%m-%d')
        
        cursor.execute('''
            SELECT activity_type, SUM(completed) as completed_count,
                   COUNT(*) as total_count
            FROM daily_activities
            WHERE user_id = ? AND date BETWEEN ? AND ?
            GROUP BY activity_type
        ''', (user_id, start_str, end_str))
        
        progress = {}
        for row in cursor.fetchall():
            activity_type = row[0]
            completed = row[1]
            total = row[2]
            progress[activity_type] = {
                'completed': completed,
                'total': total,
                'percentage': (completed / total * 100) if total > 0 else 0
            }
        
        conn.close()
        return progress
    
    def update_weekly_progress(self, user_id: int):
        """به‌روزرسانی پیشرفت هفتگی"""
        progress = self.get_weekly_progress(user_id)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        today = datetime.now(TEHRAN_TZ)
        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        
        start_str = start_of_week.strftime('%Y-%m-%d')
        end_str = end_of_week.strftime('%Y-%m-%d')
        
        for activity_type, data in progress.items():
            cursor.execute('''
                INSERT OR REPLACE INTO weekly_progress 
                (user_id, week_start, week_end, activity_type, completed_days, total_hours)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, start_str, end_str, activity_type, 
                  data['completed'], data['total']))
        
        conn.commit()
        conn.close()

class RoutinePlanner:
    """برنامه‌ریز روتین روزانه"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
    
    def generate_daily_schedule(self, user_id: int) -> List[Dict]:
        """تولید برنامه روزانه بر اساس روز هفته"""
        today = datetime.now(TEHRAN_TZ)
        day_of_week = today.weekday()  # 0=شنبه, 1=یکشنبه, ..., 5=جمعه
        day_name = self.get_persian_day(day_of_week)
        
        activities = []
        
        # مدرسه (شنبه تا چهارشنبه)
        if day_of_week in SCHEDULE["school"]["days"]:
            activities.append({
                "type": ActivityType.SCHOOL.value,
                "name": "⏰ مدرسه",
                "time": SCHEDULE["school"]["start_time"],
                "duration": "6.5 ساعت",
                "description": "ساعت 7:30 تا 14:00"
            })
        
        # تکواندو
        taekwondo_schedule = SCHEDULE["taekwondo"]
        for session in taekwondo_schedule.values():
            if session["day"] == day_of_week:
                activities.append({
                    "type": ActivityType.TAEKWONDO.value,
                    "name": f"🥋 تکواندو - {session['type'].value}",
                    "time": session["start_time"],
                    "duration": "2 ساعت",
                    "description": f"ساعت {session['start_time']} تا {session['end_time']}"
                })
        
        # برنامه‌نویسی (بعد از مدرسه/تکالیف)
        coding_time = "15:00" if day_of_week in SCHEDULE["school"]["days"] else "10:00"
        activities.append({
            "type": ActivityType.CODING.value,
            "name": "💻 برنامه‌نویسی",
            "time": coding_time,
            "duration": "1+ ساعت",
            "description": "تمرین روزانه برنامه‌نویسی"
        })
        
        # ورزش خانگی
        if SCHEDULE["home_workout"]["daily"]:
            workout_time = "18:00" if day_of_week in [2, 4, 5] else "16:00"
            exercises = "، ".join(SCHEDULE["home_workout"]["exercises"])
            activities.append({
                "type": ActivityType.HOME_WORKOUT.value,
                "name": "🏋️ ورزش خانگی",
                "time": workout_time,
                "duration": "45 دقیقه",
                "description": f"تمرینات: {exercises}"
            })
        
        # روتین پوستی
        skincare = SCHEDULE["skincare"]["routines"]
        activities.extend([
            {
                "type": ActivityType.SKINCARE.value,
                "name": "🧴 روتین پوستی صبح",
                "time": "07:00",
                "duration": "10 دقیقه",
                "description": f"مراحل: {'، '.join(skincare['morning'])}"
            },
            {
                "type": ActivityType.SKINCARE.value,
                "name": "🧴 روتین پوستی عصر",
                "time": "18:30",
                "duration": "10 دقیقه",
                "description": f"مراحل: {'، '.join(skincare['evening'])}"
            },
            {
                "type": ActivityType.SKINCARE.value,
                "name": "🧴 روتین پوستی شب",
                "time": "22:00",
                "duration": "10 دقیقه",
                "description": f"مراحل: {'، '.join(skincare['night'])}"
            }
        ])
        
        # تفریح
        leisure_time = "20:00"
        activities.append({
            "type": ActivityType.LEISURE.value,
            "name": "🎮 تفریح / وقت آزاد",
            "time": leisure_time,
            "duration": "1+ ساعت",
            "description": "زمان استراحت و فعالیت‌های مورد علاقه"
        })
        
        # مطالعه و تکالیف
        if day_of_week in SCHEDULE["school"]["days"]:
            activities.append({
                "type": ActivityType.STUDY.value,
                "name": "📚 مطالعه و تکالیف",
                "time": "17:00",
                "duration": "2 ساعت",
                "description": "مرور درس‌ها و انجام تکالیف"
            })
        
        # مرتب‌سازی بر اساس زمان
        activities.sort(key=lambda x: x["time"])
        
        # ثبت در دیتابیس
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
    
    def get_persian_day(self, day_index: int) -> str:
        """تبدیل شماره روز به نام فارسی"""
        days = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه"]
        return days[day_index]
    
    def generate_weekly_report(self, user_id: int) -> str:
        """تولید گزارش هفتگی"""
        progress = self.db.get_weekly_progress(user_id)
        
        today = datetime.now(TEHRAN_TZ)
        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        
        report = "📊 *گزارش هفتگی پیشرفت*\n\n"
        report += f"📅 از {start_of_week.strftime('%Y/%m/%d')} تا {end_of_week.strftime('%Y/%m/%d')}\n\n"
        
        total_completed = 0
        total_activities = 0
        
        for activity_type, data in progress.items():
            emoji = self.get_activity_emoji(activity_type)
            percentage = data['percentage']
            progress_bar = self.create_progress_bar(percentage)
            
            report += f"{emoji} *{activity_type}*:\n"
            report += f"   {data['completed']} از {data['total']} فعالیت\n"
            report += f"   {progress_bar} {percentage:.1f}%\n\n"
            
            total_completed += data['completed']
            total_activities += data['total']
        
        overall_percentage = (total_completed / total_activities * 100) if total_activities > 0 else 0
        report += f"🎯 *مجموع:* {total_completed} از {total_activities} فعالیت\n"
        report += f"📈 *میانگین کلی:* {overall_percentage:.1f}%\n\n"
        
        # پیام انگیزشی
        motivational_messages = [
            "🔥 عالی ادامه بده! هفته پربرکتی داشته باشی!",
            "💪 پیشرفت عالی! همین‌طور ادامه بده!",
            "🌟 افتخار میکنم به تعهدت! هفته آینده هم قوی باش!",
            "🚀 آفرین! هر روز بهتر از دیروز!",
            "🌈 تمرین و پشتکارت رو تحسین می‌کنم!"
        ]
        
        import random
        report += f"💬 {random.choice(motivational_messages)}"
        
        return report
    
    def generate_next_week_schedule(self, user_id: int) -> str:
        """پیشنهاد برنامه هفته آینده"""
        today = datetime.now(TEHRAN_TZ)
        next_monday = today + timedelta(days=(7 - today.weekday()))
        
        schedule = "📅 *برنامه پیشنهادی هفته آینده*\n\n"
        
        for i in range(7):
            day = next_monday + timedelta(days=i)
            day_name = self.get_persian_day(day.weekday())
            schedule += f"*{day_name} ({day.strftime('%Y/%m/%d')})*:\n"
            
            # مدرسه
            if day.weekday() in SCHEDULE["school"]["days"]:
                schedule += "  ⏰ مدرسه (7:30-14:00)\n"
            
            # تکواندو
            for session_name, session in SCHEDULE["taekwondo"].items():
                if session["day"] == day.weekday():
                    schedule += f"  🥋 {session['type'].value} ({session['start_time']}-{session['end_time']})\n"
            
            # فعالیت‌های روزانه ثابت
            schedule += "  💻 برنامه‌نویسی (1+ ساعت)\n"
            schedule += "  🏋️ ورزش خانگی (45 دقیقه)\n"
            schedule += "  🧴 روتین پوستی\n"
            schedule += "  🎮 تفریح (1+ ساعت)\n"
            
            if day.weekday() in SCHEDULE["school"]["days"]:
                schedule += "  📚 مطالعه و تکالیف (2 ساعت)\n"
            
            schedule += "\n"
        
        return schedule
    
    def get_activity_emoji(self, activity_type: str) -> str:
        """دریافت ایموجی مناسب برای هر فعالیت"""
        emoji_map = {
            "مدرسه": "⏰",
            "تکواندو": "🥋",
            "برنامه‌نویسی": "💻",
            "ورزش خانگی": "🏋️",
            "روتین پوستی": "🧴",
            "تفریح": "🎮",
            "مطالعه": "📚"
        }
        return emoji_map.get(activity_type, "✅")
    
    def create_progress_bar(self, percentage: float, length: int = 10) -> str:
        """ایجاد نوار پیشرفت متنی"""
        filled = int(percentage / 100 * length)
        empty = length - filled
        return "▓" * filled + "░" * empty

class TelegramBot:
    """کلاس اصلی ربات تلگرام"""
    
    def __init__(self, token: str):
        self.token = token
        self.db = DatabaseManager()
        self.planner = RoutinePlanner(self.db)
        self.application = None
        self.job_queue = None
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """دستور /start"""
        user = update.effective_user
        welcome_message = (
            f"سلام {user.first_name}! 👋\n\n"
            "🤖 *ربات مدیریت روتین روزانه* آماده خدمت‌رسانی است!\n\n"
            "📋 *دستورات موجود:*\n"
            "✅ /today - نمایش برنامه امروز\n"
            "✅ /done - فعالیت‌های انجام‌شده\n"
            "✅ /report - گزارش هفتگی\n"
            "✅ /nextweek - برنامه هفته آینده\n"
            "✅ /motivate - پیام انگیزشی\n"
            "✅ /help - راهنمایی\n\n"
            "برای شروع، از دستور /today استفاده کن!"
        )
        
        await update.message.reply_text(
            welcome_message,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def show_today_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """نمایش برنامه امروز"""
        user_id = update.effective_user.id
        
        # تولید برنامه روزانه
        activities = self.planner.generate_daily_schedule(user_id)
        
        today = datetime.now(TEHRAN_TZ)
        day_name = self.planner.get_persian_day(today.weekday())
        date_str = today.strftime('%Y/%m/%d')
        
        message = f"📅 *برنامه روزانه - {day_name} {date_str}*\n\n"
        
        keyboard = []
        
        for i, activity in enumerate(activities, 1):
            status = "✅" if activity.get("completed") else "⏳"
            message += (
                f"{i}. {status} *{activity['name']}*\n"
                f"   ⏰ ساعت: {activity['time']}\n"
                f"   📝 {activity['description']}\n\n"
            )
            
            # اضافه کردن دکمه برای فعالیت‌های انجام نشده
            if not activity.get("completed"):
                keyboard.append([
                    InlineKeyboardButton(
                        f"✅ انجام شد: {activity['name'][:20]}",
                        callback_data=f"complete_{activity['id']}"
                    )
                ])
        
        if keyboard:
            reply_markup = InlineKeyboardMarkup(keyboard)
        else:
            reply_markup = None
        
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def complete_activity(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """علامت‌گذاری فعالیت به عنوان انجام شده"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        activity_id = int(data.split("_")[1])
        user_id = query.from_user.id
        
        # علامت‌گذاری در دیتابیس
        self.db.mark_activity_completed(activity_id, user_id)
        
        # ارسال تایید
        await query.edit_message_text(
            text="✅ فعالیت با موفقیت انجام‌شده ثبت شد!",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # ارسال پیام انگیزشی تصادفی
        await self.send_motivational_message(query.message.chat_id)
    
    async def send_motivational_message(self, chat_id: int):
        """ارسال پیام انگیزشی"""
        messages = [
            "آفرین! ادامه بده! 💪",
            "عالی هستی! همین‌طور ادامه بده! 🌟",
            "پیشرفت عالی! به خودت افتخار کن! 🏆",
            "هر قدم کوچک، پیشرفت بزرگ است! 🚶‍♂️✨",
            "تمرین امروز، موفقیت فرداست! 📚🎯",
            "تو می‌تونی! به خودت ایمان داشته باش! 💖",
            "پشتکارت تحسین‌برانگیزه! ادامه بده! 🔥"
        ]
        
        import random
        message = random.choice(messages)
        
        await self.application.bot.send_message(
            chat_id=chat_id,
            text=f"💬 *پیام انگیزشی:*\n\n{message}",
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def weekly_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ارسال گزارش هفتگی"""
        user_id = update.effective_user.id
        
        report = self.planner.generate_weekly_report(user_id)
        
        await update.message.reply_text(
            report,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def next_week_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """نمایش برنامه هفته آینده"""
        user_id = update.effective_user.id
        
        schedule = self.planner.generate_next_week_schedule(user_id)
        
        await update.message.reply_text(
            schedule,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def motivate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ارسال پیام انگیزشی"""
        await self.send_motivational_message(update.message.chat_id)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """دستور /help"""
        help_text = (
            "🆘 *راهنمای ربات مدیریت روتین*\n\n"
            "📋 *دستورات اصلی:*\n"
            "✅ /start - شروع کار با ربات\n"
            "✅ /today - نمایش برنامه کامل امروز\n"
            "✅ /done - لیست فعالیت‌های انجام‌شده\n"
            "✅ /report - گزارش هفتگی پیشرفت\n"
            "✅ /nextweek - برنامه پیشنهادی هفته آینده\n"
            "✅ /motivate - دریافت پیام انگیزشی\n"
            "✅ /help - این راهنما\n\n"
            "🔔 *یادآوری خودکار:*\n"
            "ربات به طور خودکار برای فعالیت‌های مهم یادآوری ارسال می‌کند.\n\n"
            "📊 *گزارش‌دهی:*\n"
            "گزارش هفتگی هر جمعه ارسال می‌شود.\n\n"
            "⚙️ *تنظیمات:*\n"
            "به زودی امکان تنظیم زمان یادآوری اضافه می‌شود."
        )
        
        await update.message.reply_text(
            help_text,
            parse_mode=ParseMode.MARKDOWN
        )
    
    def schedule_reminders(self):
        """زمان‌بندی یادآوری‌های خودکار"""
        # یادآوری مدرسه (شنبه تا چهارشنبه)
        for day in SCHEDULE["school"]["days"]:
            self.job_queue.run_daily(
                self.remind_school,
                time=datetime.strptime("06:30", "%H:%M").time(),
                days=(day,),
                name=f"school_reminder_{day}"
            )
        
        # یادآوری تکواندو
        for session_name, session in SCHEDULE["taekwondo"].items():
            self.job_queue.run_weekly(
                self.remind_taekwondo,
                time=datetime.strptime(session["start_time"], "%H:%M").time() - timedelta(minutes=30),
                days=(session["day"],),
                name=f"taekwondo_{session_name}_reminder"
            )
        
        # یادآوری روزانه برنامه‌نویسی
        self.job_queue.run_daily(
            self.remind_coding,
            time=datetime.strptime("15:00", "%H:%M").time(),
            name="coding_reminder"
        )
        
        # یادآوری ورزش خانگی
        self.job_queue.run_daily(
            self.remind_workout,
            time=datetime.strptime("18:00", "%H:%M").time(),
            name="workout_reminder"
        )
        
        # یادآوری روتین پوستی شب
        self.job_queue.run_daily(
            self.remind_skincare_night,
            time=datetime.strptime("21:45", "%H:%M").time(),
            name="skincare_night_reminder"
        )
        
        # گزارش هفتگی (هر جمعه ساعت 20:00)
        self.job_queue.run_weekly(
            self.send_weekly_report_to_all,
            time=datetime.strptime("20:00", "%H:%M").time(),
            days=(5,),  # جمعه
            name="weekly_report"
        )
    
    async def remind_school(self, context: ContextTypes.DEFAULT_TYPE):
        """یادآوری مدرسه"""
        message = (
            "⏰ *یادآوری مدرسه*\n\n"
            "ساعت 7:30 مدرسه شروع می‌شود!\n"
            "حتماً صبحانه میل کرده و وسایل رو چک کن.\n\n"
            "روز خوبی داشته باشی! 📚✨"
        )
        
        # در حالت واقعی، اینجا باید کاربران فعال را از دیتابیس بخوانیم
        # برای نمونه، یک کاربر فرضی
        try:
            await context.bot.send_message(
                chat_id=context.job.chat_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error sending school reminder: {e}")
    
    async def remind_taekwondo(self, context: ContextTypes.DEFAULT_TYPE):
        """یادآوری تکواندو"""
        job_name = context.job.name
        session_type = ""
        
        if "fitness" in job_name:
            session_type = "بدنسازی"
        elif "form" in job_name:
            session_type = "فرم"
        elif "sparring" in job_name:
            session_type = "مبارزه"
        
        message = (
            f"🥋 *یادآوری تمرین تکواندو*\n\n"
            f"امروز جلسه {session_type} داریم!\n"
            f"وسایل تمرین رو آماده کن.\n\n"
            f"تمرین پرانرژی‌ای داشته باشی! 💪"
        )
        
        try:
            await context.bot.send_message(
                chat_id=context.job.chat_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error sending taekwondo reminder: {e}")
    
    async def remind_coding(self, context: ContextTypes.DEFAULT_TYPE):
        """یادآوری برنامه‌نویسی"""
        message = (
            "💻 *یادآوری برنامه‌نویسی*\n\n"
            "وقت تمرین برنامه‌نویسی روزانه است!\n"
            "حداقل 1 ساعت تمرین کن.\n\n"
            "مهارتت رو ارتقا بده! 🚀"
        )
        
        try:
            await context.bot.send_message(
                chat_id=context.job.chat_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error sending coding reminder: {e}")
    
    async def remind_workout(self, context: ContextTypes.DEFAULT_TYPE):
        """یادآوری ورزش خانگی"""
        exercises = "، ".join(SCHEDULE["home_workout"]["exercises"])
        message = (
            "🏋️ *یادآوری ورزش خانگی*\n\n"
            f"برنامه امروز: {exercises}\n"
            "45 دقیقه ورزش کن.\n\n"
            "قوی و سالم باشی! 💪"
        )
        
        try:
            await context.bot.send_message(
                chat_id=context.job.chat_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error sending workout reminder: {e}")
    
    async def remind_skincare_night(self, context: ContextTypes.DEFAULT_TYPE):
        """یادآوری روتین پوستی شب"""
        routine = "، ".join(SCHEDULE["skincare"]["routines"]["night"])
        message = (
            "🧴 *یادآوری روتین پوستی شب*\n\n"
            f"مراحل شب: {routine}\n"
            "قبل از خواب پوستت رو مراقبت کن.\n\n"
            "شب بخیر! 🌙✨"
        )
        
        try:
            await context.bot.send_message(
                chat_id=context.job.chat_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error sending skincare reminder: {e}")
    
    async def send_weekly_report_to_all(self, context: ContextTypes.DEFAULT_TYPE):
        """ارسال گزارش هفتگی به همه کاربران"""
        # در حالت واقعی، باید همه کاربران را از دیتابیس بخوانیم
        # برای نمونه، یک گزارش کلی ایجاد می‌کنیم
        message = (
            "📊 *گزارش هفتگی خودکار*\n\n"
            "جمعه شده! وقت بررسی هفته!\n"
            "برای مشاهده گزارش کامل از دستور /report استفاده کن.\n\n"
            "برنامه هفته آینده هم با /nextweek در دسترسته!\n\n"
            "آخر هفته خوبی داشته باشی! 🌈"
        )
        
        # اینجا در حالت واقعی باید loop روی کاربران داشته باشیم
        try:
            # برای نمونه فقط به یک چت مشخص ارسال می‌کنیم
            await context.bot.send_message(
                chat_id=context.job.chat_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error sending weekly report: {e}")
    
    def setup_handlers(self):
        """تنظیم هندلرهای ربات"""
        # Command handlers
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("today", self.show_today_schedule))
        self.application.add_handler(CommandHandler("report", self.weekly_report))
        self.application.add_handler(CommandHandler("nextweek", self.next_week_schedule))
        self.application.add_handler(CommandHandler("motivate", self.motivate))
        self.application.add_handler(CommandHandler("help", self.help_command))
        
        # Callback query handler
        self.application.add_handler(CallbackQueryHandler(self.complete_activity, pattern="^complete_"))
    
    def run(self):
        """اجرای ربات"""
        # ساخت اپلیکیشن
        self.application = Application.builder().token(self.token).build()
        self.job_queue = self.application.job_queue
        
        # تنظیم هندلرها
        self.setup_handlers()
        
        # زمان‌بندی یادآوری‌ها
        # توجه: در Render، باید از webhook استفاده کنیم
        # این بخش برای حالت polling است (توسعه محلی)
        
        logger.info("ربات در حال اجرا است...")
        
        # اجرای ربات
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

def main():
    """تابع اصلی"""
    # توکن ربات تلگرام (از متغیر محیطی بخوان)
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not BOT_TOKEN:
        logger.error("لطفاً توکن ربات را در متغیر محیطی TELEGRAM_BOT_TOKEN تنظیم کنید.")
        return
    
    # ساخت و اجرای ربات
    bot = TelegramBot(BOT_TOKEN)
    bot.run()

if __name__ == "__main__":
    main()
