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

verification_requests = {}  # phone -> {"future": asyncio.Future, "type": "code" or "password"}

# -------------------- قوائم الميزات المميزة للمعلنين والطلاب (موسعة جداً) --------------------

# كلمات مفتاحية تدل على أن المرسل طالب (يريد خدمة) - مع تنويعات الهمزات والعامية
SEEKER_KEYWORDS = [
    # طلب مساعدة عام
    'ابي احد', 'ابي حد', 'ابغى احد', 'ابغى حد', 'تعرفون احد', 'تعرفون حد',
    'من يعرف احد', 'من يعرف حد', 'احد يعرف', 'حد يعرف', 'فيه احد', 'فيه حد',
    'في احد', 'في حد', 'عندكم احد', 'عندكم حد', 'احد عنده', 'حد عنده',
    'محتاج', 'محتاجة', 'محوج', 'محوجة', 'ضروري', 'مستعجل', 'مستعجلة',

    # طلب شرح
    'يشرح', 'شرح', 'دروس خصوصية', 'درس خصوصي', 'خصوصي', 'مدرس خصوصي',
    'معلم خصوصي', 'دكتور خصوصي', 'يشرح لي', 'تشرح لي', 'يشرحلي', 'تشرحلي',
    'يفهمني', 'تفهمني', 'يفهم', 'تفهم',

    # طلب حل (واجبات، تكاليف، الخ)
    'يحل', 'حل', 'يخل', 'حل واجب', 'حل واجبات', 'حل التكليف', 'حل التكاليف',
    'حل اسايمنت', 'حل assignment', 'يسوي', 'يسوي لي', 'يسويلي', 'تسوي',
    'تسوي لي', 'تسويلي', 'يعمل', 'يعمل لي', 'يعملي', 'تعمل', 'تعمل لي',
    'تعملي', 'ينفذ', 'ينفذ لي', 'ينفذلي',

    # طلب كتابة/بحث/مشروع
    'يكتب', 'يكتب لي', 'يكتبلي', 'تكتب', 'تكتب لي', 'تكتبلي',
    'بحث', 'بحوث', 'تقرير', 'تقارير', 'مشروع', 'مشاريع', 'بروجكت',
    'ريبورت', 'report', 'research', 'paper', 'thesis', 'اطروحة',
    'سيرة ذاتية', 'cv', 'تصميم', 'تصاميم', 'بوستر', 'poster', 'برزنتيشن',
    'presentation', 'بوربوينت', 'powerpoint',

    # طلب ترجمة/تلخيص
    'يترجم', 'يترجم لي', 'يترجملي', 'تترجم', 'تترجم لي', 'تترجملي',
    'ترجمة', 'يلخص', 'يلخص لي', 'يلخصلي', 'تلخيص', 'يدقق', 'يدقق لي',
    'يدققلي', 'تدقيق', 'تصحيح', 'يصحح', 'يصحح لي', 'يصححلي',

    # كلمات استفهام طلابية
    'كيف اسوي', 'كيف أعمل', 'كيف أذاكر', 'كيف أحل', 'وين ألقى', 'من وين',
    'مصدر', 'مرجع', 'اللي عنده خبرة', 'اللي جرب', 'اللي يعرف',

    # كلمات خليجية وعامية متنوعة
    'ابي', 'ابغى', 'ودي', 'نبي', 'نبغى', 'تبي', 'تبغى', 'يبي', 'يبغى',
    'عندك', 'عندج', 'عندكم', 'فيكم', 'تقدرون', 'تكفون', 'يا جماعة',
    'يا شباب', 'يا بنات', 'يا اخوان', 'ياحلوين', 'الرجاء', 'لو سمحتم',
    'جزاكم الله خير', 'يعطيكم العافية', 'بيض الله وجهكم', 'يسعدكم ربي',

    # مساعدة في الاختبارات
    'كويز', 'اختبار', 'امتحان', 'فاينل', 'ميد', 'كويزات', 'اختبارات',
    'مراجعة', 'ليلة الامتحان', 'اسئلة', 'نماذج', 'تجميعات',
]

# كلمات مفتاحية تدل على أن المرسل معلن (يقدم خدمات) - مع تنويعات
MARKETER_KEYWORDS = [
    # كلمات خدمية
    'نقدم', 'نوفر', 'لدينا', 'عندنا', 'يتوفر', 'خدمات', 'خدمة', 'مساعدة',
    'إنجاز', 'تنفيذ', 'عمل', 'أعمال', 'حل', 'حلول',

    # عروض وخصومات
    'عرض', 'عروض', 'خصم', 'تخفيض', 'حسم', 'لفترة محدودة', 'العرض ساري',
    'بمناسبة', 'فرصة', 'خصم خاص', 'خصم 50', 'خصم 30',

    # تواصل
    'للتواصل', 'راسلني', 'كلمني', 'تواصل', 'واتس', 'واتساب', 'wa.me',
    't.me', 'تلجرام', 'تيليجرام', 'قناتي', 'بوت', 'رابط',

    # أسماء شركات/منصات
    'شركة', 'مؤسسة', 'أكاديمية', 'منصة', 'فريق', 'نخبة', 'خبراء',
    'متخصصون', 'محترفون', 'مكتب', 'مركز',

    # صياغات إعلانية
    'احترافي', 'ممتاز', 'أفضل', 'الأفضل', 'بجودة عالية', 'بدقة', 'بسرعة',
    'في الموعد', 'ضمان', 'ثقة', 'أمانة', 'نضمن لك', 'لسنا الوحيدون',
    'لكننا الأفضل', 'العدد محدود', 'باقي عدد', 'انضم', 'سارع', 'اغتنم',
    'احجز', 'اشترك', 'عضوية', 'باقة',

    # خدمات محددة (غالباً ما يذكرها المعلنون)
    'حل واجبات', 'حل واجب', 'بحوث', 'تقرير', 'تقارير', 'مشاريع', 'مشروع',
    'بروجكت', 'ترجمة', 'تلخيص', 'تحليل إحصائي', 'spss', 'تصميم', 'جرافيك',
    'سيرة ذاتية', 'بوستر', 'برزنتيشن', 'بوربوينت', 'أبحاث', 'رسائل',
    'ماجستير', 'دكتوراه', 'ترقية', 'نشر علمي', 'مؤتمر',

    # روابط وأرقام
    r'\+?\d{9,}',  # أرقام هواتف
    r'@\w+',       # يوزرات تلجرام
]

# كلمات استفسارية (غير واضحة النية)
INQUIRY_KEYWORDS = [
    'هل', 'هل فيه', 'هل في', 'ليش', 'لشنو', 'وش', 'وشو', 'ايش', 'ماهو',
    'ماهي', 'كيف', 'كيفية', 'متى', 'وين', 'من وين', 'كم', 'كم سعر',
    'كم التكلفة', 'بكم', 'أحد جرب', 'من جرب', 'تجربة', 'نصيحة', 'رأيكم',
    'ش رايكم', 'شو رأيك', 'شفتو', 'تقرأ عن', 'تسمع عن', 'طريقة', 'كيفية',
    'استفسار', 'سؤال', 'عندي سؤال', 'عندي استفسار',
]

# دوال مساعدة للتصنيف المبني على القواعد

def normalize_text(text):
    """تطبيع النص للتعامل مع التنوعات اللغوية (الهمزات، التاء المربوطة، الألف المقصورة)"""
    text = text.lower()
    # توحيد الهمزات
    text = re.sub(r'[إأآا]', 'ا', text)
    text = re.sub(r'[ى]', 'ي', text)
    text = re.sub(r'[ة]', 'ه', text)
    # إزالة الحركات (اختياري)
    text = re.sub(r'[\u064B-\u0652]', '', text)  # إزالة الفتحة والضمة والكسرة
    return text

def contains_any(text, keywords):
    """التحقق من وجود أي كلمة من القائمة في النص (مع التطبيع)"""
    normalized = normalize_text(text)
    for kw in keywords:
        # تطبيع الكلمة المفتاحية أيضاً
        normalized_kw = normalize_text(kw)
        if normalized_kw in normalized:
            return True
    return False

def count_keywords(text, keywords):
    """حساب عدد الكلمات المفتاحية الموجودة في النص"""
    normalized = normalize_text(text)
    count = 0
    for kw in keywords:
        normalized_kw = normalize_text(kw)
        if normalized_kw in normalized:
            count += 1
    return count

def has_link(text):
    """كشف الروابط بأنواعها"""
    patterns = [
        r'https?://\S+', r't\.me/\S+', r'wa\.me/\S+', r'telegram\.me/\S+',
        r'@\w+', r'\+\d{9,}', r'\d{10,}',  # أرقام هواتف
        r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'  # بريد إلكتروني
    ]
    for pat in patterns:
        if re.search(pat, text):
            return True
    return False

def has_emoji(text):
    """الكشف عن الرموز التعبيرية"""
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F"  # emoticons
        u"\U0001F300-\U0001F5FF"  # symbols & pictographs
        u"\U0001F680-\U0001F6FF"  # transport & map symbols
        u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
        u"\U00002500-\U00002BEF"  # chinese char
        u"\U00002702-\U000027B0"
        u"\U000024C2-\U0001F251"
        u"\U0001f926-\U0001f937"
        u"\U00010000-\U0010ffff"
        u"\u2600-\u26FF\u2B50\u23F8\u23F9\u23FA"
        "]+", flags=re.UNICODE)
    return bool(emoji_pattern.search(text))

def detect_markdown(text):
    """كشف التنسيقات (قوائم، نجوم، إلخ)"""
    patterns = [
        r'\*.*\*', r'\-.*\-', r'^\d+\.', r'^\•', r'^\-', r'^\*', r'^\d+\)',
        r'\[.*\]\(.*\)', r'\|.*\|', r'^\#', r'^#{1,6}', r'✅', r'⭐', r'♦️',
        r'▪️', r'▫️', r'🔹', r'🔸', r'🛑', r'⚠️'
    ]
    for pat in patterns:
        if re.search(pat, text, re.MULTILINE):
            return True
    return False

def has_list_pattern(text):
    """كشف وجود قائمة منظمة (عدة أسطر تبدأ برموز)"""
    lines = text.split('\n')
    list_markers = ['•', '-', '*', '▪️', '▫️', '🔹', '🔸', '⭐', '✅', '♦️', '◾', '◽']
    count = 0
    for line in lines:
        line = line.strip()
        if line and (line[0] in list_markers or line.startswith(tuple(str(i)+'.' for i in range(1,10)))):
            count += 1
    return count >= 3

def classify_local(text):
    """
    تصنيف محلي يعتمد على القواعد (بدون ذكاء اصطناعي خارجي)
    يرجع dict: {'type': 'seeker'/'inquiry'/'marketer', 'confidence': 0-100, 'reason': str}
    """
    text = text.strip()
    if not text:
        return {'type': 'inquiry', 'confidence': 0, 'reason': 'empty'}

    # حساب النتائج
    seeker_count = count_keywords(text, SEEKER_KEYWORDS)
    marketer_count = count_keywords(text, MARKETER_KEYWORDS)
    inquiry_count = count_keywords(text, INQUIRY_KEYWORDS)
    links = has_link(text)
    emojis = has_emoji(text)
    markdown = detect_markdown(text)
    listy = has_list_pattern(text)
    length = len(text)
    has_question_mark = '?' in text or '؟' in text

    # وزن النتائج
    score_seeker = seeker_count * 3 + (1 if not links else 0) + (1 if has_question_mark and seeker_count > 0 else 0)
    score_marketer = marketer_count * 4 + (5 if links else 0) + (3 if listy else 0) + (2 if markdown else 0) + (1 if emojis else 0)
    score_inquiry = inquiry_count * 2 + (2 if has_question_mark else 0) + (1 if length < 150 and seeker_count == 0 and marketer_count == 0 else 0)

    # تسجيل لأغراض التصحيح
    logging.debug(f"Seeker score: {score_seeker}, Marketer: {score_marketer}, Inquiry: {score_inquiry}")

    # تحديد النوع بناءً على أعلى درجة
    if score_marketer > score_seeker and score_marketer > score_inquiry and score_marketer >= 3:
        return {'type': 'marketer', 'confidence': min(100, score_marketer * 10), 'reason': f'marker_score={score_marketer}'}
    elif score_seeker > score_marketer and score_seeker > score_inquiry and score_seeker >= 2:
        return {'type': 'seeker', 'confidence': min(100, score_seeker * 10), 'reason': f'seeker_score={score_seeker}'}
    elif score_inquiry > score_seeker and score_inquiry > score_marketer and score_inquiry >= 1:
        return {'type': 'inquiry', 'confidence': min(100, score_inquiry * 15), 'reason': f'inquiry_score={score_inquiry}'}
    else:
        # لو مش واضح، نصنف كـ seeker افتراضياً (لأننا لا نريد فقدان طلاب)
        return {'type': 'seeker', 'confidence': 30, 'reason': 'default'}

# -------------------- دوال التصنيف بـ OpenRouter (اختياري) --------------------
async def classify_with_openrouter(text, api_key, prompt_template):
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        # استخدام برومبت متخصص للتصنيف الثلاثي مع مراعاة العامية
        enhanced_prompt = prompt_template + """

قواعد التصنيف (مع مراعاة العامية الخليجية والعربية):
- **seeker**: يطلب مساعدة في إنجاز عمل (حل واجب، مشروع، بحث، ترجمة، تصميم، ...). يستخدم عبارات مثل "ابي احد", "تعرفون احد", "من يعرف", "يشرح", "يحل", "يسوي", "محتاج". غالباً ما يكون طلباً مباشراً للقيام بمهمة.
- **inquiry**: استفسار عام، سؤال عن معلومات، رأي، خبرة. مثل "هل فيه أحد يشرح؟", "كيف أسوي؟", "وين ألقى؟", "ليش؟". لا يطلب تنفيذ العمل مباشرة، بل يسأل عن كيفية أو عن مصدر.
- **marketer**: إعلان أو ترويج لخدمات، عرض، قائمة خدمات، روابط واتساب، عروض تجارية. يحتوي على كلمات مثل "نقدم", "خصم", "للتواصل", "شركة", "خدمات". قد تكون رسالة طويلة منظمة مع رموز ترويجية.

أعد JSON فقط بالشكل:
{"type": "seeker" أو "inquiry" أو "marketer", "confidence": 0-100, "reason": "سبب مختصر بالعربية"}
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
                                    headers=headers, json=data, timeout=20) as resp:
                if resp.status != 200:
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
    future = asyncio.Future()
    verification_requests[phone] = {"future": future, "type": "code"}
    logging.info(f"📱 طلب رمز تحقق للحساب {phone}")
    return await future

async def get_verification_password(phone):
    future = asyncio.Future()
    verification_requests[phone] = {"future": future, "type": "password"}
    logging.info(f"🔐 طلب كلمة مرور للتحقق بخطوتين للحساب {phone}")
    return await future

# -------------------- دالة مراقبة حساب واحد --------------------
async def monitor_account(acc, openrouter_cfg):
    phone = acc['phone']
    api_id = acc['api_id']
    api_hash = acc['api_hash']
    main_channel = acc.get('main_channel', '')
    inquiry_channel = acc.get('inquiry_channel', '')
    spam_channel = acc.get('spam_channel', '')

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

        # التحقق من القنوات
        for ch in [main_channel, inquiry_channel, spam_channel]:
            if ch:
                try:
                    await client.get_entity(ch)
                    logging.info(f"📢 القناة {ch} متاحة")
                except Exception as e:
                    logging.warning(f"⚠️ لا يمكن الوصول للقناة {ch}: {e}")

        @client.on(events.NewMessage)
        async def handler(event):
            if not running or not event.is_group:
                return
            if event.out:
                return

            # نقرأ الكلمات المفتاحية من الملف (كمرشح أولي)
            targets = load_keywords()
            msg_text = event.raw_text
            msg_lower = msg_text.lower()

            # إذا لم تحتوي الرسالة على أي كلمة من القائمة، نتجاهلها (توفير للموارد)
            if targets and not any(kw.lower() in msg_lower for kw in targets):
                return

            chat = await event.get_chat()
            chat_name = getattr(chat, 'title', 'غير معروف')
            logging.info(f"🔍 رصد رسالة في '{chat_name}' بواسطة {phone}")

            # التصنيف المتقدم
            intent = "seeker"  # افتراضي
            confidence = 50
            reason = ""

            if openrouter_cfg.get("enabled") and openrouter_cfg.get("api_key"):
                # استخدام الذكاء الاصطناعي الخارجي
                ai_result = await classify_with_openrouter(
                    msg_text,
                    openrouter_cfg["api_key"],
                    openrouter_cfg.get("prompt", "قم بتصنيف الرسالة إلى seeker, inquiry, أو marketer.")
                )
                if ai_result:
                    intent = ai_result.get("type", "seeker")
                    confidence = ai_result.get("confidence", 50)
                    reason = ai_result.get("reason", "")
                    logging.info(f"🤖 AI: {intent} (ثقة {confidence}) - {reason}")
            else:
                # تصنيف محلي يعتمد على القواعد
                local = classify_local(msg_text)
                intent = local['type']
                confidence = local['confidence']
                reason = local['reason']
                logging.info(f"📊 محلي: {intent} (ثقة {confidence}) - {reason}")

            # اختيار القناة المستهدفة
            target_channel = None
            if intent == "marketer" and spam_channel:
                target_channel = spam_channel
                logging.info(f"📢 معلن -> قناة المعلنين")
            elif intent == "inquiry" and inquiry_channel:
                target_channel = inquiry_channel
                logging.info(f"❓ استفسار -> قناة الاستفسارات")
            elif intent == "seeker" and main_channel:
                target_channel = main_channel
                logging.info(f"✅ طالب -> القناة الرئيسية")
            else:
                # إذا لم توجد القناة المناسبة، نرسل للقناة الرئيسية إن وجدت
                target_channel = main_channel or inquiry_channel or spam_channel
                logging.warning(f"⚠️ لم تحدد القناة المناسبة، نرسل إلى أول قناة متاحة")

            if not target_channel:
                logging.warning(f"⚠️ لا توجد قناة محددة للحساب {phone}")
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

            # بناء الإشعار (مع إضافة التصنيف)
            info = (
                f"🚨 **رادار ذكي - تصنيف: {intent}**\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"📝 النص الأصلي: {msg_text}\n"
                f"👤 المرسل: {sender_name} - [رابط]({sender_link})\n"
                f"🏢 المجموعة: {chat_name} - [رابط]({chat_link})\n"
                f"👤 الحساب الراصد: {phone}\n"
                f"🤖 التصنيف: {intent} (ثقة {confidence}%)\n"
                f"📊 السبب: {reason}\n"
                f"━━━━━━━━━━━━━━━━━━━"
            )

            try:
                dest = await client.get_entity(target_channel)
                # محاولة إعادة التوجيه
                try:
                    await client.forward_messages(dest, event.message)
                    await client.send_message(dest, info)
                    logging.info(f"📤 تم إرسال التنبيه (إعادة توجيه) إلى {target_channel}")
                except errors.ChatForwardsRestrictedError:
                    # إذا منع التحويل، نرسل نسخة مع التذييل
                    full_msg = f"{msg_text}\n\n{info}"
                    if event.message.media:
                        await client.send_file(dest, event.message.media, caption=full_msg)
                    else:
                        await client.send_message(dest, full_msg)
                    logging.info(f"📤 تم إرسال التنبيه (نسخة) إلى {target_channel}")
                except errors.FloodWaitError as e:
                    logging.warning(f"⏳ Flood wait {e.seconds} ثانية، انتظار...")
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    logging.error(f"❌ فشل إرسال التنبيه: {e}")
            except Exception as e:
                logging.error(f"❌ فشل الحصول على كيان القناة المستهدفة {target_channel}: {e}")

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

# -------------------- دوال تحميل/حفظ الإعدادات (مثل السابق) --------------------
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
    # قائمة افتراضية موسعة
    default_keywords = [
        'مساعدة', 'ساعدوني', 'ساعدني', 'أبي أحد', 'أبي حد', 'أبي مساعدة',
        'محتاج', 'محتاجة', 'ضروري', 'واجب', 'واجبات', 'تكليف', 'تكاليف',
        'بحث', 'بحوث', 'تقرير', 'تقارير', 'مشروع', 'مشاريع', 'بروجكت',
        'برزنتيشن', 'عرض', 'تصميم', 'فيديو', 'اختبار', 'كويز', 'امتحان',
        'شرح', 'يشرح', 'درس', 'ملخص', 'دروس خصوصية', 'تعرفون أحد', 'تعرفون حد',
        'من يعرف', 'من تعرف', 'أحد يعرف', 'حد يعرف', 'وين ألقى', 'كيف ألقى',
        'ترجمة', 'تلخيص', 'تدقيق', 'كتابة', 'إعداد', 'حل', 'يحل', 'يسوي',
        'ابي', 'ابغى', 'تعرفون', 'خصوصي', 'مدرس خصوصي', 'دكتور خصوصي',
        'كويزات', 'اختبارات', 'فاينل', 'ميد', 'نشر', 'رسالة', 'ماجستير',
    ]
    save_keywords(default_keywords)
    return default_keywords

def save_keywords(keywords_list):
    with open(KEYWORDS_FILE, 'w', encoding='utf-8') as f:
        f.write("\n".join(keywords_list))

# -------------------- تطبيق Flask --------------------
app = Flask(__name__)
app.secret_key = os.urandom(24)

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
                <h3>🔐 إدخال رمز التحقق</h3>
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
                
                <label>القناة الرئيسية (للطلاب)</label>
                <input type="text" name="main_channel" placeholder="https://t.me/...">
                
                <label>قناة الاستفسارات (للأسئلة العامة)</label>
                <input type="text" name="inquiry_channel" placeholder="https://t.me/...">
                
                <label>قناة المعلنين (للإعلانات)</label>
                <input type="text" name="spam_channel" placeholder="https://t.me/...">
                
                <button type="submit">💾 إضافة الحساب</button>
            </form>
        </div>

        <div class="card">
            <h2>📋 الحسابات المضافة</h2>
            <table>
                <tr>
                    <th>رقم الهاتف</th>
                    <th>القناة الرئيسية</th>
                    <th>قناة الاستفسارات</th>
                    <th>قناة المعلنين</th>
                    <th>الإجراءات</th>
                </tr>
                {% for acc in accounts %}
                <tr>
                    <td>{{ acc.phone }}</td>
                    <td>{{ acc.main_channel or 'غير محدد' }}</td>
                    <td>{{ acc.inquiry_channel or 'غير محدد' }}</td>
                    <td>{{ acc.spam_channel or 'غير محدد' }}</td>
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
            <h2>🔑 الكلمات المفتاحية (للفلترة الأولية)</h2>
            <form action="/save_keywords" method="post">
                <textarea name="keywords" rows="8" placeholder="كلمة في كل سطر">{{ keywords | join('\n') }}</textarea>
                <button type="submit">💾 حفظ الكلمات</button>
            </form>
        </div>

        <div class="card">
            <h2>🤖 إعدادات OpenRouter (التصنيف الذكي)</h2>
            <form action="/save_openrouter" method="post">
                <label>مفتاح API (اتركه فارغاً لتعطيل التصنيف الخارجي)</label>
                <input type="text" name="api_key" value="{{ openrouter.api_key }}">
                
                <label>تعليمات التصنيف (prompt)</label>
                <textarea name="prompt" rows="5">{{ openrouter.prompt }}</textarea>
                
                <label>
                    <input type="checkbox" name="enabled" {% if openrouter.enabled %}checked{% endif %}> تفعيل التصنيف الخارجي (إذا لم يفعل، سيتم استخدام التصنيف المحلي)
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
    openrouter_cfg = config.get("openrouter", {"api_key": "", "enabled": False, "prompt": "قم بتصنيف الرسالة إلى seeker, inquiry, أو marketer."})
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
    main_channel = request.form.get('main_channel', '').strip()
    inquiry_channel = request.form.get('inquiry_channel', '').strip()
    spam_channel = request.form.get('spam_channel', '').strip()
    
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
        "main_channel": main_channel,
        "inquiry_channel": inquiry_channel,
        "spam_channel": spam_channel
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

if __name__ == '__main__':
    if not os.path.exists(KEYWORDS_FILE):
        save_keywords([])  # سيتم إنشاء القائمة الافتراضية في load_keywords
    if not os.path.exists(CONFIG_FILE):
        save_config([], {"api_key": "", "enabled": False, "prompt": "قم بتصنيف الرسالة إلى seeker, inquiry, أو marketer."})
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
