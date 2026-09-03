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

TARGET_URL = "https://mobile.free.fr/souscription/options"
SESSION_DIR = "vip_sessions"
os.makedirs(SESSION_DIR, exist_ok=True)

@app.route("/vip/<session_id>")
def view_vip_session(session_id):
    state_file = os.path.join(SESSION_DIR, f"{session_id}.json")
    meta_file = os.path.join(SESSION_DIR, f"{session_id}.meta.json")
    
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
            <title>تم اختيار الرقم المميز بنجاح!</title>
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
                <h1>🔥 تم تثبيت واختيار الرقم المميز!</h1>
                <div class="number">{number}</div>
                <div class="loader"></div>
                <p>جاري نقلك إلى موقع Free Mobile لتجد الرقم بانتظارك...</p>
            </div>
            <script>
                setTimeout(function() {{
                    window.location.href = "https://mobile.free.fr/souscription/options";
                }}, 1200);
            </script>
        </body>
        </html>
        """
        
        response = make_response(html_content)
        response.set_cookie("vip_active_session", session_id, max_age=300)
        return response

    except Exception as e:
        return f"<h3>حدث خطأ أثناء تحميل الجلسة: {e}</h3>", 500

@app.route("/")
def home():
    return "<h3>🚀 FreeMobile VIP Engine v79 يعمل بكفاءة عالية وبدون توقف!</h3>"

def evaluate_vip_expanded(num):
    clean = str(num).replace(" ", "").replace("-", "")
    if not (len(clean) == 10 and (clean.startswith("06") or clean.startswith("07"))):
        return None
    d = clean[2:]

    if len(set(d)) <= 4: return "تنوع منخفض للأرقام (مميز)"
    if d == d[::-1]: return "مرآة متناظرة كاملة (Palindrome)"
    if d[:4] == d[4:]: return "نصفين متطابقين تماماً"
    
    if any(seq in d for seq in ["0123", "1234", "2345", "3456", "4567", "5678", "6789", "9876", "8765", "7654", "6543", "5432", "4321", "3210"]):
        return "تسلسل أرقام متتالي"

    if len(set(d[-4:])) <= 2 or len(set(d[:4])) <= 2: return "تكرار عالي في الأطراف"
    if d[0] == d[1] == d[2] or d[-3] == d[-2] == d[-1]: return "ثلاثية متتالية"

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

        print(f"💾 [حفظ الجلسة] تم حفظ جلسة VIP للرقم: {safe_number}", flush=True)
        return session_id
    except Exception as e:
        print(f"⚠️ فشل حفظ حالة الجلسة: {e}", flush=True)
        return None

def send_telegram_alert(number, desc, session_id):
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "https://freemobile-bot.onrender.com").rstrip("/")
    open_url = f"{render_url}/vip/{session_id}"

    message = (
        "🔥 *رقم مميز VIP جديد (مختار تلقائياً)!*\n\n"
        f"📱 الرقم: `{number}`\n"
        f"💎 التصنيف: {desc}\n\n"
        f"🔗 [اضغط هنا للدخول وإتمام الشراء مباشرة]({open_url})"
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
            print("📨 تم إرسال تنبيه Telegram بنجاح", flush=True)
        else:
            print("⚠️ Telegram رفض الرسالة:", response.text, flush=True)
    except Exception as e:
        print(f"⚠️ خطأ إرسال Telegram: {e}", flush=True)

def run_smart_proxy_monitor():
    print("🚀 بدء تشغيل محرك تدوير الجلسات وفحص الأرقام في الخلفية...", flush=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"

    try:
        with sync_playwright() as p:
            print("✅ [PLAYWRIGHT] تم تفعيل المتصفح السحابي بنجاح", flush=True)
            while True:
                browser = None
                try:
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context(
                        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
                    )
                    page = context.new_page()
                    
                    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=25000)
                    time.sleep(1.5)

                    # تفعيل خيار "رقم جديد" تلقائياً
                    page.evaluate("""
                        () => {
                            const labels = Array.from(document.querySelectorAll('label, div, span'));
                            const newNumLabel = labels.find(el => el.textContent.includes('nouveau numéro'));
                            if (newNumLabel) {
                                newNumLabel.click();
                            }
                            const radios = document.querySelectorAll('input[type="radio"]');
                            radios.forEach(r => {
                                if (r.value && (r.value.includes('new') || r.value.includes('nouveau') || r.id.includes('new'))) {
                                    r.click();
                                    r.checked = true;
                                    r.dispatchEvent(new Event('change', { bubbles: true }));
                                }
                            });
                        }
                    """)
                    time.sleep(1.0)

                    numbers_data = page.evaluate("""
                        async () => {
                            try {
                                const res = await fetch('./api/msisdns?' + Math.random(), {
                                    headers: { 
                                        'X-Requested-With': 'XMLHttpRequest',
                                        'Cache-Control': 'no-cache'
                                    }
                                });
                                if (res.ok) return await res.json();
                            } catch (e) {}
                            return null;
                        }
                    """)

                    if numbers_data:
                        numbers_list = numbers_data if isinstance(numbers_data, list) else numbers_data.get("msisdns", [])
                        if numbers_list:
                            for item in numbers_list:
                                num_val = item.get("value") if isinstance(item, dict) else str(item)
                                if not num_val:
                                    continue

                                vip_desc = evaluate_vip_expanded(num_val)
                                if vip_desc:
                                    print(f"🔥🔥🔥 VIP FOUND! الرقم: {num_val} | التصنيف: {vip_desc}", flush=True)
                                    
                                    try:
                                        page.evaluate(f"""
                                            (targetNum) => {{
                                                const selects = document.querySelectorAll('select');
                                                selects.forEach(sel => {{
                                                    for (let i = 0; i < sel.options.length; i++) {{
                                                        let opt = sel.options[i];
                                                        if (opt.value.includes(targetNum) || opt.text.includes(targetNum)) {{
                                                            sel.selectedIndex = i;
                                                            sel.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                                            sel.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                                        }}
                                                    }}
                                                }});
                                            }}
                                        """, num_val)
                                        time.sleep(0.3)
                                    except Exception as ex:
                                        print(f"⚠️ خطأ في اختيار الرقم: {ex}", flush=True)

                                    session_id = save_vip_session(context, num_val)
                                    if session_id:
                                        send_telegram_alert(num_val, vip_desc, session_id)
                                    break
                    
                    if browser:
                        browser.close()
                except Exception as e:
                    print(f"⚠️ [LOOP ERROR]: {e}", flush=True)
                    if browser:
                        try:
                            browser.close()
                        except Exception:
                            pass

                time.sleep(random.uniform(2.5, 4.5))
    except Exception as e:
        print(f"❌ خطأ فادح في المحرك: {e}", flush=True)

# تشغيل البوت ذاتياً لمنع النوم على Render
def self_ping_worker():
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "https://freemobile-bot.onrender.com")
    while True:
        try:
            requests.get(render_url, timeout=10)
        except:
            pass
        time.sleep(180) # كل 3 دقائق

# إطلاق المحرك فوراً عند تشغيل الملف وليس عند أول طلب زائر
if __name__ == "__main__":
    t_monitor = threading.Thread(target=run_smart_proxy_monitor, daemon=True)
    t_monitor.start()
    print("[SYSTEM] تم بدء محرك فحص الأرقام فوراً مع إقلاع السيرفر!", flush=True)

    t_ping = threading.Thread(target=self_ping_worker, daemon=True)
    t_ping.start()

    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
