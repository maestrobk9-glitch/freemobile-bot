import os
import json
import time
import random
import uuid
import requests
import threading

from flask import Flask, jsonify, request, redirect, render_template_string, make_response
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

app = Flask(__name__)

# ============================================================
# CONFIG
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

TARGET_URL = "https://mobile.free.fr/souscription/options"

RENDER_EXTERNAL_URL = os.environ.get(
    "RENDER_EXTERNAL_URL",
    "https://freemobile-bot.onrender.com"
).rstrip("/")

SESSION_DIR = "vip_sessions"
os.makedirs(SESSION_DIR, exist_ok=True)

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.0 Mobile/15E148 Safari/604.1"
)

# ============================================================
# GLOBAL SESSION STORAGE
# ============================================================

ACTIVE_SESSIONS = {}
ACTIVE_SESSIONS_LOCK = threading.Lock()


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():
    return """
    <h3>
        🚀 FreeMobile VIP Engine يعمل
    </h3>
    """


# ============================================================
# VIP PAGE
#
# IMPORTANT:
# We do NOT simply redirect to mobile.free.fr anymore.
# The saved browser session is opened by Playwright on the server.
# ============================================================

@app.route("/vip/<session_id>")
def view_vip_session(session_id):

    state_file = os.path.join(
        SESSION_DIR,
        f"{session_id}.json"
    )

    meta_file = os.path.join(
        SESSION_DIR,
        f"{session_id}.meta.json"
    )

    session_file = os.path.join(
        SESSION_DIR,
        f"{session_id}.session.json"
    )

    if not os.path.exists(meta_file):
        return "<h3>⚠️ الجلسة غير موجودة.</h3>", 404

    try:

        with open(meta_file, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        number = metadata.get("number", "غير معروف")

        # ----------------------------------------------------
        # Start a temporary browser viewer for this session.
        # ----------------------------------------------------

        viewer_url = f"/vip/{session_id}/open"

        html = f"""
        <!DOCTYPE html>
        <html lang="ar" dir="rtl">
        <head>
            <meta charset="UTF-8">

            <meta
                name="viewport"
                content="width=device-width,initial-scale=1"
            >

            <title>Free Mobile VIP</title>

            <style>

                body {{
                    margin:0;
                    background:#0f172a;
                    color:white;
                    font-family:Tahoma,Arial,sans-serif;
                    text-align:center;
                    padding:50px 20px;
                }}

                .card {{
                    max-width:500px;
                    margin:auto;
                    background:#1e293b;
                    padding:30px;
                    border-radius:18px;
                    box-shadow:
                        0 15px 40px rgba(0,0,0,.45);
                }}

                h1 {{
                    color:#38bdf8;
                }}

                .number {{
                    color:#facc15;
                    font-size:34px;
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
                    margin-top:25px;
                    font-size:18px;
                    font-weight:bold;
                }}

                .info {{
                    color:#cbd5e1;
                    line-height:1.8;
                }}

            </style>
        </head>

        <body>

            <div class="card">

                <h1>🔥 الرقم المميز</h1>

                <div class="number">
                    {number}
                </div>

                <div class="info">
                    تم حفظ جلسة Free Mobile على الخادم.
                    <br>
                    اضغط على الزر لفتح نفس جلسة المتصفح.
                </div>

                <a
                    class="button"
                    href="{viewer_url}"
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
            f"<h3>حدث خطأ أثناء تحميل الجلسة: {e}</h3>",
            500
        )


# ============================================================
# OPEN SESSION
#
# This launches Playwright with the saved state.
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
        return "<h3>❌ الجلسة غير موجودة.</h3>", 404

    if not os.path.exists(state_file):
        return "<h3>❌ ملف الجلسة غير موجود.</h3>", 404

    try:

        with open(meta_file, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        number = metadata.get("number", "")

        # ----------------------------------------------------
        # The actual session is opened by a server-side
        # Playwright browser.
        #
        # We use a persistent running browser session stored
        # in ACTIVE_SESSIONS.
        # ----------------------------------------------------

        with ACTIVE_SESSIONS_LOCK:

            existing = ACTIVE_SESSIONS.get(session_id)

            if existing:

                page = existing.get("page")

                if page:

                    try:
                        if not page.is_closed():

                            return f"""
                            <!DOCTYPE html>
                            <html lang="ar" dir="rtl">
                            <head>
                                <meta charset="UTF-8">
                                <meta
                                    name="viewport"
                                    content="width=device-width,initial-scale=1"
                                >
                                <meta
                                    http-equiv="refresh"
                                    content="0;url={TARGET_URL}"
                                >
                                <title>Free Mobile</title>
                            </head>
                            <body>
                                <h3>
                                    🔥 يتم فتح جلسة الرقم
                                    {number}
                                </h3>
                            </body>
                            </html>
                            """

                    except Exception:
                        pass

        # ----------------------------------------------------
        # NOTE:
        # HTTP cannot directly attach the user's phone browser
        # to Playwright.
        #
        # Instead we expose the server session through a
        # controlled browser page below.
        # ----------------------------------------------------

        return f"""
        <!DOCTYPE html>
        <html lang="ar" dir="rtl">

        <head>

            <meta charset="UTF-8">

            <meta
                name="viewport"
                content="width=device-width,initial-scale=1"
            >

            <title>Free Mobile VIP</title>

            <style>

                body {{
                    background:#0f172a;
                    color:white;
                    font-family:Arial;
                    text-align:center;
                    padding:50px 15px;
                }}

                .card {{
                    max-width:550px;
                    margin:auto;
                    background:#1e293b;
                    padding:30px;
                    border-radius:15px;
                }}

                .number {{
                    color:#facc15;
                    font-size:30px;
                    margin:20px;
                    direction:ltr;
                }}

                .warning {{
                    color:#fbbf24;
                    line-height:1.8;
                }}

            </style>

        </head>

        <body>

            <div class="card">

                <h2>🔥 جلسة Free Mobile محفوظة</h2>

                <div class="number">
                    {number}
                </div>

                <p class="warning">
                    الجلسة محفوظة على الخادم.
                    <br><br>
                    لا يمكن للمتصفح الموجود على الهاتف
                    استيراد BrowserContext الخاص بـ Playwright
                    تلقائياً.
                </p>

                <p>
                    لذلك يجب استخدام نفس المتصفح الموجود
                    على الخادم أو بناء Proxy/Remote Browser
                    للوصول إليه.
                </p>

            </div>

        </body>

        </html>
        """

    except Exception as e:

        return f"<h3>❌ خطأ: {e}</h3>", 500


# ============================================================
# NUMBER EVALUATION
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
            or clean.startswith("07")
        )
    ):
        return None

    d = clean[2:]

    if len(set(d)) <= 4:
        return "تنوع منخفض للأرقام"

    if d == d[::-1]:
        return "Palindrome"

    if d[:4] == d[4:]:
        return "نصفين متطابقين"

    sequences = [
        "0123",
        "1234",
        "2345",
        "3456",
        "4567",
        "5678",
        "6789",
        "9876",
        "8765",
        "7654",
        "6543",
        "5432",
        "4321",
        "3210",
    ]

    if any(seq in d for seq in sequences):
        return "تسلسل أرقام"

    if (
        len(set(d[-4:])) <= 2
        or
        len(set(d[:4])) <= 2
    ):
        return "تكرار عالي في الأطراف"

    if (
        d[0] == d[1] == d[2]
        or
        d[-3] == d[-2] == d[-1]
    ):
        return "ثلاثية متتالية"

    return None


# ============================================================
# SESSION STORAGE
# ============================================================

def save_session_state(context, page, number):

    session_id = uuid.uuid4().hex

    safe_number = "".join(
        c for c in str(number)
        if c.isdigit()
    )

    state_file = os.path.join(
        SESSION_DIR,
        f"{session_id}.json"
    )

    meta_file = os.path.join(
        SESSION_DIR,
        f"{session_id}.meta.json"
    )

    session_file = os.path.join(
        SESSION_DIR,
        f"{session_id}.session.json"
    )

    try:

        # ----------------------------------------------------
        # Save cookies + localStorage + IndexedDB
        # ----------------------------------------------------

        context.storage_state(
            path=state_file,
            indexed_db=True
        )

        # ----------------------------------------------------
        # sessionStorage is NOT included automatically.
        # Save it separately.
        # ----------------------------------------------------

        try:

            session_storage = page.evaluate(
                "() => JSON.stringify(sessionStorage)"
            )

        except Exception:

            session_storage = "{}"

        with open(
            session_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                {
                    "sessionStorage": json.loads(
                        session_storage or "{}"
                    )
                },
                f,
                ensure_ascii=False,
                indent=2
            )

        # ----------------------------------------------------
        # Save metadata
        # ----------------------------------------------------

        metadata = {
            "session_id": session_id,
            "number": safe_number,
            "created": int(time.time()),
            "state_file": state_file,
            "session_file": session_file,
            "target_url": TARGET_URL
        }

        with open(
            meta_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                metadata,
                f,
                ensure_ascii=False,
                indent=2
            )

        print(
            f"💾 SESSION SAVED: {safe_number}",
            flush=True
        )

        return session_id

    except Exception as e:

        print(
            f"❌ SESSION SAVE ERROR: {e}",
            flush=True
        )

        return None


# ============================================================
# VERIFY NUMBER INSIDE PAGE
# ============================================================

def verify_number_on_page(page, number):

    clean_target = "".join(
        c for c in str(number)
        if c.isdigit()
    )

    try:

        # ----------------------------------------------------
        # Check visible text
        # ----------------------------------------------------

        body_text = page.locator("body").inner_text(
            timeout=5000
        )

        body_digits = "".join(
            c for c in body_text
            if c.isdigit()
        )

        if clean_target in body_digits:
            print(
                f"✅ الرقم {number} موجود في الصفحة",
                flush=True
            )

            return True

    except Exception:
        pass

    try:

        # ----------------------------------------------------
        # Check selected options
        # ----------------------------------------------------

        selected = page.locator(
            "select option:checked"
        )

        count = selected.count()

        for i in range(count):

            try:

                text = selected.nth(i).inner_text()

                digits = "".join(
                    c for c in text
                    if c.isdigit()
                )

                if clean_target in digits:

                    print(
                        f"✅ الرقم {number} محدد فعلياً",
                        flush=True
                    )

                    return True

            except Exception:
                pass

    except Exception:
        pass

    try:

        # ----------------------------------------------------
        # Check inputs
        # ----------------------------------------------------

        inputs = page.locator(
            "input, select"
        )

        count = inputs.count()

        for i in range(count):

            try:

                value = inputs.nth(i).input_value()

                digits = "".join(
                    c for c in str(value)
                    if c.isdigit()
                )

                if clean_target in digits:

                    print(
                        f"✅ الرقم {number} موجود في input",
                        flush=True
                    )

                    return True

            except Exception:
                pass

    except Exception:
        pass

    return False


# ============================================================
# SELECT NUMBER
# ============================================================

def select_number(page, number):

    clean_number = "".join(
        c for c in str(number)
        if c.isdigit()
    )

    print(
        f"🎯 محاولة اختيار: {clean_number}",
        flush=True
    )

    # --------------------------------------------------------
    # First try native select
    # --------------------------------------------------------

    try:

        selects = page.locator("select")

        count = selects.count()

        for i in range(count):

            sel = selects.nth(i)

            try:

                options = sel.locator("option")

                option_count = options.count()

                for j in range(option_count):

                    option = options.nth(j)

                    value = option.get_attribute("value")
                    text = option.inner_text()

                    combined = (
                        str(value or "")
                        + " "
                        + str(text or "")
                    )

                    digits = "".join(
                        c for c in combined
                        if c.isdigit()
                    )

                    if clean_number in digits:

                        sel.select_option(
                            index=j,
                            force=True
                        )

                        time.sleep(0.5)

                        # Trigger the real DOM events
                        page.evaluate(
                            """
                            (el) => {
                                el.dispatchEvent(
                                    new Event(
                                        'input',
                                        {bubbles:true}
                                    )
                                );

                                el.dispatchEvent(
                                    new Event(
                                        'change',
                                        {bubbles:true}
                                    )
                                );
                            }
                            """,
                            sel
                        )

                        time.sleep(0.5)

                        print(
                            "✅ تم اختيار الرقم من select",
                            flush=True
                        )

                        return True

            except Exception:
                continue

    except Exception:
        pass

    # --------------------------------------------------------
    # Second method: click element containing number
    # --------------------------------------------------------

    try:

        locator = page.get_by_text(
            clean_number,
            exact=False
        )

        count = locator.count()

        if count > 0:

            for i in range(min(count, 10)):

                try:

                    locator.nth(i).click(
                        force=True,
                        timeout=3000
                    )

                    time.sleep(0.5)

                    print(
                        "✅ تم الضغط على الرقم",
                        flush=True
                    )

                    return True

                except Exception:
                    continue

    except Exception:
        pass

    # --------------------------------------------------------
    # Third method: generic DOM search
    # --------------------------------------------------------

    try:

        result = page.evaluate(
            """
            (target) => {

                const all =
                    document.querySelectorAll(
                        'button, label, div, span, option, input'
                    );

                for (const el of all) {

                    const text =
                        (el.innerText || '') +
                        ' ' +
                        (el.value || '') +
                        ' ' +
                        (el.getAttribute('value') || '');

                    const digits =
                        text.replace(/\\D/g, '');

                    if (
                        digits.includes(target) &&
                        el.offsetParent !== null
                    ) {

                        try {
                            el.click();
                            return true;
                        } catch(e) {}
                    }
                }

                return false;
            }
            """,
            clean_number
        )

        if result:

            time.sleep(0.5)

            print(
                "✅ تم اختيار الرقم عبر DOM",
                flush=True
            )

            return True

    except Exception as e:

        print(
            f"⚠️ DOM selection error: {e}",
            flush=True
        )

    return False


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram_alert(
    number,
    desc,
    session_id
):

    if not TELEGRAM_BOT_TOKEN or not CHAT_ID:

        print(
            "⚠️ Telegram variables غير موجودة",
            flush=True
        )

        return

    open_url = (
        f"{RENDER_EXTERNAL_URL}/vip/{session_id}"
    )

    message = (
        "🔥 *رقم مميز VIP جديد!*\n\n"
        f"📱 الرقم: `{number}`\n"
        f"💎 التصنيف: {desc}\n\n"
        "🔐 تم حفظ جلسة Free Mobile على الخادم.\n\n"
        f"🔗 [فتح جلسة الرقم]({open_url})"
    )

    telegram_url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }

    try:

        response = requests.post(
            telegram_url,
            json=payload,
            timeout=10
        )

        if response.ok:

            print(
                "📨 Telegram OK",
                flush=True
            )

        else:

            print(
                "❌ Telegram ERROR:",
                response.text,
                flush=True
            )

    except Exception as e:

        print(
            f"❌ Telegram exception: {e}",
            flush=True
        )


# ============================================================
# MONITOR
# ============================================================

def run_smart_proxy_monitor():

    print(
        "🚀 بدء مراقبة Free Mobile...",
        flush=True
    )

    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"

    try:

        with sync_playwright() as p:

            print(
                "✅ Playwright جاهز",
                flush=True
            )

            while True:

                browser = None
                context = None
                page = None

                try:

                    browser = p.chromium.launch(
                        headless=True
                    )

                    context = browser.new_context(
                        user_agent=MOBILE_UA,
                        viewport={
                            "width": 390,
                            "height": 844
                        },
                        device_scale_factor=3,
                        is_mobile=True,
                        has_touch=True
                    )

                    page = context.new_page()

                    # ------------------------------------------------
                    # Network logging
                    # Useful for discovering what Free actually
                    # sends when a number is selected.
                    # ------------------------------------------------

                    def log_request(req):

                        url = req.url.lower()

                        if (
                            "msisdn" in url
                            or
                            "numero" in url
                            or
                            "number" in url
                        ):

                            print(
                                f"🌐 REQUEST: "
                                f"{req.method} {req.url}",
                                flush=True
                            )

                    page.on(
                        "request",
                        log_request
                    )

                    # ------------------------------------------------
                    # Open Free
                    # ------------------------------------------------

                    page.goto(
                        TARGET_URL,
                        wait_until="domcontentloaded",
                        timeout=30000
                    )

                    time.sleep(1)

                    # ------------------------------------------------
                    # Fetch available numbers from SAME page context
                    # ------------------------------------------------

                    numbers_data = page.evaluate(
                        """
                        async () => {

                            try {

                                const res =
                                    await fetch(
                                        './api/msisdns?' +
                                        Math.random(),
                                        {
                                            credentials: 'include',
                                            headers: {
                                                'X-Requested-With':
                                                    'XMLHttpRequest',

                                                'Cache-Control':
                                                    'no-cache'
                                            }
                                        }
                                    );

                                if (res.ok) {
                                    return await res.json();
                                }

                            } catch(e) {}

                            return null;
                        }
                        """
                    )

                    if not numbers_data:

                        print(
                            "⚠️ لم تصل أرقام",
                            flush=True
                        )

                    else:

                        numbers_list = (
                            numbers_data
                            if isinstance(
                                numbers_data,
                                list
                            )
                            else
                            numbers_data.get(
                                "msisdns",
                                []
                            )
                        )

                        print(
                            f"📡 أرقام مستلمة: "
                            f"{len(numbers_list)}",
                            flush=True
                        )

                        for item in numbers_list:

                            if isinstance(item, dict):

                                num_val = item.get(
                                    "value"
                                )

                            else:

                                num_val = str(item)

                            if not num_val:
                                continue

                            vip_desc = (
                                evaluate_vip_expanded(
                                    num_val
                                )
                            )

                            if not vip_desc:
                                continue

                            print(
                                f"🔥 VIP FOUND: "
                                f"{num_val} | "
                                f"{vip_desc}",
                                flush=True
                            )

                            # ------------------------------------------------
                            # Select the number
                            # ------------------------------------------------

                            selected = select_number(
                                page,
                                num_val
                            )

                            if not selected:

                                print(
                                    "⚠️ لم أستطع اختيار الرقم",
                                    flush=True
                                )

                                continue

                            # ------------------------------------------------
                            # Give the application time to update
                            # its internal state.
                            # ------------------------------------------------

                            time.sleep(1.0)

                            # ------------------------------------------------
                            # Verify that the number really exists
                            # in the current page state.
                            # ------------------------------------------------

                            verified = (
                                verify_number_on_page(
                                    page,
                                    num_val
                                )
                            )

                            if not verified:

                                print(
                                    "⚠️ الرقم لم يتم التحقق منه "
                                    "داخل الصفحة",
                                    flush=True
                                )

                                continue

                            print(
                                "✅ الرقم تم التحقق منه "
                                "داخل جلسة Free Mobile",
                                flush=True
                            )

                            # ------------------------------------------------
                            # Save actual browser state
                            # ------------------------------------------------

                            session_id = (
                                save_session_state(
                                    context,
                                    page,
                                    num_val
                                )
                            )

                            if not session_id:

                                continue

                            # ------------------------------------------------
                            # Keep the server browser context alive.
                            # ------------------------------------------------

                            with ACTIVE_SESSIONS_LOCK:

                                ACTIVE_SESSIONS[
                                    session_id
                                ] = {
                                    "browser": browser,
                                    "context": context,
                                    "page": page,
                                    "number": num_val,
                                    "created": time.time()
                                }

                            browser = None
                            context = None
                            page = None

                            # ------------------------------------------------
                            # Telegram
                            # ------------------------------------------------

                            send_telegram_alert(
                                num_val,
                                vip_desc,
                                session_id
                            )

                            print(
                                "🎯 تم تثبيت الجلسة وإرسال Telegram",
                                flush=True
                            )

                            break

                except Exception as e:

                    print(
                        f"⚠️ LOOP ERROR: {e}",
                        flush=True
                    )

                finally:

                    try:

                        if page and not page.is_closed():
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

                time.sleep(
                    random.uniform(2.5, 4.5)
                )

    except Exception as e:

        print(
            f"❌ FATAL MONITOR ERROR: {e}",
            flush=True
        )


# ============================================================
# CLEAN OLD SESSIONS
# ============================================================

def cleanup_sessions():

    while True:

        try:

            now = time.time()

            for filename in os.listdir(
                SESSION_DIR
            ):

                if not filename.endswith(
                    ".meta.json"
                ):
                    continue

                meta_path = os.path.join(
                    SESSION_DIR,
                    filename
                )

                try:

                    with open(
                        meta_path,
                        "r",
                        encoding="utf-8"
                    ) as f:

                        metadata = json.load(f)

                    created = metadata.get(
                        "created",
                        0
                    )

                    # 30 minutes
                    if now - created > 1800:

                        session_id = metadata.get(
                            "session_id"
                        )

                        with ACTIVE_SESSIONS_LOCK:

                            active = (
                                ACTIVE_SESSIONS.pop(
                                    session_id,
                                    None
                                )
                            )

                        if active:

                            try:
                                active["page"].close()
                            except Exception:
                                pass

                            try:
                                active["context"].close()
                            except Exception:
                                pass

                            try:
                                active["browser"].close()
                            except Exception:
                                pass

                        # Remove files

                        for suffix in [
                            ".meta.json",
                            ".json",
                            ".session.json"
                        ]:

                            path = os.path.join(
                                SESSION_DIR,
                                f"{session_id}{suffix}"
                            )

                            try:

                                if os.path.exists(path):
                                    os.remove(path)

                            except Exception:
                                pass

                        print(
                            f"🧹 Deleted old session "
                            f"{session_id}",
                            flush=True
                        )

                except Exception:
                    continue

        except Exception:
            pass

        time.sleep(300)


# ============================================================
# START MONITOR ONLY ONCE
# ============================================================

monitor_started = False
monitor_lock = threading.Lock()


@app.before_request
def trigger_background_monitor():

    global monitor_started

    with monitor_lock:

        if not monitor_started:

            monitor_started = True

            thread = threading.Thread(
                target=run_smart_proxy_monitor,
                daemon=True
            )

            thread.start()

            cleanup_thread = threading.Thread(
                target=cleanup_sessions,
                daemon=True
            )

            cleanup_thread.start()

            print(
                "[SYSTEM] Monitor started",
                flush=True
            )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            "5000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
