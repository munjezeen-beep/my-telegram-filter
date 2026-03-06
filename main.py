# -*- coding: utf-8 -*-
import asyncio
import os
import json
import re
import logging
import threading
from datetime import datetime
from flask import Flask, render_template_string, request, redirect, url_for, jsonify
from telethon import TelegramClient, events
import aiohttp

# -------------------- الإعدادات الأساسية --------------------
BASE_DIR = os.path.dirname(os.path.realpath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'radar_config.json')
KEYWORDS_FILE = os.path.join(BASE_DIR, 'radar_keywords.txt')
LOG_FILE = os.path.join(BASE_DIR, 'radar.log')

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
            return [line.strip() for line in f if line.strip()]
    return []

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
        data = {
            "model": "qwen/qwen3-vl-30b-a3b-thinking",
            "messages": [
                {"role": "system", "content": prompt_template},
                {"role": "user", "content": text}
            ]
        }
        async with aiohttp.ClientSession() as session:
            async with session.post("https://openrouter.ai/api/v1/chat/completions",
                                    headers=headers, json=data) as resp:
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
        await client.start(phone=phone)
        logging.info(f"✅ {phone} connected")

        if alert_group:
            try:
                await client.get_entity(alert_group)
                logging.info(f"📢 Alert group {alert_group} accessible")
            except Exception as e:
                logging.warning(f"⚠️ Cannot access alert group {alert_group}: {e}")

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
                if kw in msg_lower:
                    chat = await event.get_chat()
                    chat_name = getattr(chat, 'title', 'unknown')
                    logging.info(f"🔍 Keyword '{kw}' in '{chat_name}' by {phone}")

                    # التصنيف الذكي
                    sender_type = None
                    confidence = 0
                    if openrouter_cfg.get("enabled") and openrouter_cfg.get("api_key"):
                        ai_result = await classify_with_openrouter(
                            msg_text,
                            openrouter_cfg["api_key"],
                            openrouter_cfg.get("prompt", "")
                        )
                        if ai_result:
                            sender_type = ai_result.get("type")
                            confidence = ai_result.get("confidence", 0)
                            reason = ai_result.get("reason", "")
                            logging.info(f"🤖 AI: {sender_type} ({confidence}%) - {reason}")
                            if sender_type == "marketer" and confidence > 60:
                                logging.info(f"🚫 Ignored marketer message")
                                return  # لا ترسل

                    # إرسال الإشعار فقط إذا كان seeker (أو التصنيف معطل)
                    if alert_group:
                        try:
                            dest = await client.get_entity(alert_group)
                            info = (f"🚨 **New Radar Alert**\n"
                                    f"🔍 Keyword: {kw}\n"
                                    f"👥 Group: {chat_name}\n"
                                    f"👤 Account: {phone}")
                            if sender_type:
                                info += f"\n🤖 AI: {sender_type} ({confidence}%)"
                            await client.send_message(dest, info)
                            await client.forward_messages(dest, event.message)
                            logging.info(f"📤 Alert sent")
                        except Exception as e:
                            logging.error(f"Failed to send alert: {e}")
                    break

        await client.run_until_disconnected()
    except Exception as e:
        logging.error(f"Error in account {phone}: {e}")
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
        logging.error("No accounts to run")
        return
    logging.info(f"🚀 Starting radar with {len(acc_list)} accounts")
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
    logging.info("🛑 Radar stopped")

# -------------------- تطبيق Flask --------------------
app = Flask(__name__)

# قالب HTML مدمج (للبساطة)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>رادار التليجرام - لوحة التحكم</title>
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
        .arabic { font-family: 'Tahoma', sans-serif; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 رادار التليجرام الذكي - لوحة التحكم</h1>
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
        // تحديث تلقائي كل 10 ثوان
        setInterval(refreshLog, 10000);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    config = load_config()
    accounts_list = config.get("accounts", [])
    openrouter_cfg = config.get("openrouter", {"api_key": "", "enabled": False, "prompt": ""})
    keywords_list = load_keywords()
    
    # قراءة آخر 100 سطر من السجل
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
    # التحقق من عدم تكرار الرقم
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
        save_keywords(["بحث", "واجب", "تقارير", "مساعدة", "شرح"])
    if not os.path.exists(CONFIG_FILE):
        save_config([], {"api_key": "", "enabled": False, "prompt": "قم بتحليل الرسالة وتحديد ما إذا كان المرسل مسوقاً أو باحثاً."})
    
    # تشغيل خادم Flask (يمكن تغيير المنفذ)
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
