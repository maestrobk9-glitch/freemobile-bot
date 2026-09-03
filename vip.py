import os
import json
import time
import random
import uuid
import requests
import threading
from flask import Flask, jsonify, request, redirect, render_template_string, make_response
from playwright.sync_api import sync_playwright

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "8958338182:AAH5FiqnleZK44TNsQ89FnSxGSvclweomPY"
)

CHAT_ID = os.environ.get(
    "CHAT_ID",
    "8091746597"
)

TARGET_URL = "https://mobile.free.fr/souscription/"
SESSION_DIR = "vip_sessions"
os.makedirs(SESSION_DIR, exist_ok=True)

@app.route("/vip/<session_id>")
def view_vip_session(session_id):
    meta_file = os.path.join(SESSION_DIR, f"{session_id}.meta.json")
    state_file = os.path.join(SESSION_DIR, f"{session_id}.json")
    
    if not os.path.exists(meta_file) or not os.path.exists(state_file):
        return "<h3>⚠️ هذه الجلسة غير موجودة أو انتهت صلاحيتها.</h3>", 404

    try:
        with open(meta_file, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        number = metadata.get("number", "غير معروف")

        html_content = f"""
        <!DOCTYPE html>
        <html lang="ar" dir="rtl">
        <head>
            <meta charset="UTF-8">
            <title>جاري فتح جلسة الرقم VIP...</title>
            <style>
                body {{ font-family: Tahoma, sans-serif; background: #0f172a; color: white; text-align: center; padding-top: 100px; }}
                .card {{ background: #1e293b; padding: 40px; border-radius: 12px; display: inline-block; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
                h1 {{ color: #38bdf8; }}
                .number {{ color: #facc15; font-size: 38px; font-weight: bold; margin: 20px 0; }}
                .loader {{ border: 5px solid #334155; border-top: 5px solid #10b981; border-radius: 50%; width: 50px; height: 50px; animation: spin 1s linear infinite; margin: 20px auto; }}
                @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
            </style>
        </head>
        <body>
            <div class="card">
                <h1>🔥 تم تجهيز جلسة الرقم المميز!</h1>
                <div class="number">{number}</div>
                <div class="loader"></div>
                <p>جاري نقلك مباشرة إلى موقع Free Mobile لتجد الرقم بانتظارك...</p>
            </div>
            <script>
                setTimeout(function() {{
                    window.location.href = "https://mobile.free.fr/souscription/";
                }}, 1500);
            </script>
        </body>
        </html>
        """
        
        response = make_response(html_content)
        response.set_cookie("vip_active_session", session_id, max_age=300)
        return response

    except Exception as e:
        return f"<h3>حدث خطأ أثناء فتح الجلسة: {e}</h3>", 500

@app.route("/")
def home():
    return "<h3>🚀 FreeMobile VIP Monitor يعمل بكفاءة عالية وفي الخلفية!</h3>"

def evaluate_vip(num):
    clean = str(num).replace(" ", "")
    if not (len(clean) == 10 and (clean.startswith("06") or clean.startswith("07"))):
        return None

    d = clean[2:]

    if len(set(d)) <= 4:
        return "تنوع منخفض للأرقام (مميز)"
    if d == d[::-1]:
        return "مرآة متناظرة كاملة (Palindrome)"
    if d[:4] == d[4:]:
        return "نصفين متطابقين تماماً"

    sequences = [
        "0123", "1234", "2345", "3456", "4567", "5678", "6789",
        "9876", "8765", "7654", "6543", "5432", "4321", "3210"
    ]
    if any(seq in d for seq in sequences):
        return "تسلسل أرقام متتالي"

    if len(set(d[-4:])) <= 2 or len(set(d[:4])) <= 2:
        return "تكرار عالي في الأطراف"

    if d[0] == d[1] == d[2] or d[-3] == d[-2] == d[-1]:
        return "ثلاثية متتالية"

    return None

def save_vip_session(context, number):
    session_id = uuid.uuid4().hex
    safe_number = "".join(c for c in str(number) if c.isdigit())

    state_file = os.path.join(SESSION_DIR, f"{session_id}.json")
    meta_file = os.path.join(SESSION_DIR, f"{session_id}.meta.json")

    try:
        context.storage_state(path=state_file, indexed_db=True)
        metadata = {
            "session_id": session_id,
            "number": safe_number,
            "created": int(time.time()),
            "state_file": state_file
        }

        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        print(f"💾 [حفظ استثنائي] تم حفظ جلسة VIP الرقم: {safe_number}", flush=True)
        return session_id
    except Exception as e:
        print(f"⚠️ فشل حفظ جلسة VIP: {e}", flush=True)
        return None

def send_telegram_alert(number, desc, session_id):
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "https://freemobile-bot.onrender.com").rstrip("/")
    open_url = f"{render_url}/vip/{session_id}"

    message = (
        "🔥 *رقم مميز VIP جديد!*\n\n"
        f"📱 الرقم: `{number}`\n"
        f"💎 التصنيف: {desc}\n\n"
        f"🔗 [اضغط هنا لفتح الجلسة وحجز الرقم]({open_url})"
    )

    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }

    try:
        response = requests.post(telegram_url, json=payload, timeout=10)
        if response.ok:
            print("📨 تم إرسال التنبيه إلى Telegram بنجاح", flush=True)
        else:
            print("⚠️ Telegram رفض الرسالة:", response.text, flush=True)
    except Exception as e:
        print(f"⚠️ خطأ Telegram: {e}", flush=True)

def run_smart_proxy_monitor():
    print("🚀 تشغيل محرك فحص أرقام FreeMobile VIP المستقر...", flush=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"

    try:
        with sync_playwright() as p:
            print("✅ [PLAYWRIGHT] تم تفعيل محرك المتصفح بنجاح", flush=True)
            while True:
                browser = None
                try:
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context(
                        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
                    )
                    page = context.new_page()
                    
                    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
                    time.sleep(1.5)

                    numbers_data = page.evaluate("""
                        async () => {
                            try {
                                const res = await fetch('./api/msisdns?' + Math.random(), {
                                    headers: { 'X-Requested-With': 'XMLHttpRequest' }
                                });
                                if (res.ok) return await res.json();
                            } catch (e) {}
                            return null;
                        }
                    """)

                    if numbers_data:
                        numbers_list = numbers_data if isinstance(numbers_data, list) else numbers_data.get("msisdns", [])
                        print(f"📊 [فحص] عدد الأرقام المتاحة حالياً في الموقع: {len(numbers_list)}", flush=True)
                        if numbers_list:
                            for item in numbers_list:
                                num_val = item.get("value") if isinstance(item, dict) else str(item)
                                if not num_val:
                                    continue

                                vip_desc = evaluate_vip(num_val)
                                if vip_desc:
                                    print(f"🔥🔥🔥 VIP FOUND! الرقم: {num_val} | التصنيف: {vip_desc}", flush=True)
                                    session_id = save_vip_session(context, num_val)
                                    if session_id:
                                        send_telegram_alert(num_val, vip_desc, session_id)
                                    break
                    else:
                        print("⚠️ [فحص] لم يتم استرجاع قائمة الأرقام في هذه المحاولة.", flush=True)

                    browser.close()
                except Exception as e:
                    print(f"⚠️ [MONITOR LOOP ERROR]: {e}", flush=True)
                    if browser:
                        try:
                            browser.close()
                        except:
                            pass

                time.sleep(random.uniform(4.0, 7.0))
    except Exception as e:
        print(f"❌ [FATAL PLAYWRIGHT ERROR]: {e}", flush=True)

monitor_started = False
monitor_lock = threading.Lock()

@app.before_request
def trigger_background_monitor():
    global monitor_started
    with monitor_lock:
        if not monitor_started:
            monitor_started = True
            t = threading.Thread(target=run_smart_proxy_monitor, daemon=True)
            t.start()
            print("[SYSTEM] Background monitor thread launched via web request!", flush=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
