# -*- coding: utf-8 -*-
import asyncio
import os
import json
import re
import logging
import threading
from datetime import datetime
from flask import Flask, render_template_string, request, redirect, url_for, jsonify, session
from telethon import TelegramClient, events, errors
import aiohttp

# -------------------- الإعدادات الأساسية --------------------
BASE_DIR = os.path.dirname(os.path.realpath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'radar_config.json')
KEYWORDS_FILE = os.path.join(BASE_DIR, 'radar_keywords.txt')
LOG_FILE = os.path.join(BASE_DIR, 'radar.log')
SESSION_FILE = os.path.join(BASE_DIR, 'flask_session.json')

# إعداد تسجيل الأحداث
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# -------------------- متغيرات الرادار --------------------
accounts = []
running = False
clients = []
loop = None
radar_thread = None

# تخزين طلبات التحقق مؤقتاً
verification_requests = {}  # phone -> {"future": asyncio.Future, "type": "code" or "password"}

# -------------------- دوال تحميل/حفظ الإعدادات --------------------
def load_config():
    global accounts
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                accounts = data.get("accounts", [])
                return data
        except:
            return {"accounts": [], "openrouter": {}}
    return {"accounts": [], "openrouter": {}}

def save_config(accounts_list, openrouter_settings):
    full_cfg = {
        "accounts": accounts_list,
        "openrouter": openrouter_settings
    }
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(full_cfg, f, ensure_ascii=False, indent=4)
    global accounts
    accounts = accounts_list

def load_keywords():
    if os.path.exists(KEYWORDS_FILE):
        with open(KEYWORDS_FILE, 'r', encoding='utf-8') as f:
            keywords = [line.strip() for line in f if line.strip()]
            if keywords:
                return keywords
    # قائمة افتراضية موسعة جداً
    default_keywords = [
        'مساعدة', 'ساعدوني', 'ساعدني', 'ساعد', 'ساعدنا', 'ساعدو', 'ساعديني',
        'أبي أحد', 'أبي حد', 'أبي مساعدة', 'أبغى أحد', 'أبغى حد', 'أبغى مساعدة',
        'محتاج', 'محتاجة', 'محوج', 'محوجة', 'ضروري', 'مستعجل', 'مستعجلة',
        'أرجوكم', 'لو سمحتم', 'الله يجزاكم خير', 'بيض الله وجهكم', 'مشكورين',
        'يعطيكم العافية', 'الرجاء المساعدة', 'تحتاج مساعدة', 'نحتاج مساعدة',
        'يحتاج مساعدة', 'عندي مشكلة', 'عندي سؤال', 'عندي استفسار',
        'أبي استفسار', 'أبي حل', 'بليييز', 'بليز', 'please', 'plz', 'help',
        'need help', 'urgent', 'help me',
        'واجب', 'واجبات', 'تكليف', 'تكاليف', 'تكليفات', 'تكاليفي', 'واجبي', 'واجباتي',
        'حل', 'يحل', 'يخل', 'اسايمنت', 'assignment', 'homework', 'أسايمنت',
        'اسايمن', 'اسايم', 'حل واجب', 'حل الواجب', 'حل التكليف', 'حل التكاليف',
        'حل أسايمنت', 'حل assignment', 'تصحيح واجب', 'تصحيح اسايمنت',
        'مساعدة في الواجب', 'مساعدة في الاسايمنت', 'تسليم واجب', 'تسليم تكليف',
        'تأخير واجب', 'مهلة واجب',
        'بحث', 'بحوث', 'تقرير', 'تقارير', 'ريبورت', 'report', 'research',
        'بحثي', 'تقريري', 'دراسة', 'دراسة حالة', 'case study', 'رسالة', 'رسائل',
        'أطروحة', 'thesis', 'إعداد بحث', 'كتابة بحث', 'عمل بحث', 'عمل تقرير',
        'إعداد تقرير', 'كتابة تقرير', 'تحضير بحث', 'مصادر بحث', 'مراجع بحث',
        'مساعدة في البحث', 'مساعدة في التقرير', 'مناقشة بحث', 'خطة بحث',
        'خطة دراسة', 'مقترح بحث', 'proposal', 'بحث علمي', 'paper', 'ورقة بحثية',
        'مشروع', 'مشاريع', 'بروجكت', 'project', 'بروجيكت', 'بروجكتي', 'مشروعي',
        'مشروع تخرج', 'مشاريع تخرج', 'مشروع التخرج', 'مشاريع التخرج',
        'مشروع نهائي', 'خطة مشروع', 'إعداد مشروع', 'تنفيذ مشروع',
        'مساعدة في المشروع', 'مناقشة مشروع', 'مشروع برمجة', 'مشروع هندسي',
        'مشروع تصميم', 'مشروع بحثي',
        'برزنتيشن', 'presentation', 'بوربوينت', 'powerpoint', 'عرض', 'عروض',
        'عرضي', 'تصميم', 'تصاميم', 'تصميمي', 'بوستر', 'poster', 'برشور', 'brochure',
        'انفوجرافيك', 'infographic', 'خريطة ذهنية', 'mind map', 'شريحة', 'شرائح',
        'عرض تقديمي', 'عروض تقديمية', 'تصميم بوربوينت', 'تصميم عرض',
        'تصميم بوستر', 'تصميم برشور', 'تصميم انفوجرافيك', 'غلاف بحث', 'غلاف تقرير',
        'تنسيق عرض', 'تحسين عرض',
        'فيديو', 'فيديوهات', 'مونتاج', 'مقطع', 'تصوير', 'تحرير', 'انميشن', 'animation',
        'موشن جرافيك', 'motion graphic', 'فيديو تعليمي', 'فيديو شرح', 'مقطع فيديو',
        'تصميم فيديو', 'إخراج فيديو', 'إنتاج فيديو', 'تحرير فيديو', 'مونتاج فيديو',
        'اختبار', 'اختبارات', 'كويز', 'كويزات', 'فاينل', 'ميد', 'امتحان', 'امتحانات',
        'اختبار نهائي', 'اختبار منتصف', 'كويز نهائي', 'كويز منتصف',
        'امتحان نهائي', 'امتحان منتصف', 'حل اختبار', 'حل امتحان', 'حل كويз',
        'مساعدة في الاختبار', 'مراجعة اختبار', 'أسئلة اختبار', 'نماذج اختبارات',
        'تجميعات اختبارات', 'أسئلة سنوات سابقة',
        'شرح', 'يشرح', 'شرحي', 'درس', 'دروس', 'دروسي', 'ملخص', 'ملخصات', 'ملخصي',
        'مذكرة', 'مذكرات', 'أساسيات', 'تمارين', 'تدريبات', 'فهم', 'استيعاب', 'تبسيط',
        'شرح درس', 'شرح مادة', 'شرح موضوع', 'دروس خصوصية', 'دروس تقوية',
        'حصة خصوصية', 'تلخيص مادة', 'تلخيص كتاب', 'تلخيص درس', 'تبسيط مادة', 'تأسيس',
        'مراجعة', 'مراجعة ليلة الامتحان', 'مراجعة نهائية', 'مراجعة سريعة',
        'رياضيات', 'فيزياء', 'كيمياء', 'أحياء', 'إنجليزي', 'عربي', 'تاريخ', 'جغرافيا',
        'فلسفة', 'منطق', 'قانون', 'محاسبة', 'اقتصاد', 'إدارة', 'تسويق', 'برمجة',
        'علوم حاسب', 'هندسة', 'طب', 'صيدلة', 'تمريض', 'حقوق', 'علوم سياسية', 'إعلام',
        'لغات', 'ترجمة', 'أدب', 'نحو', 'صرف', 'بلاغة', 'فقه', 'حديث', 'تفسير',
        'رياضيات بحتة', 'رياضيات تطبيقية', 'فيزياء عامة', 'فيزياء نووية',
        'كيمياء عضوية', 'كيمياء تحليلية', 'أحياء دقيقة', 'أحياء جزيئية',
        'تشريح', 'فسيولوجيا', 'صيدلانيات', 'مبادىء محاسبة', 'محاسبة مالية',
        'محاسبة تكاليف', 'تدقيق', 'اقتصاد كلي', 'اقتصاد جزئي', 'إدارة أعمال',
        'تسويق إلكتروني', 'برمجة بايثون', 'برمجة جافا', 'برمجة سي', 'قواعد بيانات',
        'شبكات', 'ذكاء اصطناعي', 'تعلم آلة',
        'دكتور خصوصي', 'مدرس خصوصي', 'معلم خصوصي', 'مدرسة خصوصية', 'تدريس خصوصي',
        'شرح خصوصي', 'يشرح خصوصي', 'معيد', 'متخصص', 'أستاذ خصوصي',
        'مدرس خصوصي رياضيات', 'مدرس خصوصي فيزياء', 'مدرس خصوصي كيمياء',
        'مدرس خصوصي إنجليزي', 'تدريس منزلي', 'تدريس أونلاين',
        'تعرفون أحد', 'تعرفون حد', 'من يعرف', 'من تعرف', 'أحد يعرف', 'حد يعرف',
        'وين ألقى', 'كيف ألقى', 'كيف أحصل', 'مصدر', 'مرجع', 'مصادر', 'مراجع',
        'عندكم فكرة', 'أحد عنده خبرة', 'من جرب', 'تجربة', 'نصيحة', 'توجيه', 'إرشاد',
        'تعرفون مكان', 'تعرفون موقع', 'تعرفون قناة', 'تعرفون مجموعة',
        'تلخيص', 'صياغة', 'كتابة', 'إعداد', 'تنفيذ', 'استشارة', 'تصحيح', 'نسخ', 'تنسيق',
        'ترجمة نص', 'تدقيق لغوي', 'صياغة قانونية', 'كتابة مقال', 'إعداد خطة',
        'استشارة قانونية', 'استشارة هندسية', 'استشارة طبية', 'مراجعة بحث',
        'مراجعة مشروع', 'تصحيح أخطاء', 'تحرير نص', 'تنسيق رسالة',
        'ليالي الامتحان', 'أسئلة', 'إجابات', 'نماذج', 'تجميعات', 'شروحات',
        'حفظ', 'تذكر', 'تطبيق', 'تدريب', 'تجميعات أسئلة', 'شروحات فيديو',
        'دروس أونلاين', 'كورسات', 'دورات', 'تدريب عملي',
        'رسالة ماجستير', 'رسالة دكتوراه', 'نشر', 'مؤتمر', 'مجلة علمية', 'تحكيم',
        'نشر علمي', 'إعداد رسالة ماجستير', 'كتابة أطروحة', 'نشر بحث',
        'مؤتمر علمي', 'مجلة محكمة',
        'كود', 'برنامج', 'موقع', 'نظام', 'قاعدة بيانات', 'خوارزمية', 'هيكل بيانات',
        'واجهة', 'debug', 'troubleshooting', 'تطوير موقع', 'تطوير تطبيق',
        'تصميم واجهات', 'اختبار برمجيات', 'حل مشكلة برمجية', 'مساعدة في الكود',
        'مشروع ويب', 'تطبيق موبايل', 'تطبيق أندرويد', 'تطبيق iOS',
        'رسم', 'أوتوكاد', 'سوليدوركس', 'ريفيت', 'ديزاين', 'تصميم معماري', 'إنشائي',
        'ميكانيكي', 'كهربائي', 'civil', 'mechanical', 'electrical', 'خرائط',
        'مخططات', 'رسومات هندسية', 'تصميم داخلي', 'مخططات هندسية', 'لوحات هندسية',
        'نمذجة', 'نحت', 'تصميم منتج', 'تصميم أثاث',
        'فوتوشوب', 'إليستريتور', 'ان ديزاين', 'جرافيك', 'graphic design',
        'تصميم جرافيكي', 'شعار', 'logo', 'هوية', 'identity', 'براند', 'brand',
        'هوية بصرية', 'براندينغ', 'تصميم شعار', 'تصميم إعلانات',
        'تصميم مطبوعات', 'تصميم تجربة مستخدم', 'تصميم منشورات',
        'تصميم سوشيال ميديا', 'تصميم بوستات', 'تصميم بانرات',
        'ترجمة لغة', 'ترجمة إنجليزي', 'ترجمة عربي', 'ترجمة علمية',
        'ترجمة أدبية', 'تلخيص مقال', 'ترجمة وثائق', 'ترجمة أبحاث',
        'تدقيق نحوي', 'تحرير أكاديمي', 'مراجعة ترجمة',
        'أحد يساعد', 'أحد يحل', 'أحد يشرح', 'أحد يعمل', 'أحد يسوي',
        'أحد يصمم', 'أحد يبرمج', 'أحد يترجم', 'أحد يلخص', 'أحد يدقق', 'أحد يراجع',
        'اللي عنده خبرة', 'اللي يقدر يساعد', 'اللي يعرف', 'اللي عنده فكرة',
        'فيه أحد', 'هل من مساعد', 'يوجد مساعدة', 'أحتاج مساعدة في', 'أحتاج حل',
        'أحتاج شرح', 'أحتاج مشروع',
        'ابي احد', 'ابي حد', 'ابي مساعدة', 'ابغى احد', 'ابغى حد', 'ابغى مساعدة',
        'تعرفون احد', 'من يعرف احد', 'من يعرف حد', 'احد عنده', 'حد عنده',
        'عندكم', 'فيكم', 'تقدرون', 'تكفون', 'يا جماعة', 'يا شباب', 'يا بنات',
        'نبي', 'نبغى', 'تبي', 'تبغى', 'يبي', 'يبغى', 'نبي احد', 'نبغى احد',
        'عندك خبرة', 'عندك فكرة', 'تعرف احد', 'تعرف حد', 'من عنده', 'من عندها',
        'please help', 'assignment help', 'homework help', 'research help',
        'project help', 'essay', 'dissertation', 'lab report', 'coding help',
        'programming help', 'exam help', 'quiz help', 'test help',
        'tutor', 'private tutor', 'online tutor', 'explain', 'explanation',
        'summary', 'summary help', 'translation', 'design help',
        'presentation help', 'powerpoint help', 'edit', 'proofread',
        'کمک', 'راهنمایی', 'پروژه', 'تکلیف', 'تحقیق', 'کوئیز',
        'استاد خصوصی', 'معلم خصوصی', 'ترجمه', 'خلاصه',
        'مدد', 'کام', 'پروجیکٹ', 'اسائنمنٹ', 'ہوم ورک', 'ریسرچ',
        'رپورٹ', 'پرائیویٹ ٹیوٹر', 'ترجمہ', 'تلخیص',
        'عاجل', 'هام', 'ضروري جدا', 'يسعدكم ربي', 'يا ليت', 'لو تكرمتم',
        'الرجاء', 'نأمل مساعدتكم', 'نرجو المساعدة', 'نحتاج دعم',
        'نطلب مساعدة', 'نستفسر عن'
    ]
    # حفظ الكلمات الافتراضية في الملف
    save_keywords(default_keywords)
    return default_keywords

def save_keywords(keywords_list):
    with open(KEYWORDS_FILE, 'w', encoding='utf-8') as f:
        f.write("\n".join(keywords_list))

# -------------------- دوال التصنيف بـ OpenRouter --------------------
async def classify_with_openrouter(text, api_key, prompt_template):
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        # تحسين الـ prompt ليكون أكثر دقة
        enhanced_prompt = prompt_template + """

معايير إضافية:
- **طالب (seeker)**: يستخدم كلمات مثل "أحتاج", "أريد", "كيف", "هل يوجد", "أبي أحد", "تعرفون". يطلب شرحًا، حلاً، بحثًا، مشروعًا، ترجمة. لا يحتوي على روابط دعائية أو قوائم خدمات.
- **معلن (marketer)**: يحتوي على كلمات مثل "نقدم", "خدمات", "عروض", "للتواصل", "خصم", "احترافي". قد يحتوي على قوائم منقطة، رموز ترويجية (⭐ ✅ ═════)، روابط واتساب أو تليجرام، أو إعلانات مكررة.
أعد JSON فقط بالشكل: {"type": "seeker" أو "marketer", "confidence": 0-100, "reason": "السبب"}
"""
        data = {
            "model": "qwen/qwen3-vl-30b-a3b-thinking",
            "messages": [
                {"role": "system", "content": enhanced_prompt},
                {"role": "user", "content": text}
            ]
        }
        async with aiohttp.ClientSession() as session:
            async with session.post("https://openrouter.ai/api/v1/chat/completions",
                                    headers=headers, json=data) as resp:
                if resp.status != 200:
                    logging.error(f"OpenRouter returned {resp.status}")
                    return None
                result = await resp.json()
                content = result["choices"][0]["message"]["content"]
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
    except Exception as e:
        logging.error(f"OpenRouter error: {e}")
    return None

# -------------------- دوال التحقق (Code & Password) --------------------
async def get_verification_code(phone):
    """تطلب رمز التحقق وتنتظر إدخاله من لوحة التحكم"""
    future = asyncio.Future()
    verification_requests[phone] = {"future": future, "type": "code"}
    logging.info(f"📱 طلب رمز تحقق للحساب {phone}")
    return await future

async def get_verification_password(phone):
    """تطلب كلمة المرور للتحقق بخطوتين"""
    future = asyncio.Future()
    verification_requests[phone] = {"future": future, "type": "password"}
    logging.info(f"🔐 طلب كلمة مرور للتحقق بخطوتين للحساب {phone}")
    return await future

# -------------------- دالة مراقبة حساب واحد --------------------
async def monitor_account(acc, openrouter_cfg):
    phone = acc['phone']
    api_id = acc['api_id']
    api_hash = acc['api_hash']
    alert_group = acc.get('alert_group', '')

    session_name = f"session_{re.sub(r'\D', '', phone)}"
    session_path = os.path.join(BASE_DIR, session_name)
    client = TelegramClient(session_path, api_id, api_hash)
    clients.append(client)

    try:
        await client.connect()
        if not await client.is_user_authorized():
            await client.send_code_request(phone)
            code = await get_verification_code(phone)
            try:
                await client.sign_in(phone, code)
            except Exception as e:
                if "password" in str(e).lower() or "2fa" in str(e).lower():
                    password = await get_verification_password(phone)
                    await client.sign_in(password=password)
                else:
                    raise e

        logging.info(f"✅ {phone} متصل")

        if alert_group:
            try:
                await client.get_entity(alert_group)
                logging.info(f"📢 مجموعة الإشعارات {alert_group} متاحة")
            except Exception as e:
                logging.warning(f"⚠️ لا يمكن الوصول لمجموعة الإشعارات {alert_group}: {e}")

        @client.on(events.NewMessage)
        async def handler(event):
            if not running or not event.is_group:
                return
            if event.out:
                return

            targets = load_keywords()
            if not targets:
                return

            msg_text = event.raw_text
            msg_lower = msg_text.lower()

            for kw in targets:
                if kw.lower() in msg_lower:
                    chat = await event.get_chat()
                    chat_name = getattr(chat, 'title', 'غير معروف')
                    logging.info(f"🔍 رصد كلمة '{kw}' في '{chat_name}' بواسطة {phone}")

                    sender_type = None
                    confidence = 0
                    if openrouter_cfg.get("enabled") and openrouter_cfg.get("api_key"):
                        ai_result = await classify_with_openrouter(
                            msg_text,
                            openrouter_cfg["api_key"],
                            openrouter_cfg.get("prompt", "قم بتحليل الرسالة وتحديد ما إذا كان المرسل مسوقاً أو باحثاً.")
                        )
                        if ai_result:
                            sender_type = ai_result.get("type")
                            confidence = ai_result.get("confidence", 0)
                            reason = ai_result.get("reason", "")
                            logging.info(f"🤖 الذكاء الاصطناعي: {sender_type} (ثقة {confidence}%) - {reason}")
                            if sender_type == "marketer" and confidence > 60:
                                logging.info(f"🚫 تم تجاهل رسالة معلن (ثقة {confidence}%)")
                                return

                    # جمع معلومات المرسل والمجموعة
                    sender = await event.get_sender()
                    sender_name = getattr(sender, 'first_name', '') or ''
                    if getattr(sender, 'last_name', None):
                        sender_name += f" {sender.last_name}"
                    sender_name = sender_name.strip() or "غير معروف"
                    sender_username = getattr(sender, 'username', None)
                    sender_id = sender.id
                    if sender_username:
                        sender_link = f"https://t.me/{sender_username}"
                    else:
                        sender_link = f"tg://user?id={sender_id}"

                    chat_username = getattr(chat, 'username', None)
                    chat_id = chat.id
                    if chat_username:
                        chat_link = f"https://t.me/{chat_username}"
                    else:
                        chat_link = f"https://t.me/c/{chat_id}/{event.id}"

                    # بناء الإشعار
                    info = (
                        f"🚨 **رادار ذكي - طلب مساعدة**\n"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"🔍 الكلمة: {kw}\n"
                        f"📝 النص الأصلي: {msg_text}\n"
                        f"👤 المرسل: {sender_name} - [رابط]({sender_link})\n"
                        f"🏢 المجموعة: {chat_name} - [رابط]({chat_link})\n"
                        f"👤 الحساب الراصد: {phone}\n"
                    )
                    if sender_type:
                        info += f"🤖 تصنيف الذكاء: {sender_type} (ثقة {confidence}%)\n"
                    info += "━━━━━━━━━━━━━━━━━━━"

                    if alert_group:
                        try:
                            dest = await client.get_entity(alert_group)
                            # محاولة إعادة التوجيه
                            try:
                                await client.forward_messages(dest, event.message)
                                await client.send_message(dest, info)
                                logging.info(f"📤 تم إرسال التنبيه (إعادة توجيه)")
                            except errors.ChatForwardsRestrictedError:
                                # إذا منع التحويل، نرسل نسخة مع التذييل
                                full_msg = f"{msg_text}\n\n{info}"
                                if event.message.media:
                                    await client.send_file(dest, event.message.media, caption=full_msg)
                                else:
                                    await client.send_message(dest, full_msg)
                                logging.info(f"📤 تم إرسال التنبيه (نسخة)")
                            except errors.FloodWaitError as e:
                                logging.warning(f"⏳ Flood wait {e.seconds} ثانية، انتظار...")
                                await asyncio.sleep(e.seconds)
                                # إعادة المحاولة بعد الانتظار (يمكن إعادة الاستدعاء أو تركها)
                            except Exception as e:
                                logging.error(f"❌ فشل إرسال التنبيه: {e}")
                        except Exception as e:
                            logging.error(f"❌ فشل الحصول على كيان المجموعة المستهدفة: {e}")
                    break

        await client.run_until_disconnected()
    except errors.FloodWaitError as e:
        logging.warning(f"⏳ Flood wait للحساب {phone}: {e.seconds} ثانية، انتظار...")
        await asyncio.sleep(e.seconds)
    except Exception as e:
        logging.error(f"خطأ في حساب {phone}: {e}")
    finally:
        await client.disconnect()
        if client in clients:
            clients.remove(client)

# -------------------- دالة تشغيل الرادار --------------------
async def run_radar():
    global running
    config = load_config()
    acc_list = config.get("accounts", [])
    openrouter_cfg = config.get("openrouter", {})
    if not acc_list:
        logging.error("لا توجد حسابات للتشغيل")
        return
    logging.info(f"🚀 بدء الرادار بعدد {len(acc_list)} حسابات")
    tasks = [monitor_account(acc, openrouter_cfg) for acc in acc_list]
    await asyncio.gather(*tasks, return_exceptions=True)

def start_radar_async():
    global loop, radar_thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_radar())

def stop_radar():
    global running, clients, loop
    running = False
    for client in clients:
        try:
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(client.disconnect(), loop)
        except:
            pass
    clients.clear()
    logging.info("🛑 تم إيقاف الرادار")

# -------------------- تطبيق Flask --------------------
app = Flask(__name__)
app.secret_key = os.urandom(24)

# قالب HTML المدمج (كما هو مع إضافة زر لتحديث السجل)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>رادار التليجرام الذكي - لوحة التحكم</title>
    <style>
        body { font-family: 'Tahoma', sans-serif; background: #1e1e2f; color: #fff; margin: 20px; }
        .container { max-width: 1200px; margin: auto; }
        .card { background: #2a2a3a; border-radius: 10px; padding: 20px; margin-bottom: 20px; box-shadow: 0 4px 10px rgba(0,0,0,0.3); }
        h2 { color: #ffaa00; border-bottom: 2px solid #ffaa00; padding-bottom: 10px; }
        label { display: block; margin: 10px 0 5px; font-weight: bold; color: #ccc; }
        input, textarea, select { width: 100%; padding: 10px; border-radius: 5px; border: none; background: #3a3a4a; color: #fff; margin-bottom: 15px; }
        button { background: #ffaa00; color: #1e1e2f; border: none; padding: 12px 25px; border-radius: 5px; font-weight: bold; cursor: pointer; margin-left: 10px; }
        button:hover { background: #ffbb22; }
        .btn-danger { background: #d9534f; }
        .btn-danger:hover { background: #c9302c; }
        .btn-success { background: #5cb85c; }
        .btn-success:hover { background: #4cae4c; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { padding: 12px; text-align: center; border-bottom: 1px solid #3a3a4a; }
        th { background: #ffaa00; color: #1e1e2f; }
        .log-box { background: #111; color: #0f0; padding: 15px; border-radius: 5px; font-family: monospace; height: 300px; overflow-y: scroll; }
        .flex { display: flex; gap: 10px; }
        .status { display: inline-block; padding: 5px 15px; border-radius: 20px; font-weight: bold; }
        .running { background: #5cb85c; }
        .stopped { background: #d9534f; }
        .modal { display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; background-color: rgba(0,0,0,0.7); }
        .modal-content { background: #2a2a3a; margin: 10% auto; padding: 30px; border-radius: 10px; width: 400px; color: #fff; }
        .close { color: #aaa; float: left; font-size: 28px; font-weight: bold; cursor: pointer; }
        .close:hover { color: #ffaa00; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 رادار التليجرام الذكي - لوحة التحكم</h1>
        
        <!-- نافذة رمز التحقق -->
        <div id="codeModal" class="modal">
            <div class="modal-content">
                <span class="close" onclick="closeCodeModal()">&times;</span>
                <h3 id="codeTitle">🔐 إدخال رمز التحقق</h3>
                <p id="codePhone"></p>
                <input type="text" id="codeInput" placeholder="أدخل الرمز المرسل إلى تليجرام" style="width:100%; padding:10px; margin:10px 0;">
                <button onclick="submitCode()" style="width:100%;">إرسال الرمز</button>
            </div>
        </div>
        
        <!-- نافذة كلمة المرور (للتحقق بخطوتين) -->
        <div id="passwordModal" class="modal">
            <div class="modal-content">
                <span class="close" onclick="closePasswordModal()">&times;</span>
                <h3>🔐 إدخال كلمة المرور</h3>
                <p id="passwordPhone"></p>
                <input type="password" id="passwordInput" placeholder="أدخل كلمة المرور للتحقق بخطوتين" style="width:100%; padding:10px; margin:10px 0;">
                <button onclick="submitPassword()" style="width:100%;">إرسال كلمة المرور</button>
            </div>
        </div>

        <div class="card">
            <div class="flex">
                <h2>حالة الرادار</h2>
                <span class="status {{ 'running' if radar_running else 'stopped' }}">
                    {{ '🟢 يعمل' if radar_running else '🔴 متوقف' }}
                </span>
            </div>
            <form action="/toggle" method="post" style="display:inline;">
                <button type="submit" class="{{ 'btn-danger' if radar_running else 'btn-success' }}">
                    {{ '⏹️ إيقاف الرادار' if radar_running else '▶️ تشغيل الرادار' }}
                </button>
            </form>
            <a href="/"><button type="button">🔄 تحديث الصفحة</button></a>
        </div>

        <div class="card">
            <h2>➕ إضافة حساب جديد</h2>
            <form action="/add_account" method="post">
                <label>رقم الهاتف (مع مفتاح الدولة، مثال: 967XXXXXXXXX)</label>
                <input type="text" name="phone" required pattern="[0-9]+" title="أرقام فقط">
                
                <label>API ID</label>
                <input type="number" name="api_id" required>
                
                <label>API Hash</label>
                <input type="text" name="api_hash" required>
                
                <label>رابط مجموعة الإشعارات (اختياري)</label>
                <input type="text" name="alert_group" placeholder="https://t.me/...">
                
                <button type="submit">💾 إضافة الحساب</button>
            </form>
        </div>

        <div class="card">
            <h2>📋 الحسابات المضافة</h2>
            <table>
                <tr>
                    <th>رقم الهاتف</th>
                    <th>مجموعة الإشعارات</th>
                    <th>الإجراءات</th>
                </tr>
                {% for acc in accounts %}
                <tr>
                    <td>{{ acc.phone }}</td>
                    <td>{{ acc.alert_group if acc.alert_group else 'غير محدد' }}</td>
                    <td>
                        <form action="/delete_account" method="post" style="display:inline;">
                            <input type="hidden" name="phone" value="{{ acc.phone }}">
                            <button type="submit" class="btn-danger" onclick="return confirm('هل أنت متأكد؟')">🗑️ حذف</button>
                        </form>
                    </td>
                </tr>
                {% endfor %}
            </table>
        </div>

        <div class="card">
            <h2>🔑 الكلمات المفتاحية</h2>
            <form action="/save_keywords" method="post">
                <textarea name="keywords" rows="8" placeholder="كلمة في كل سطر">{{ keywords | join('\n') }}</textarea>
                <button type="submit">💾 حفظ الكلمات</button>
            </form>
        </div>

        <div class="card">
            <h2>🤖 إعدادات OpenRouter (التصنيف الذكي)</h2>
            <form action="/save_openrouter" method="post">
                <label>مفتاح API (اتركه فارغاً لتعطيل التصنيف)</label>
                <input type="text" name="api_key" value="{{ openrouter.api_key }}">
                
                <label>تعليمات التصنيف (prompt)</label>
                <textarea name="prompt" rows="5">{{ openrouter.prompt }}</textarea>
                
                <label>
                    <input type="checkbox" name="enabled" {% if openrouter.enabled %}checked{% endif %}> تفعيل التصنيف الذكي
                </label>
                
                <button type="submit">💾 حفظ إعدادات OpenRouter</button>
            </form>
        </div>

        <div class="card">
            <h2>📜 سجل الأحداث (آخر 100 سطر)</h2>
            <div class="log-box" id="log-box">{{ log }}</div>
            <button onclick="refreshLog()">🔄 تحديث السجل</button>
        </div>
    </div>
    <script>
        function refreshLog() {
            fetch('/log')
                .then(response => response.text())
                .then(data => {
                    document.getElementById('log-box').innerText = data;
                });
        }
        
        function checkVerificationRequests() {
            fetch('/api/verification-requests')
                .then(response => response.json())
                .then(data => {
                    if (data.phone && data.type) {
                        if (data.type === 'code') {
                            document.getElementById('codePhone').innerText = 'رقم الحساب: ' + data.phone;
                            document.getElementById('codeModal').style.display = 'block';
                        } else if (data.type === 'password') {
                            document.getElementById('passwordPhone').innerText = 'رقم الحساب: ' + data.phone;
                            document.getElementById('passwordModal').style.display = 'block';
                        }
                    }
                });
        }
        
        function submitCode() {
            const code = document.getElementById('codeInput').value;
            fetch('/api/submit-code', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({code: code})
            }).then(() => {
                document.getElementById('codeModal').style.display = 'none';
                document.getElementById('codeInput').value = '';
            });
        }
        
        function submitPassword() {
            const password = document.getElementById('passwordInput').value;
            fetch('/api/submit-password', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({password: password})
            }).then(() => {
                document.getElementById('passwordModal').style.display = 'none';
                document.getElementById('passwordInput').value = '';
            });
        }
        
        function closeCodeModal() {
            document.getElementById('codeModal').style.display = 'none';
        }
        
        function closePasswordModal() {
            document.getElementById('passwordModal').style.display = 'none';
        }
        
        setInterval(refreshLog, 10000);
        setInterval(checkVerificationRequests, 2000);
    </script>
</body>
</html>
"""

# -------------------- مسارات Flask --------------------
@app.route('/api/verification-requests')
def verification_requests_api():
    for phone, req in verification_requests.items():
        if not req["future"].done():
            return {"phone": phone, "type": req["type"]}
    return {}

@app.route('/api/submit-code', methods=['POST'])
def submit_code():
    data = request.get_json()
    code = data.get('code', '')
    for phone, req in list(verification_requests.items()):
        if req["type"] == "code" and not req["future"].done():
            req["future"].set_result(code)
            del verification_requests[phone]
            break
    return {"status": "ok"}

@app.route('/api/submit-password', methods=['POST'])
def submit_password():
    data = request.get_json()
    password = data.get('password', '')
    for phone, req in list(verification_requests.items()):
        if req["type"] == "password" and not req["future"].done():
            req["future"].set_result(password)
            del verification_requests[phone]
            break
    return {"status": "ok"}

@app.route('/')
def index():
    config = load_config()
    accounts_list = config.get("accounts", [])
    openrouter_cfg = config.get("openrouter", {"api_key": "", "enabled": False, "prompt": ""})
    keywords_list = load_keywords()
    
    log_content = ""
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            log_content = "".join(lines[-100:])
    
    return render_template_string(
        HTML_TEMPLATE,
        accounts=accounts_list,
        keywords=keywords_list,
        openrouter=openrouter_cfg,
        radar_running=running,
        log=log_content
    )

@app.route('/add_account', methods=['POST'])
def add_account():
    phone = request.form.get('phone', '').strip()
    api_id = request.form.get('api_id', '').strip()
    api_hash = request.form.get('api_hash', '').strip()
    alert_group = request.form.get('alert_group', '').strip()
    
    if not phone or not api_id or not api_hash:
        return "جميع الحقول مطلوبة", 400
    
    config = load_config()
    accounts_list = config.get("accounts", [])
    if any(acc['phone'] == phone for acc in accounts_list):
        return "هذا الحساب موجود بالفعل", 400
    
    accounts_list.append({
        "phone": phone,
        "api_id": int(api_id),
        "api_hash": api_hash,
        "alert_group": alert_group
    })
    save_config(accounts_list, config.get("openrouter", {}))
    return redirect(url_for('index'))

@app.route('/delete_account', methods=['POST'])
def delete_account():
    phone = request.form.get('phone', '')
    config = load_config()
    accounts_list = config.get("accounts", [])
    accounts_list = [acc for acc in accounts_list if acc['phone'] != phone]
    save_config(accounts_list, config.get("openrouter", {}))
    return redirect(url_for('index'))

@app.route('/save_keywords', methods=['POST'])
def save_keywords_route():
    keywords_text = request.form.get('keywords', '')
    keywords_list = [line.strip() for line in keywords_text.split('\n') if line.strip()]
    save_keywords(keywords_list)
    return redirect(url_for('index'))

@app.route('/save_openrouter', methods=['POST'])
def save_openrouter():
    api_key = request.form.get('api_key', '').strip()
    enabled = 'enabled' in request.form
    prompt = request.form.get('prompt', '').strip()
    
    config = load_config()
    openrouter_cfg = {
        "api_key": api_key,
        "enabled": enabled,
        "prompt": prompt
    }
    save_config(config.get("accounts", []), openrouter_cfg)
    return redirect(url_for('index'))

@app.route('/toggle', methods=['POST'])
def toggle_radar():
    global running, radar_thread
    if running:
        stop_radar()
        running = False
    else:
        running = True
        radar_thread = threading.Thread(target=start_radar_async, daemon=True)
        radar_thread.start()
    return redirect(url_for('index'))

@app.route('/log')
def get_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            return "".join(lines[-100:])
    return ""

if __name__ == '__main__':
    # تأكد من وجود ملفات افتراضية
    if not os.path.exists(KEYWORDS_FILE):
        save_keywords([])  # هذا سيؤدي إلى استخدام load_keywords التي تنشئ القائمة
    if not os.path.exists(CONFIG_FILE):
        save_config([], {"api_key": "", "enabled": False, "prompt": "قم بتحليل الرسالة وتحديد ما إذا كان المرسل مسوقاً أو باحثاً."})
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
