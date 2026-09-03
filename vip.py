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

# ============================================================
# ACTIVE SESSIONS
# ============================================================

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
        <meta name="viewport"
              content="width=device-width,initial-scale=1">
        <title>Free Mobile VIP</title>
    </head>

    <body style="
        background:#0f172a;
        color:white;
        font-family:Arial;
        text-align:center;
        padding:50px;
    ">

        <h2>
            🚀 FreeMobile VIP Engine يعمل
        </h2>

    </body>
    </html>
    """


# ============================================================
# VIP LINK
# ============================================================

@app.route("/vip/<session_id>")
def view_vip_session(session_id):

    meta_file = os.path.join(
        SESSION_DIR,
        f"{session_id}.meta.json"
    )

    state_file = os.path.join(
        SESSION_DIR,
        f"{session_id}.json"
    )

    if not os.path.exists(meta_file):

        return (
            "<h3>⚠️ الجلسة غير موجودة.</h3>",
            404
        )

    if not os.path.exists(state_file):

        return (
            "<h3>⚠️ ملف الجلسة غير موجود.</h3>",
            404
        )

    try:

        with open(
            meta_file,
            "r",
            encoding="utf-8"
        ) as f:

            metadata = json.load(f)

        number = metadata.get(
            "number",
            "غير معروف"
        )

        open_url = (
            f"{RENDER_EXTERNAL_URL}"
            f"/vip/{session_id}/open"
        )

        html = f"""
        <!DOCTYPE html>

        <html lang="ar" dir="rtl">

        <head>

            <meta charset="UTF-8">

            <meta
                name="viewport"
                content="width=device-width,
                initial-scale=1"
            >

            <title>Free Mobile VIP</title>

            <style>

                body {{
                    margin:0;
                    background:#0f172a;
                    color:white;
                    font-family:Tahoma,Arial;
                    text-align:center;
                    padding:50px 15px;
                }}

                .card {{
                    max-width:500px;
                    margin:auto;
                    background:#1e293b;
                    padding:30px;
                    border-radius:18px;
                    box-shadow:
                        0 15px 40px
                        rgba(0,0,0,.45);
                }}

                h1 {{
                    color:#38bdf8;
                }}

                .number {{
                    color:#facc15;
                    font-size:36px;
                    font-weight:bold;
                    margin:25px 0;
                    direction:ltr;
                }}

                .button {{
                    display:block;
                    background:#10b981;
                    color:white;
                    text-decoration:none;
                    padding:16px;
                    border-radius:10px;
                    font-size:18px;
                    font-weight:bold;
                    margin-top:25px;
                }}

                .info {{
                    color:#cbd5e1;
                    line-height:1.8;
                }}

            </style>

        </head>

        <body>

            <div class="card">

                <h1>
                    🔥 رقم VIP
                </h1>

                <div class="number">
                    {number}
                </div>

                <div class="info">

                    تم العثور على الرقم
                    وحفظ جلسة Free Mobile.

                    <br><br>

                    اضغط لفتح جلسة الرقم.

                </div>

                <a
                    class="button"
                    href="{open_url}"
                >
                    🚀 فتح جلسة Free Mobile
                </a>

            </div>

        </body>

        </html>
        """

        return html

    except Exception as e:

        return (
            f"<h3>❌ خطأ: {e}</h3>",
            500
        )


# ============================================================
# OPEN SAVED SESSION
# ============================================================

@app.route("/vip/<session_id>/open")
def open_vip_session(session_id):

    meta_file = os.path.join(
        SESSION_DIR,
        f"{session_id}.meta.json"
    )

    state_file = os.path.join(
        SESSION_DIR,
        f"{session_id}.json"
    )

    if not os.path.exists(meta_file):

        return (
            "<h3>❌ الجلسة غير موجودة.</h3>",
            404
        )

    if not os.path.exists(state_file):

        return (
            "<h3>❌ ملف الجلسة غير موجود.</h3>",
            404
        )

    try:

        with open(
            meta_file,
            "r",
            encoding="utf-8"
        ) as f:

            metadata = json.load(f)

        number = metadata.get(
            "number",
            ""
        )

        with ACTIVE_SESSIONS_LOCK:

            active = ACTIVE_SESSIONS.get(
                session_id
            )

        if active:

            page = active.get("page")

            try:

                if page and not page.is_closed():

                    current_url = page.url

                    return f"""
                    <!DOCTYPE html>
                    <html lang="ar" dir="rtl">
                    <head>
                        <meta charset="UTF-8">
                        <meta name="viewport" content="width=device-width, initial-scale=1">
                        <title>VIP Session</title>
                    </head>
                    <body style="background:#0f172a;color:white;font-family:Arial;text-align:center;padding:50px 15px;">
                        <h2>🔥 جلسة الرقم مفتوحة</h2>
                        <h1 style="color:#facc15;direction:ltr;">{number}</h1>
                        <p>الجلسة محفوظة على الخادم.</p>
                        <p>URL: {current_url}</p>
                    </body>
                    </html>
                    """

            except Exception:
                pass

        print(
            f"🔄 إعادة إنشاء جلسة: {session_id}",
            flush=True
        )

        with sync_playwright() as p:

            browser = p.chromium.launch(
                headless=True
            )

            context = browser.new_context(
                storage_state=state_file,
                user_agent=MOBILE_UA,
                viewport={
                    "width":390,
                    "height":844
                },
                device_scale_factor=3,
                is_mobile=True,
                has_touch=True,
                locale="fr-FR"
            )

            page = context.new_page()

            page.goto(
                TARGET_URL,
                wait_until="domcontentloaded",
                timeout=30000
            )

            time.sleep(2)

            with ACTIVE_SESSIONS_LOCK:

                ACTIVE_SESSIONS[
                    session_id
                ] = {
                    "browser":browser,
                    "context":context,
                    "page":page,
                    "number":number,
                    "created":time.time()
                }

            return f"""
            <!DOCTYPE html>
            <html lang="ar" dir="rtl">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <title>Free Mobile VIP</title>
            </head>
            <body style="background:#0f172a;color:white;font-family:Arial;text-align:center;padding:50px;">
                <h2>🔥 تم فتح جلسة Free Mobile</h2>
                <h1 style="color:#facc15;direction:ltr;">{number}</h1>
                <p>الجلسة تم تحميلها بواسطة Playwright.</p>
            </body>
            </html>
            """

    except Exception as e:

        return (
            f"<h3>❌ خطأ: {e}</h3>",
            500
        )


# ============================================================
# VIP EVALUATOR
# ============================================================

def evaluate_vip_expanded(num):

    clean = (
        str(num)
        .replace(" ", "")
        .replace("-", "")
        .replace(".", "")
    )

    if not (
        len(clean) == 10
        and (
            clean.startswith("06")
            or
            clean.startswith("07")
        )
    ):

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


# ============================================================
# VERIFY NUMBER
# ============================================================

def verify_number_on_page(page, number):

    target = "".join(c for c in str(number) if c.isdigit())

    try:
        text = page.locator("body").inner_text(timeout=5000)
        digits = "".join(c for c in text if c.isdigit())
        if target in digits:
            return True
    except Exception:
        pass

    return False


# ============================================================
# SELECT NUMBER
# ============================================================

def select_number(page, number):

    target = "".join(c for c in str(number) if c.isdigit())

    try:
        selects = page.locator("select")
        count = selects.count()
        for i in range(count):
            sel = selects.nth(i)
            options = sel.locator("option")
            for j in range(options.count()):
                option = options.nth(j)
                combined = (option.get_attribute("value") or "") + " " + (option.inner_text() or "")
                digits = "".join(c for c in combined if c.isdigit())
                if target in digits:
                    sel.select_option(index=j, force=True)
                    time.sleep(0.4)
                    page.evaluate("(el) => { el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }", sel)
                    time.sleep(1)
                    return True
    except Exception:
        pass

    try:
        locator = page.get_by_text(target, exact=False)
        if locator.count() > 0:
            locator.first.click(force=True, timeout=3000)
            time.sleep(1)
            return True
    except Exception:
        pass

    return False


# ============================================================
# SAVE SESSION
# ============================================================

def save_session_state(context, page, number):

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
            "state_file": state_file,
            "target_url": TARGET_URL
        }

        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        return session_id
    except Exception as e:
        return None


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram_alert(number, desc, session_id):

    if not TELEGRAM_BOT_TOKEN or not CHAT_ID:
        return

    open_url = f"{RENDER_EXTERNAL_URL}/vip/{session_id}"
    message = (
        "🔥 *رقم VIP جديد!*\n\n"
        f"📱 الرقم: `{number}`\n"
        f"💎 التصنيف: {desc}\n\n"
        "🔐 تم حفظ جلسة Free Mobile.\n\n"
        f"🔗 [فتح الجلسة]({open_url})"
    )

    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }

    try:
        requests.post(telegram_url, json=payload, timeout=10)
    except Exception:
        pass


# ============================================================
# MONITOR
# ============================================================

def run_smart_proxy_monitor():

    print("🚀 بدء محرك فحص الأرقام المحدث...", flush=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"

    try:
        with sync_playwright() as p:
            print("✅ PLAYWRIGHT READY", flush=True)

            while True:
                browser = None
                context = None
                page = None

                try:
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context(
                        user_agent=MOBILE_UA,
                        viewport={"width": 390, "height": 844},
                        device_scale_factor=3,
                        is_mobile=True,
                        has_touch=True,
                        locale="fr-FR"
                    )
                    page = context.new_page()

                    print("🌐 فتح Free Mobile...", flush=True)
                    response = page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
                    time.sleep(3)

                    # استخراج الأرقام مباشرة من محتوى الصفحة والـ DOM والعناصر المتاحة
                    numbers_list = page.evaluate("""
                        () => {
                            let results = [];
                            const elements = document.querySelectorAll('select option, input, div, span, label, p');
                            elements.forEach(el => {
                                let text = el.innerText || el.value || el.textContent || '';
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
                        print("⚠️ لم يتم العثور على أرقام في الصفحة حالياً، إعادة المحاولة...", flush=True)
                        continue

                    print(f"📊 عدد الأرقام المكتشفة: {len(numbers_list)}", flush=True)

                    for num_val in numbers_list:
                        vip_desc = evaluate_vip_expanded(num_val)
                        if not vip_desc:
                            continue

                        print(f"🔥🔥🔥 VIP FOUND: {num_val} | {vip_desc}", flush=True)

                        selected = select_number(page, num_val)
                        if not selected:
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
                        break

                except Exception as e:
                    print(f"⚠️ LOOP ERROR: {repr(e)}", flush=True)

                finally:
                    try:
                        if page: page.close()
                    except Exception:
                        pass
                    try:
                        if context: context.close()
                    except Exception:
                        pass
                    try:
                        if browser: browser.close()
                    except Exception:
                        pass

                time.sleep(random.uniform(2.5, 4.5))

    except Exception as e:
        print(f"❌ FATAL: {repr(e)}", flush=True)


# ============================================================
# CLEAN OLD SESSIONS
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
                        try: active["page"].close()
                        except Exception: pass
                        try: active["context"].close()
                        except Exception: pass
                        try: active["browser"].close()
                        except Exception: pass
                    for suffix in [".meta.json", ".json", ".session.json"]:
                        path = os.path.join(SESSION_DIR, f"{session_id}{suffix}")
                        if os.path.exists(path):
                            os.remove(path)
        except Exception:
            pass
        time.sleep(300)


# ============================================================
# START MONITOR
# ============================================================

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


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
