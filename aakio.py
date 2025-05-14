import os
import json
import smtplib
import asyncio
from datetime import datetime
from email.mime.text import MIMEText
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters, ContextTypes
import requests

# التوكن الخاص بالبوت
BOT_TOKEN = "6154380829:AAEeY7-UeBbUYPgTLRp5rs9Ug1FdU3F09h0"

# القنوات المطلوبة للاشتراك
CHANNELS = {
    "𝗴𝗿 𝘀𝘁𝗼𝗿𝗲": "gg4ggg33",
    "متجر باونتي راش بلوكس": "tsmtgrr"
}

# مسار ملف تخزين بيانات المستخدمين
USERS_DATA_FILE = "users_data.json"
# مسار ملف السجل
LOG_FILE = "email_logs.json"

# معرف مالك البوت
OWNER_ID = 6004326248

# ذاكرة مؤقتة لتخزين حالة تحقق المستخدمين
verified_users = {}
# ذاكرة مؤقتة للردود
pending_replies = {}
# مهام الإرسال الجارية
sending_tasks = {}

def load_users_data():
    """تحميل بيانات المستخدمين من ملف JSON"""
    if os.path.exists(USERS_DATA_FILE):
        with open(USERS_DATA_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    return {}

def save_users_data(data):
    """حفظ بيانات المستخدمين إلى ملف JSON"""
    with open(USERS_DATA_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)

def load_logs():
    """تحميل سجل الإرسال"""
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    return {"sent": 0, "failed": []}

def save_logs(logs):
    """حفظ سجل الإرسال"""
    with open(LOG_FILE, "w", encoding="utf-8") as file:
        json.dump(logs, file, indent=4, ensure_ascii=False)

async def check_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """التحقق من اشتراك المستخدم في جميع القنوات"""
    user_id = update.effective_user.id

    for channel_name, channel_id in CHANNELS.items():
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember?chat_id=@{channel_id}&user_id={user_id}"
            response = requests.get(url).json()
            
            # التحقق من استجابة API
            if not response.get('ok'):
                print(f"Error: Failed to check membership for {channel_name}")
                await send_channels_menu(update, context)
                return False
            
            # التحقق من حالة العضوية
            status = response['result']['status']
            if status not in ['member', 'creator', 'administrator']:
                print(f"User is not a member of {channel_name}. Status: {status}")
                await send_channels_menu(update, context)
                return False
                
        except Exception as e:
            print(f"Exception while checking channel {channel_name}: {e}")
            await send_channels_menu(update, context)
            return False

    return True

async def send_channels_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إرسال قائمة القنوات للمستخدم"""
    buttons = []
    for channel_name, channel_id in CHANNELS.items():
        buttons.append([InlineKeyboardButton(channel_name, url=f"https://t.me/{channel_id}")])
    
    buttons.append([InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_subscription")])
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="⚠️ يجب الاشتراك في القنوات التالية أولاً:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def handle_subscription_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة التحقق من الاشتراك"""
    query = update.callback_query
    await query.answer()
    
    if await check_channels(update, context):
        await query.edit_message_text("✓ تم التحقق بنجاح! يمكنك الآن استخدام البوت")
        await main_menu(update, context)
    else:
        await query.answer("❌ لم تكمل الاشتراك بعد!", show_alert=True)

async def forward_to_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحويل رسالة المستخدم إلى المالك مع زر للرد"""
    try:
        if update.message:
            # تحويل الرسالة إلى المالك
            forwarded_message = await context.bot.forward_message(
                chat_id=OWNER_ID,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )

            # إضافة زر "رد"
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("رد", callback_data=f"reply_{update.effective_chat.id}")]
            ])
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text="📩 هل تريد الرد على هذه الرسالة؟",
                reply_to_message_id=forwarded_message.message_id,
                reply_markup=reply_markup
            )
    except Exception as e:
        print(f"Error forwarding message: {e}")

async def handle_owner_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة ضغط المالك على زر الرد"""
    query = update.callback_query
    await query.answer()
    
    if str(update.effective_user.id) != str(OWNER_ID):
        await query.answer("❌ ليس لديك صلاحية للقيام بهذا!", show_alert=True)
        return
    
    target_user_id = query.data.split("_")[1]
    context.user_data["reply_to_user"] = target_user_id
    await query.edit_message_text(text="✏️ اكتب الرد الآن وسيتم إرساله إلى المستخدم.")

async def send_reply_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إرسال رد المالك إلى المستخدم الأصلي"""
    if str(update.effective_user.id) != str(OWNER_ID):
        return

    # التحقق من وجود معرف المستخدم في user_data
    target_user_id = context.user_data.get("reply_to_user")
    if target_user_id:
        try:
            # إرسال الرد إلى المستخدم الأصلي
            await context.bot.send_message(
                chat_id=target_user_id,
                text=update.message.text
            )
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text="✅ تم إرسال الرد إلى المستخدم."
            )
            # إزالة حالة الرد
            del context.user_data["reply_to_user"]
        except Exception as e:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f"❌ فشل إرسال الرد: {str(e)}"
            )
    else:
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text="⚠️ لا يوجد مستخدم للرد عليه. اضغط على زر 'رد' أولاً."
        )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة رسائل المستخدمين العادية"""
    if not update.effective_user:
        # إذا لم يكن هناك مستخدم مرتبط بالتحديث، تجاهل التحديث
        print("⚠️ تم استلام تحديث بدون معلومات عن المستخدم.")
        return

    user_id = str(update.effective_user.id)

    # إذا كان المرسل هو المالك، معالجة الردود
    if str(user_id) == str(OWNER_ID):
        await send_reply_to_user(update, context)
        return

    # إذا لم يكن المستخدم هو المالك، تحويل الرسائل إلى المالك
    await forward_to_owner(update, context)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء تشغيل البوت"""
    user_id = str(update.effective_user.id)

    # التحقق من اشتراك المستخدم في القنوات
    if not await check_channels(update, context):
        return  # إذا لم يكن مشتركًا، توقف هنا

    # تحميل بيانات المستخدمين
    users_data = load_users_data()

    # إذا كان المستخدم جديدًا، أضفه إلى قاعدة البيانات
    if user_id not in users_data:
        users_data[user_id] = {
            "emails_list": [],
            "email_contact": "",
            "subject": "",
            "message_body": "",
            "message_count": 0,
            "delay_seconds": 0
        }
        save_users_data(users_data)

    # إرسال رسالة ترحيبية
    await context.bot.send_message(
    chat_id=update.effective_chat.id,
    text=(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✦ *أهلاً وسهلاً بكم في بوت الخدمة* ✦\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "نُرحب بكم في البوت المُخصص من قِبل:\n\n"
        "      ┏━═━═━═━═━═━═━┓\n"
        "         𝐀𝐊𝐈𝐎 - اكـيـو\n"
        "      ┗━═━═━═━═━═━═━┛\n\n"
        "المُصمم خصيصًا لمساعدتكم في:\n"
        "• رفع الحظر عن المجموعات وحساباتكم الخاصة\n"
        "• إرسال عدد كبير من الرسائل عبر Gmail\n"
        "• تقديم دعم سريع وفعّال\n\n"
        "┌──────────────┐\n"
        "   ⚠️ *تنويه مهم*\n"
        "└──────────────┘\n"
        "الخدمة متاحة *مجانًا* لفترة محدودة،\n"
        "وسيتم لاحقًا تفعيلها *برسوم رمزية بسيطة*\n\n"
        "شكراً لثقتكم بنا\n"
        "مع تحيات عمو: *Akio اكيو*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ),
    parse_mode="Markdown"
)

    await main_menu(update, context)

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """القائمة الرئيسية"""
    user_id = str(update.effective_user.id)

    # إنشاء لوحة الأزرار
    keyboard = [
        [
            InlineKeyboardButton("➕ إضافة إيميل", callback_data='add_email'),
            InlineKeyboardButton("📧 إيميل التواصل", callback_data='set_contact')
        ],
        [
            InlineKeyboardButton("📌 موضوع الرسالة", callback_data='subject'),
            InlineKeyboardButton("📝 وصف الرسالة", callback_data='body')
        ],
        [
            InlineKeyboardButton("🔢 عدد الرسائل", callback_data='count'),
            InlineKeyboardButton("⏱️ وقت التأخير", callback_data='delay')
        ],
        [
            InlineKeyboardButton("📋 عرض الإعدادات", callback_data='show_settings'),
            InlineKeyboardButton("📊 إحصائيات الإرسال", callback_data='send_stats')
        ],
        [
            InlineKeyboardButton("🚀 بدء الإرسال", callback_data='start_sending'),
            InlineKeyboardButton("🛑 إيقاف الإرسال", callback_data='cancel_sending')
        ],
        [
            InlineKeyboardButton("akio المطور", url="https://t.me/a_k_i"),
            InlineKeyboardButton("akio قناة", url="https://t.me/zaxio1")
        ]
    ]

    # إضافة زر الإذاعة فقط إذا كان المستخدم هو المالك
    if user_id == str(OWNER_ID):
        keyboard.append([InlineKeyboardButton("📢 الإذاعة", callback_data='broadcast')])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🔧 لوحة تحكم إرسال الرسائل:",
        reply_markup=reply_markup
    )

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تفعيل وضع الإذاعة (خاص بالمالك فقط)"""
    query = update.callback_query
    await query.answer()

    # تحقق من أن المستخدم هو المالك
    if str(update.effective_user.id) != str(OWNER_ID):
        await query.answer("❌ هذا الخيار متاح للمالك فقط!", show_alert=True)
        return

    # تفعيل وضع الإذاعة
    context.user_data['broadcast_mode'] = True
    await query.edit_message_text("📢 الرجاء إرسال الرسالة التي تريد بثها لجميع المستخدمين:")

async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إرسال رسالة إذاعية لجميع المستخدمين (خاص بالمالك فقط)"""
    if str(update.effective_user.id) != str(OWNER_ID):
        return

    if not context.user_data.get('broadcast_mode'):
        return

    message_text = update.message.text
    users_data = load_users_data()
    total_users = len(users_data)
    success_count = 0
    failed_count = 0

    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=f"⏳ جاري إرسال الرسالة إلى {total_users} مستخدم..."
    )

    for user_id in users_data:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=message_text
            )
            success_count += 1
        except Exception as e:
            print(f"Failed to send broadcast to {user_id}: {e}")
            failed_count += 1
        await asyncio.sleep(0.1)  # تخفيف الضغط على الخادم

    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=f"✅ تم الانتهاء من الإذاعة:\n\n- النجاح: {success_count}\n- الفشل: {failed_count}"
    )

    # تعطيل وضع الإذاعة
    context.user_data['broadcast_mode'] = False

async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض إعدادات المستخدم"""
    user_id = str(update.effective_user.id)
    users_data = load_users_data()
    
    if user_id not in users_data:
        await start(update, context)
        return
    
    user_settings = users_data[user_id]
    emails_info = "\n".join([f"- {email['address']}" for email in user_settings.get("emails_list", [])]) or "لا توجد إيميلات مضافة."
    
    settings_text = (
        f"📋 <b>الإعدادات الحالية:</b>\n\n"
        f"📩 <b>إيميلات التطبيقات:</b>\n{emails_info}\n\n"
        f"📧 <b>إيميل التواصل:</b> {user_settings.get('email_contact', 'غير محدد')}\n"
        f"📌 <b>موضوع الرسالة:</b> {user_settings.get('subject', 'غير محدد')}\n"
        f"📝 <b>وصف الرسالة:</b> {user_settings.get('message_body', 'غير محدد')}\n"
        f"🔢 <b>عدد الرسائل:</b> {user_settings.get('message_count', 0)}\n"
        f"⏱️ <b>وقت التأخير:</b> {user_settings.get('delay_seconds', 0)} ثانية."
    )
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=settings_text,
        parse_mode='HTML'
    )

async def send_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إرسال إحصائيات الإرسال"""
    logs = load_logs()
    stats_text = (
        f"📊 <b>إحصائيات الإرسال:</b>\n\n"
        f"✅ <b>الرسائل المرسلة بنجاح:</b> {logs['sent']}\n"
        f"❌ <b>الرسائل الفاشلة:</b> {len(logs['failed'])}\n\n"
        f"<b>آخر 5 رسائل فاشلة:</b>\n"
    )
    
    for i, failed in enumerate(logs['failed'][-5:], 1):
        stats_text += f"{i}. {failed.get('error', 'Unknown error')}\n"
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=stats_text,
        parse_mode='HTML'
    )

def send_email_sync(email_data, to_email, subject, body):
    """إرسال بريد إلكتروني متزامن"""
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = email_data['address']
        msg['To'] = to_email
        
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(email_data['address'], email_data['password'])
            server.send_message(msg)
        return True, None
    except Exception as e:
        return False, str(e)

async def send_emails_task(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    """مهمة إرسال الرسائل في الخلفية"""
    users_data = load_users_data()
    user_settings = users_data[user_id]
    logs = load_logs()
    
    sent_count = 0
    failed_messages = []
    
    for i in range(user_settings["message_count"]):
        if user_id in sending_tasks and sending_tasks[user_id].cancelled():
            break
            
        email = user_settings["emails_list"][i % len(user_settings["emails_list"])]
        
        success, error = await asyncio.to_thread(
            send_email_sync,
            email,
            user_settings["email_contact"],
            user_settings["subject"],
            user_settings["message_body"]
        )
        
        if success:
            sent_count += 1
            logs["sent"] += 1
            if sent_count % 1 == 0:  # تحديث كل 5 رسائل
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"📤 جاري الإرسال: {i+1}/{user_settings['message_count']} (✅ {sent_count} ❌ {len(failed_messages)})"
                )
        else:
            failed_messages.append({
                "attempt": i+1,
                "error": error,
                "timestamp": str(datetime.now())
            })
            logs["failed"].append({
                "attempt": i+1,
                "error": error,
                "timestamp": str(datetime.now())
            })
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ فشل الإرسال {i+1}: {error}"
            )
        
        if i < user_settings["message_count"] - 1 and user_settings["delay_seconds"] > 0:
            await asyncio.sleep(user_settings["delay_seconds"])
    
    save_logs(logs)
    
    report_text = (
        f"📋 <b>تقرير الإرسال:</b>\n\n"
        f"✅ <b>الرسائل المرسلة بنجاح:</b> {sent_count}\n"
        f"❌ <b>الرسائل الفاشلة:</b> {len(failed_messages)}\n\n"
        f"<b>تفاصيل الأخطاء:</b>\n"
    )
    
    for i, failed in enumerate(failed_messages, 1):
        report_text += f"{i}. {failed['error']}\n"
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=report_text,
        parse_mode='HTML'
    )
    
    if user_id in sending_tasks:
        del sending_tasks[user_id]

async def start_sending_emails(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء عملية إرسال الرسائل"""
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = str(update.effective_user.id)
    users_data = load_users_data()
    
    if user_id not in users_data:
        await start(update, context)
        return
    
    user_settings = users_data[user_id]
    
    # التحقق من الإعدادات المطلوبة
    if not user_settings.get("emails_list"):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ لا توجد إيميلات مضافة. الرجاء إضافة إيميل أولاً."
        )
        return
    
    if not user_settings.get("email_contact"):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ لم يتم تعيين إيميل التواصل. الرجاء تعيينه أولاً."
        )
        return
    
    if not user_settings.get("subject") or not user_settings.get("message_body"):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ لم يتم تعيين موضوع أو وصف الرسالة. الرجاء تعيينهما أولاً."
        )
        return
    
    if user_settings.get("message_count", 0) <= 0:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ عدد الرسائل غير صحيح. الرجاء تعيين عدد صحيح موجب."
        )
        return
    
    if user_id in sending_tasks:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ لديك عملية إرسال جارية بالفعل!"
        )
        return
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🚀 بدء إرسال {user_settings['message_count']} رسالة..."
    )
    
    # بدء المهمة في الخلفية
    task = asyncio.create_task(send_emails_task(update, context, user_id))
    sending_tasks[user_id] = task

async def cancel_sending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إيقاف عملية الإرسال الجارية"""
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = str(update.effective_user.id)
    
    if user_id in sending_tasks:
        sending_tasks[user_id].cancel()
        del sending_tasks[user_id]
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🛑 تم إيقاف عملية الإرسال الجارية."
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ لا توجد عملية إرسال جارية لإيقافها."
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة ضغطات الأزرار"""
    query = update.callback_query
    await query.answer()
    
    user_id = str(update.effective_user.id)
    users_data = load_users_data()
    
    if user_id not in users_data:
        await start(update, context)
        return
    
    if query.data == 'broadcast':
        await handle_broadcast(update, context)
    elif query.data == 'add_email':
        users_data[user_id]["current_setting"] = 'add_email'
        save_users_data(users_data)
        await query.edit_message_text(text="📩 الرجاء إرسال الإيميل الجديد:")
    elif query.data == 'set_contact':
        users_data[user_id]["current_setting"] = 'set_contact'
        save_users_data(users_data)
        await query.edit_message_text(text="📧 الرجاء إرسال إيميل التواصل:")
    elif query.data == 'subject':
        users_data[user_id]["current_setting"] = 'subject'
        save_users_data(users_data)
        await query.edit_message_text(text="📌 الرجاء إرسال موضوع الرسالة:")
    elif query.data == 'body':
        users_data[user_id]["current_setting"] = 'body'
        save_users_data(users_data)
        await query.edit_message_text(text="📝 الرجاء إرسال وصف الرسالة:")
    elif query.data == 'count':
        users_data[user_id]["current_setting"] = 'count'
        save_users_data(users_data)
        await query.edit_message_text(text="🔢 الرجاء إرسال عدد الرسائل المراد إرسالها:")
    elif query.data == 'delay':
        users_data[user_id]["current_setting"] = 'delay'
        save_users_data(users_data)
        await query.edit_message_text(text="⏱️ الرجاء إرسال وقت التأخير بين كل رسالة (بالثواني):")
    elif query.data == 'show_settings':
        await show_settings(update, context)
    elif query.data == 'send_stats':
        await send_stats(update, context)
    elif query.data == 'start_sending':
        await start_sending_emails(update, context)
    elif query.data == 'cancel_sending':
        await cancel_sending(update, context)
    elif query.data == 'check_subscription':
        await handle_subscription_check(update, context)
    elif query.data.startswith('reply_'):
        await handle_owner_reply(update, context)
    else:
        await query.edit_message_text(text="🚫 أمر غير معروف!")

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة رسائل المستخدمين العادية"""
    user_id = str(update.effective_user.id)

    # تحميل بيانات المستخدمين
    users_data = load_users_data()
    if user_id not in users_data:
        users_data[user_id] = {
            "emails_list": [],
            "email_contact": "",
            "subject": "",
            "message_body": "",
            "message_count": 0,
            "delay_seconds": 0
        }
        save_users_data(users_data)

    current_setting = users_data[user_id].get("current_setting")

    if current_setting == 'add_email':
        new_email = update.message.text.strip()
        if '@' in new_email and '.' in new_email.split('@')[-1]:
            users_data[user_id]["temp_email"] = new_email
            users_data[user_id]["current_setting"] = 'add_password'
            save_users_data(users_data)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="🔐 الرجاء إرسال كلمة مرور التطبيقات الخاصة بهذا الإيميل:"
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ الرجاء إرسال إيميل صحيح."
            )

    elif current_setting == 'add_password':
        app_password = update.message.text.strip()
        if len(app_password) >= 8:
            users_data[user_id]["emails_list"].append({
                'address': users_data[user_id]["temp_email"],
                'password': app_password
            })
            del users_data[user_id]["temp_email"]
            users_data[user_id]["current_setting"] = None
            save_users_data(users_data)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"✅ تم إضافة الإيميل بنجاح: {users_data[user_id]['emails_list'][-1]['address']}"
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ كلمة المرور قصيرة جدًا. الرجاء إرسال كلمة مرور صحيحة."
            )

    elif current_setting == 'set_contact':
        email = update.message.text.strip()
        if '@' in email and '.' in email.split('@')[-1]:
            users_data[user_id]["email_contact"] = email
            users_data[user_id]["current_setting"] = None
            save_users_data(users_data)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"✅ تم تعيين إيميل التواصل إلى: {users_data[user_id]['email_contact']}"
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ الرجاء إرسال إيميل صحيح."
            )

    elif current_setting == 'subject':
        users_data[user_id]["subject"] = update.message.text.strip()
        users_data[user_id]["current_setting"] = None
        save_users_data(users_data)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ تم تعيين موضوع الرسالة إلى: {users_data[user_id]['subject']}"
        )

    elif current_setting == 'body':
        users_data[user_id]["message_body"] = update.message.text.strip()
        users_data[user_id]["current_setting"] = None
        save_users_data(users_data)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ تم تعيين وصف الرسالة إلى: {users_data[user_id]['message_body']}"
        )

    elif current_setting == 'count':
        try:
            count = int(update.message.text.strip())
            if count > 0:
                users_data[user_id]["message_count"] = count
                users_data[user_id]["current_setting"] = None
                save_users_data(users_data)
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"✅ تم تعيين عدد الرسائل إلى: {users_data[user_id]['message_count']}"
                )
            else:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ الرجاء إرسال رقم أكبر من الصفر."
                )
        except ValueError:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ الرجاء إرسال رقم صحيح."
            )

    elif current_setting == 'delay':
        try:
            delay = int(update.message.text.strip())
            if delay >= 0:
                users_data[user_id]["delay_seconds"] = delay
                users_data[user_id]["current_setting"] = None
                save_users_data(users_data)
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"✅ تم تعيين وقت التأخير إلى: {users_data[user_id]['delay_seconds']} ثانية."
                )
            else:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ الرجاء إرسال رقم غير سالب."
                )
        except ValueError:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ الرجاء إرسال رقم صحيح."
            )

def main():
    """الدالة الرئيسية لتشغيل البوت"""
    application = Application.builder().token(BOT_TOKEN).build()

    # إضافة المعالجات
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    # بدء البوت
    application.run_polling()

if __name__ == '__main__':
    main()