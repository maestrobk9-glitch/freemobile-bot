import os
import json
import time
import random
import uuid
import requests
import threading

from flask import Flask
from playwright.sync_api import sync_playwright

app = Flask(__name__)

# ============================================================
# CONFIG
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    ""
)

CHAT_ID = os.environ.get(
    "CHAT_ID",
    ""
)

# رابط البروكسي المستخدم في المتصفح (مثال: http://user:pass@ip:port)
PROXY_URL = os.environ.get("PROXY_URL", "")

# رابط الـ API الخاص بمزود البروكسي لتغيير الـ IP فوراً (إذا توفر لدى الشركة التي تشتري منها البروكسي)
CHANGE_IP_API = os.environ.get("CHANGE_IP_API", "")

TARGET_URL = "https://mobile.free.fr/souscription/options"

RENDER_EXTERNAL_URL = os.environ.get(
    "RENDER_EXTERNAL_URL",
    "https://freemobile-bot.onrender.com"
).rstrip("/")

SESSION_DIR = "vip_sessions"

os.makedirs(
    SESSION_DIR,
    exist_ok=True
)

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.0 Mobile/15E148 Safari/604.1"
)

ACTIVE_SESSIONS = {}
ACTIVE_SESSIONS_LOCK = threading.Lock()


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():
    return """
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Free Mobile VIP</title>
    </head>
    <body style="background:#0f172a;color:white;font-family:Arial;text-align:center;padding:50px;">
        <h2>🚀 FreeMobile VIP Engine يعمل مع تغيير الـ IP</h2>
    </body>
    </html>
    """


# ============================================================
# VIP LINK & SESSION MANAGEMENT
# ============================================================

@app.route("/vip/<session_id>")
def view_vip_session(session_id):
    meta_file = os.path.join(SESSION_DIR, f"{session_id}.meta.json")
    state_file = os.path.join(SESSION_DIR, f"{session_id}.json")

    if not os.path.exists(meta_file) or not os.path.exists(state_file):
        return ("<h3>⚠️ الجلسة غير موجودة.</h3>", 404)

    try:
        with open(meta_file, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        number = metadata.get("number", "غير معروف")
        open_url = f"{RENDER_EXTERNAL_URL}/vip/{session_id}/open"

        html = f"""
        <!DOCTYPE html>
        <html lang="ar" dir="rtl">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Free Mobile VIP</title>
            <style>
                body {{ margin:0; background:#0f172a; color:white; font-family:Tahoma,Arial; text-align:center; padding:50px 15px; }}
                .card {{ max-width:500px; margin:auto; background:#1e293b; padding:30px; border-radius:18px; box-shadow:0 15px 40px rgba(0,0,0,.45); }}
                h1 {{ color:#38bdf8; }}
                .number {{ color:#facc15; font-size:36px; font-weight:bold; margin:25px 0; direction:ltr; }}
                .button {{ display:block; background:#10b981; color:white; text-decoration:none; padding:16px; border-radius:10px; font-size:18px; font-weight:bold; margin-top:25px; }}
                .info {{ color:#cbd5e1; line-height:1.8; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h1>🔥 رقم VIP</h1>
                <div class="number">{number}</div>
                <div class="info">تم العثور على الرقم وحفظ جلسة Free Mobile.<br><br>اضغط لفتح جلسة الرقم.</div>
                <a class="button" href="{open_url}">🚀 فتح جلسة Free Mobile</a>
            </div>
        </body>
        </html>
        """
        return html
    except Exception as e:
        return (f"<h3>❌ خطأ: {e}</h3>", 500)


@app.route("/vip/<session_id>/open")
def open_vip_session(session_id):
    meta_file = os.path.join(SESSION_DIR, f"{session_id}.meta.json")
    state_file = os.path.join(SESSION_DIR, f"{session_id}.json")

    if not os.path.exists(meta_file) or not os.path.exists(state_file):
        return ("<h3>❌ الجلسة غير موجودة.</h3>", 404)

    try:
        with open(meta_file, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        number = metadata.get("number", "")

        with ACTIVE_SESSIONS_LOCK:
            active = ACTIVE_SESSIONS.get(session_id)

        if active and active.get("page") and not active.get("page").is_closed():
            return f"<h2>🔥 جلسة الرقم مفتوحة</h2><h1 style='color:#facc15;direction:ltr;'>{number}</h1>"

        with sync_playwright() as p:
            launch_args = {"headless": True}
            if PROXY_URL:
                launch_args["proxy"] = {"server": PROXY_URL}

            browser = p.chromium.launch(**launch_args)
            context = browser.new_context(
                storage_state=state_file,
                user_agent=MOBILE_UA,
                viewport={"width": 390, "height": 844},
                device_scale_factor=3,
                is_mobile=True,
                has_touch=True,
                locale="fr-FR"
            )
            page = context.new_page()
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)

            with ACTIVE_SESSIONS_LOCK:
                ACTIVE_SESSIONS[session_id] = {
                    "browser": browser,
                    "context": context,
                    "page": page,
                    "number": number,
                    "created": time.time()
                }

            return f"<h2>🔥 تم فتح جلسة Free Mobile</h2><h1 style='color:#facc15;direction:ltr;'>{number}</h1>"
    except Exception as e:
        return (f"<h3>❌ خطأ: {e}</h3>", 500)


# ============================================================
# VIP EVALUATOR & HELPERS
# ============================================================

def evaluate_vip_expanded(num):
    clean = str(num).replace(" ", "").replace("-", "").replace(".", "")
    if not (len(clean) == 10 and (clean.startswith("06") or clean.startswith("07"))):
        return None
    d = clean[2:]
    if len(set(d)) <= 4:
        return "تنوع منخفض للأرقام"
    if d == d[::-1]:
        return "مرآة متناظرة كاملة"
    if d[:4] == d[4:]:
        return "نصفين متطابقين"
    sequences = [
        "0123", "1234", "2345", "3456", "4567",
        "5678", "6789", "9876", "8765", "7654",
        "6543", "5432", "4321", "3210"
    ]
    if any(seq in d for seq in sequences):
        return "تسلسل أرقام متتالي"
    if len(set(d[-4:])) <= 2 or len(set(d[:4])) <= 2:
        return "تكرار عالي في الأطراف"
    if d[0] == d[1] == d[2] or d[-3] == d[-2] == d[-1]:
        return "ثلاثية متتالية"
    return None


def select_number(page, number):
    target = "".join(c for c in str(number) if c.isdigit())
    try:
        selects = page.locator("select")
        for i in range(selects.count()):
            sel = selects.nth(i)
            options = sel.locator("option")
            for j in range(options.count()):
                combined = (options.nth(j).get_attribute("value") or "") + " " + (options.nth(j).inner_text() or "")
                if target in "".join(c for c in combined if c.isdigit()):
                    sel.select_option(index=j, force=True)
                    time.sleep(0.5)
                    return True
    except Exception:
        pass
    return False


def verify_number_on_page(page, number):
    target = "".join(c for c in str(number) if c.isdigit())
    try:
        text = page.locator("body").inner_text(timeout=5000)
        return target in "".join(c for c in text if c.isdigit())
    except Exception:
        return False


def save_session_state(context, page, number):
    session_id = uuid.uuid4().hex
    safe_number = "".join(c for c in str(number) if c.isdigit())
    state_file = os.path.join(SESSION_DIR, f"{session_id}.json")
    meta_file = os.path.join(SESSION_DIR, f"{session_id}.meta.json")
    try:
        context.storage_state(path=state_file, indexed_db=True)
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump({
                "session_id": session_id,
                "number": safe_number,
                "created": int(time.time()),
                "state_file": state_file
            }, f)
        return session_id
    except Exception:
        return None


def send_telegram_alert(number, desc, session_id):
    if not TELEGRAM_BOT_TOKEN or not CHAT_ID:
        return
    open_url = f"{RENDER_EXTERNAL_URL}/vip/{session_id}"
    message = (
        "🔥 *رقم VIP جديد!*\n\n"
        f"📱 الرقم: `{number}`\n"
        f"💎 التصنيف: {desc}\n\n"
        f"🔗 [فتح الجلسة]({open_url})"
    )
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": message,
                "parse_mode": "Markdown"
            },
            timeout=10
        )
    except Exception:
        pass


def request_new_ip_from_proxy():
    """وظيفة لتغيير الـ IP عبر الـ API الخاص بالبروكسي إذا كان متوفراً"""
    if CHANGE_IP_API:
        try:
            requests.get(CHANGE_IP_API, timeout=10)
            print("🔄 تم إرسال طلب تغيير الـ IP إلى مزود البروكسي بنجاح.", flush=True)
            time.sleep(3) # الانتظار قليلاً حتى يتم تغيير الـ IP فعلياً
        except Exception as e:
            print(f"⚠️ فشل تغيير الـ IP عبر الـ API: {e}", flush=True)


# ============================================================
# MONITOR WITH FORCED IP ROTATION
# ============================================================

def run_smart_proxy_monitor():
    print("🚀 بدء محرك الفحص مع نظام التغيير الاجباري للـ IP عند غياب الأرقام...", flush=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"

    empty_scans_count = 0

    try:
        with sync_playwright() as p:
            while True:
                browser = None
                context = None
                page = None

                try:
                    # إذا لم يتم العثور على أرقام لمدة مرتين، نقوم بطلب IP جديد ومسح الجلسة
                    if empty_scans_count >= 2:
                        print("🔄 لم يتم العثور على أرقام، جاري تغيير الـ IP فوراً...", flush=True)
                        request_new_ip_from_proxy()
                        empty_scans_count = 0

                    launch_args = {"headless": True}
                    if PROXY_URL:
                        launch_args["proxy"] = {"server": PROXY_URL}

                    browser = p.chromium.launch(**launch_args)
                    context = browser.new_context(
                        user_agent=MOBILE_UA,
                        viewport={"width": 390, "height": 844},
                        device_scale_factor=3,
                        is_mobile=True,
                        has_touch=True,
                        locale="fr-FR"
                    )
                    page = context.new_page()

                    print("🌐 فتح صفحة Free Mobile بالفحص الجديد...", flush=True)
                    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
                    time.sleep(4)

                    numbers_list = page.evaluate("""
                        () => {
                            let results = [];
                            const elements = document.querySelectorAll('select option, div, span, option');
                            elements.forEach(el => {
                                let text = el.innerText || el.value || '';
                                const matches = text.match(/0[67][\\s\\d\\.]{8,}/g);
                                if (matches) {
                                    matches.forEach(m => {
                                        let cleanNum = m.replace(/\\D/g, '');
                                        if (cleanNum.length === 10) {
                                            results.push(cleanNum);
                                        }
                                    });
                                }
                            });
                            return [...new Set(results)];
                        }
                    """)

                    if not numbers_list:
                        print("⚠️ الصفحة فارغة ولم يتم رصد أي أرقام، سيتم تغيير الـ IP في المرة القادمة...", flush=True)
                        empty_scans_count += 1
                        time.sleep(4)
                        continue

                    empty_scans_count = 0
                    print(f"📊 عدد الأرقام المكتشفة: {len(numbers_list)}", flush=True)

                    found_vip = False
                    for num_val in numbers_list:
                        vip_desc = evaluate_vip_expanded(num_val)
                        if not vip_desc:
                            continue

                        print(f"🔥🔥🔥 VIP FOUND: {num_val} | {vip_desc}", flush=True)

                        if not select_number(page, num_val):
                            continue
                        time.sleep(1)
                        if not verify_number_on_page(page, num_val):
                            continue

                        session_id = save_session_state(context, page, num_val)
                        if not session_id:
                            continue

                        with ACTIVE_SESSIONS_LOCK:
                            ACTIVE_SESSIONS[session_id] = {
                                "browser": browser,
                                "context": context,
                                "page": page,
                                "number": num_val,
                                "created": time.time()
                            }

                        browser = None
                        context = None
                        page = None

                        send_telegram_alert(num_val, vip_desc, session_id)
                        found_vip = True
                        break

                    if not found_vip:
                        print("ℹ️ الأرقام المتاحة عادية، الانتقال للدورة التالية...", flush=True)

                except Exception as e:
                    print(f"⚠️ LOOP ERROR: {repr(e)}", flush=True)
                    empty_scans_count += 1

                finally:
                    try:
                        if page:
                            page.close()
                    except Exception:
                        pass
                    try:
                        if context:
                            context.close()
                    except Exception:
                        pass
                    try:
                        if browser:
                            browser.close()
                    except Exception:
                        pass

                time.sleep(random.uniform(3.0, 5.0))

    except Exception as e:
        print(f"❌ FATAL: {repr(e)}", flush=True)


# ============================================================
# CLEAN SESSIONS & RUN APP
# ============================================================

def cleanup_sessions():
    while True:
        try:
            now = time.time()
            for filename in os.listdir(SESSION_DIR):
                if not filename.endswith(".meta.json"):
                    continue
                meta_path = os.path.join(SESSION_DIR, filename)
                with open(meta_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                if now - metadata.get("created", 0) > 1800:
                    session_id = metadata.get("session_id")
                    with ACTIVE_SESSIONS_LOCK:
                        active = ACTIVE_SESSIONS.pop(session_id, None)
                    if active:
                        try:
                            active["browser"].close()
                        except Exception:
                            pass
                    for suffix in [".meta.json", ".json", ".session.json"]:
                        p_file = os.path.join(SESSION_DIR, f"{session_id}{suffix}")
                        if os.path.exists(p_file):
                            os.remove(p_file)
        except Exception:
            pass
        time.sleep(300)


monitor_started = False
monitor_lock = threading.Lock()

@app.before_request
def trigger_background_monitor():
    global monitor_started
    with monitor_lock:
        if not monitor_started:
            monitor_started = True
            threading.Thread(target=run_smart_proxy_monitor, daemon=True).start()
            threading.Thread(target=cleanup_sessions, daemon=True).start()
            print("[SYSTEM] Monitor started", flush=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
