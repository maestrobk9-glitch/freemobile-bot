import os
import json
import time
import random
import uuid
import requests
import threading
import sys

from flask import Flask, make_response
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
TARGET_URL = "https://mobile.free.fr/souscription/options"
SESSION_DIR = "vip_sessions"
os.makedirs(SESSION_DIR, exist_ok=True)

# إدارة تدوير البروكسيات لتغيير الـ IP عند الحاجة
CURRENT_PROXY_INDEX = 0

def get_next_working_proxy():
    global CURRENT_PROXY_INDEX
    proxies_env = os.environ.get("PROXIES_LIST", "")
    proxy_list = [p.strip() for p in proxies_env.split(",") if p.strip()]
    if not proxy_list:
        return None
    proxy = proxy_list[CURRENT_PROXY_INDEX % len(proxy_list)]
    CURRENT_PROXY_INDEX += 1
    return proxy

@app.route("/")
def home():
    return """
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head><meta charset="UTF-8"><title>FreeMobile VIP Bot</title></head>
    <body style="font-family:Arial;text-align:center;padding:50px">
        <h2>🚀 FreeMobile VIP Bot (vip pro) يعمل بكفاءة</h2>
    </body>
    </html>
    """

@app.route("/vip/<session_id>")
def view_vip_session(session_id):
    state_file = os.path.join(SESSION_DIR, f"{session_id}.json")
    meta_file = os.path.join(SESSION_DIR, f"{session_id}.meta.json")
    if not os.path.exists(meta_file):
        return "<h3 style='text-align:center'>⚠️ هذه الجلسة غير موجودة.</h3>", 404

    try:
        with open(meta_file, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        number = metadata.get("number", "غير معروف")
        
        html = f"""
        <!DOCTYPE html>
        <html lang="ar" dir="rtl">
        <head>
            <meta charset="UTF-8">
            <title>Free Mobile VIP</title>
            <style>
                body {{ margin:0; background:#0f172a; color:white; font-family:Arial,sans-serif; text-align:center; padding:50px 15px; }}
                .card {{ max-width:500px; margin:auto; background:#1e293b; padding:35px 20px; border-radius:18px; box-shadow:0 10px 30px rgba(0,0,0,.4); }}
                .number {{ direction:ltr; color:#facc15; font-size:38px; font-weight:bold; margin:25px 0; }}
                .button {{ display:block; margin-top:25px; padding:16px; background:#16a34a; color:white; text-decoration:none; border-radius:12px; font-weight:bold; font-size:18px; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h1>🔥 تم العثور على رقم VIP</h1>
                <div class="number">{number}</div>
                <a class="button" href="https://mobile.free.fr/souscription/options">فتح Free Mobile</a>
            </div>
        </body>
        </html>
        """
        response = make_response(html)
        response.set_cookie("vip_active_session", session_id, max_age=600, httponly=True, samesite="Lax")
        return response
    except Exception as e:
        return f"<h3 style='text-align:center'>⚠️ حدث خطأ: {e}</h3>", 500

def evaluate_vip_expanded(num):
    clean = str(num).replace(" ", "").replace("-", "").strip()
    if not (len(clean) == 10 and (clean.startswith("06") or clean.startswith("07"))):
        return None
    d = clean[2:]
    if len(set(d)) <= 4: return "تنوع منخفض للأرقام (مميز)"
    if d == d[::-1]: return "مرآة متناظرة كاملة (Palindrome)"
    if d[:4] == d[4:]: return "نصفين متطابقين تماماً"
    
    sequences = ["0123", "1234", "2345", "3456", "4567", "5678", "6789", "9876", "8765", "7654", "6543", "5432", "4321", "3210"]
    for seq in sequences:
        if seq in d: return "تسلسل أرقام متتالي"
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
        metadata = {"session_id": session_id, "number": safe_number, "created": int(time.time()), "state_file": state_file}
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        print(f"💾 [SESSION] تم حفظ جلسة الرقم {safe_number}", flush=True)
        return session_id
    except Exception as e:
        print(f"⚠️ [SESSION] فشل حفظ الجلسة: {e}", flush=True)
        return None

def send_telegram_alert(number, desc, session_id):
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "https://freemobile-bot.onrender.com").rstrip("/")
    open_url = f"{render_url}/vip/{session_id}"
    message = f"🔥 *رقم مميز VIP جديد!*\n\n📱 الرقم: `{number}`\n💎 التصنيف: {desc}\n\n🔗 [عرض الرقم وفتح Free Mobile]({open_url})"
    if not TELEGRAM_BOT_TOKEN or not CHAT_ID: return
    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try:
        requests.post(telegram_url, json=payload, timeout=10)
    except Exception:
        pass

def select_number(page, number):
    target = str(number).replace(" ", "").replace("-", "").strip()
    try:
        radio_count = page.locator('input[type="radio"]').count()
        for i in range(radio_count):
            try:
                radio = page.locator('input[type="radio"]').nth(i)
                combined = (str(radio.get_attribute("value")) + " " + str(radio.get_attribute("id"))).lower()
                if "new" in combined or "nouveau" in combined:
                    try: radio.check(force=True, timeout=2000)
                    except: radio.click(force=True, timeout=2000)
                    time.sleep(0.3)
            except: continue

        select_count = page.locator("select").count()
        for i in range(select_count):
            try:
                select = page.locator("select").nth(i)
                option_count = select.locator("option").count()
                for j in range(option_count):
                    option = select.locator("option").nth(j)
                    val = option.get_attribute("value") or ""
                    txt = option.inner_text() or ""
                    if target in val.replace(" ", "") or target in txt.replace(" ", ""):
                        select.select_option(value=val, timeout=2000)
                        return True
            except: continue
    except:
        pass
    return False

def run_smart_proxy_monitor():
    print("🔥🔥🔥 [THREAD ACTIVE] محرك الفحص بدأ", flush=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/opt/render/project/src/pw-browsers"

    while True:
        try:
            with sync_playwright() as p:
                print("✅ [PLAYWRIGHT] تم تشغيل Playwright", flush=True)
                while True:
                    browser = None
                    context = None
                    page = None
                    try:
                        # تفعيل استخدام بروكسي جديد فوراً إذا حدث خطأ حظر سابقاً
                        force_proxy = getattr(sys, '_use_proxy_next', False)
                        current_proxy = get_next_working_proxy() if force_proxy else None

                        launch_args = {
                            "headless": True,
                            "args": ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
                        }
                        if current_proxy:
                            launch_args["proxy"] = {"server": current_proxy}
                            print(f"🔄 [IP CHANGED] تم تغيير الـ IP عبر البروكسي: {current_proxy}", flush=True)
                        else:
                            print("🌐 [IP NORMAL] العمل بالـ IP العادي...", flush=True)

                        browser = p.chromium.launch(**launch_args)
                        context = browser.new_context(
                            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
                            viewport={"width": 390, "height": 844},
                            locale="fr-FR"
                        )
                        page = context.new_page()
                        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=25000)
                        time.sleep(1.5)

                        numbers_data = page.evaluate("""
                            async () => {
                                try {
                                    const res = await fetch('./api/msisdns?' + Date.now(), {
                                        headers: { 'X-Requested-With': 'XMLHttpRequest', 'Cache-Control': 'no-cache' }
                                    });
                                    if (!res.ok) return { __error: 'HTTP ' + res.status };
                                    return await res.json();
                                } catch (e) { return { __error: String(e) }; }
                            }
                        """)

                        if isinstance(numbers_data, dict) and numbers_data.get("__error__"):
                            err_msg = str(numbers_data.get("__error__"))
                            print(f"⚠️ [API] {err_msg}", flush=True)
                            # إذا ظهر خطأ 429 أو حظر، سيتم تغيير الـ IP في المحاولة القادمة تلقائياً
                            if "429" in err_msg:
                                sys._use_proxy_next = True
                            else:
                                sys._use_proxy_next = False
                        else:
                            sys._use_proxy_next = False
                            numbers_list = numbers_data if isinstance(numbers_data, list) else numbers_data.get("msisdns", [])
                            print(f"📱 [API] عدد الأرقام: {len(numbers_list)}", flush=True)
                            
                            found = False
                            for item in numbers_list:
                                num_val = item.get("value") if isinstance(item, dict) else str(item)
                                if not num_val: continue
                                vip_desc = evaluate_vip_expanded(num_val)
                                if not vip_desc: continue
                                found = True
                                print(f"🔥🔥🔥 VIP FOUND! الرقم: {num_val}", flush=True)
                                select_number(page, num_val)
                                session_id = save_vip_session(context, num_val)
                                if session_id:
                                    send_telegram_alert(num_val, vip_desc, session_id)
                                break
                            
                            if not found:
                                print("🔍 [MONITOR] لا يوجد رقم VIP هذه المرة", flush=True)

                    except Exception as e:
                        print(f"⚠️ [LOOP ERROR] {repr(e)}", flush=True)
                    finally:
                        if browser:
                            try: browser.close()
                            except: pass

                    delay = random.uniform(2.5, 4.5)
                    time.sleep(delay)
        except Exception as e:
            print(f"❌ [PLAYWRIGHT RESTART ERROR] {repr(e)}", flush=True)
            time.sleep(5)

if __name__ == "__main__":
    monitor_thread = threading.Thread(target=run_smart_proxy_monitor, daemon=True)
    monitor_thread.start()
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
