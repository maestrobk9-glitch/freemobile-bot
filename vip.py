import os
import json
import time
import uuid
import re
import requests
import threading
from flask import Flask, render_template_string
from playwright.sync_api import sync_playwright

app = Flask(__name__)

# =========================================================
# CONFIG
# =========================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

TARGET_URL = "https://mobile.free.fr/souscription/init/choice"

SESSION_DIR = os.path.join(os.getcwd(), "vip_sessions")
os.makedirs(SESSION_DIR, exist_ok=True)

SCAN_DELAY = 3.0

# لمنع إرسال نفس الرقم مرات كثيرة
SEEN_FILE = os.path.join(SESSION_DIR, "seen_numbers.json")


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():
    return """
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Free Mobile VIP Monitor</title>
        <style>
            body {
                background:#0f172a;
                color:white;
                font-family:Arial,sans-serif;
                text-align:center;
                padding-top:60px;
            }
            .box {
                display:inline-block;
                background:#1e293b;
                padding:35px;
                border-radius:15px;
            }
            .ok {
                color:#22c55e;
            }
        </style>
    </head>
    <body>
        <div class="box">
            <h1>🚀 Free Mobile VIP Monitor</h1>
            <p class="ok">● Monitor actif</p>
            <p>Le moteur de surveillance fonctionne en arrière-plan.</p>
        </div>
    </body>
    </html>
    """


# =========================================================
# VIP PAGE
# =========================================================

@app.route("/vip/<session_id>")
def view_vip_session(session_id):

    meta_file = os.path.join(
        SESSION_DIR,
        f"{session_id}.meta.json"
    )

    if not os.path.exists(meta_file):
        return """
        <h3 style="text-align:center;margin-top:50px;">
        ⚠️ هذه الجلسة غير موجودة أو انتهت.
        </h3>
        """, 404

    try:

        with open(meta_file, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        number = metadata.get("number", "غير معروف")

        return render_template_string("""
        <!DOCTYPE html>
        <html lang="ar" dir="rtl">
        <head>
            <meta charset="UTF-8">
            <title>VIP Free Mobile</title>

            <style>
                body {
                    font-family: Arial, sans-serif;
                    background:#0f172a;
                    color:white;
                    text-align:center;
                    padding-top:60px;
                }

                .card {
                    background:#1e293b;
                    padding:35px;
                    border-radius:18px;
                    display:inline-block;
                    min-width:320px;
                    box-shadow:0 10px 30px rgba(0,0,0,.4);
                }

                h1 {
                    color:#38bdf8;
                }

                .number {
                    color:#facc15;
                    font-size:36px;
                    font-weight:bold;
                    margin:25px 0;
                }

                .btn {
                    display:inline-block;
                    margin-top:20px;
                    padding:13px 25px;
                    background:#10b981;
                    color:white;
                    text-decoration:none;
                    border-radius:9px;
                    font-weight:bold;
                }
            </style>
        </head>

        <body>

            <div class="card">

                <h1>🔥 VIP NUMBER</h1>

                <p>رقم الهاتف الذي تم العثور عليه:</p>

                <div class="number">
                    {{ number }}
                </div>

                <p>
                    تم حفظ جلسة المتصفح.
                </p>

                <a
                    class="btn"
                    href="https://mobile.free.fr/souscription/init/choice"
                    target="_blank"
                >
                    فتح Free Mobile
                </a>

            </div>

        </body>
        </html>
        """, number=number)

    except Exception as e:

        print(
            f"[ERROR] Reading session: {repr(e)}",
            flush=True
        )

        return "Internal error", 500


# =========================================================
# VIP EVALUATION
# =========================================================

def evaluate_vip(num):

    clean = re.sub(r"\D", "", str(num))

    if len(clean) != 10:
        return None

    if not (
        clean.startswith("06")
        or clean.startswith("07")
    ):
        return None

    d = clean[2:]

    # كل الأرقام تقريباً متشابهة
    if len(set(d)) <= 4:
        return "تنوع منخفض للأرقام"

    # مثال 0612344321
    if d == d[::-1]:
        return "Palindrome"

    # مثال 0612341234
    if d[:4] == d[4:]:
        return "نصفان متطابقان"

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
        "3210"
    ]

    for seq in sequences:
        if seq in d:
            return "تسلسل أرقام"

    # تكرار قوي في آخر 4 أرقام
    if len(set(d[-4:])) <= 2:
        return "تكرار قوي في النهاية"

    # تكرار قوي في أول 4 أرقام
    if len(set(d[:4])) <= 2:
        return "تكرار قوي في البداية"

    # ثلاثية
    if (
        d[0] == d[1] == d[2]
        or
        d[-3] == d[-2] == d[-1]
    ):
        return "ثلاثية متتالية"

    return None


# =========================================================
# SEEN NUMBERS
# =========================================================

seen_lock = threading.Lock()


def load_seen():

    try:

        if not os.path.exists(SEEN_FILE):
            return set()

        with open(
            SEEN_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(data, list):
            return set(data)

    except Exception as e:

        print(
            f"[WARN] Cannot load seen numbers: {repr(e)}",
            flush=True
        )

    return set()


def save_seen(seen):

    try:

        # نحافظ على آخر 5000 رقم فقط
        data = list(seen)[-5000:]

        with open(
            SEEN_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False
            )

    except Exception as e:

        print(
            f"[WARN] Cannot save seen numbers: {repr(e)}",
            flush=True
        )


SEEN_NUMBERS = load_seen()


# =========================================================
# NUMBER EXTRACTION
# =========================================================

def extract_numbers(value):

    """
    يبحث بشكل recursive داخل JSON
    عن أرقام فرنسية 06xxxxxxxx أو 07xxxxxxxx.
    """

    found = set()

    if value is None:
        return found

    if isinstance(value, dict):

        for k, v in value.items():

            # نعطي أولوية للحقول التي غالباً تحمل الرقم
            key = str(k).lower()

            if any(
                word in key
                for word in [
                    "msisdn",
                    "number",
                    "phone",
                    "mobile",
                    "telephone",
                    "tel"
                ]
            ):

                found.update(
                    extract_numbers(v)
                )

            else:

                found.update(
                    extract_numbers(v)
                )

        return found

    if isinstance(value, list):

        for item in value:

            found.update(
                extract_numbers(item)
            )

        return found

    if isinstance(value, (int, float)):

        value = str(value)

    if isinstance(value, str):

        text = value

        # إزالة المسافات والنقاط والشرطات بين أرقام الهاتف
        normalized = re.sub(
            r"(?<=\d)[ .-](?=\d)",
            "",
            text
        )

        matches = re.findall(
            r"(?<!\d)(?:06|07)\d{8}(?!\d)",
            normalized
        )

        for number in matches:

            if len(number) == 10:
                found.add(number)

    return found


# =========================================================
# SAVE SESSION
# =========================================================

def save_vip_session(context, number):

    session_id = uuid.uuid4().hex

    safe_number = re.sub(
        r"\D",
        "",
        str(number)
    )

    state_file = os.path.join(
        SESSION_DIR,
        f"{session_id}.json"
    )

    meta_file = os.path.join(
        SESSION_DIR,
        f"{session_id}.meta.json"
    )

    try:

        context.storage_state(
            path=state_file
        )

        metadata = {
            "session_id": session_id,
            "number": safe_number,
            "created": int(time.time()),
            "state_file": state_file
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
            f"[SESSION] Saved: {safe_number}",
            flush=True
        )

        return session_id

    except Exception as e:

        print(
            f"[ERROR] Session save failed: {repr(e)}",
            flush=True
        )

        return None


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram_alert(
    number,
    description,
    session_id
):

    if not TELEGRAM_BOT_TOKEN:
        print(
            "[ERROR] TELEGRAM_BOT_TOKEN is missing",
            flush=True
        )
        return False

    if not CHAT_ID:
        print(
            "[ERROR] CHAT_ID is missing",
            flush=True
        )
        return False

    render_url = os.environ.get(
        "RENDER_EXTERNAL_URL",
        "https://freemobile-bot.onrender.com"
    ).rstrip("/")

    open_url = (
        f"{render_url}/vip/{session_id}"
    )

    message = (
        "🔥 *رقم مميز VIP جديد!*\n\n"
        f"📱 الرقم: `{number}`\n"
        f"💎 التصنيف: {description}\n\n"
        f"🔗 [فتح الجلسة]({open_url})"
    )

    telegram_url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }

    try:

        response = requests.post(
            telegram_url,
            json=payload,
            timeout=15
        )

        if response.ok:

            print(
                f"[TELEGRAM] Alert sent: {number}",
                flush=True
            )

            return True

        print(
            "[TELEGRAM ERROR]",
            response.status_code,
            response.text,
            flush=True
        )

        return False

    except Exception as e:

        print(
            f"[TELEGRAM ERROR] {repr(e)}",
            flush=True
        )

        return False


# =========================================================
# PROCESS NUMBER
# =========================================================

def process_number(
    context,
    number
):

    global SEEN_NUMBERS

    clean = re.sub(
        r"\D",
        "",
        str(number)
    )

    if len(clean) != 10:
        return

    if not (
        clean.startswith("06")
        or clean.startswith("07")
    ):
        return

    with seen_lock:

        if clean in SEEN_NUMBERS:
            return

    description = evaluate_vip(clean)

    if not description:
        return

    print(
        "",
        flush=True
    )

    print(
        "🔥🔥🔥 VIP FOUND 🔥🔥🔥",
        flush=True
    )

    print(
        f"📱 NUMBER: {clean}",
        flush=True
    )

    print(
        f"💎 TYPE: {description}",
        flush=True
    )

    session_id = save_vip_session(
        context,
        clean
    )

    if not session_id:
        print(
            "[ERROR] Could not create session",
            flush=True
        )
        return

    sent = send_telegram_alert(
        clean,
        description,
        session_id
    )

    if sent:

        with seen_lock:

            SEEN_NUMBERS.add(clean)
            save_seen(SEEN_NUMBERS)


# =========================================================
# JSON RESPONSE HANDLER
# =========================================================

def inspect_response(
    response,
    context
):

    try:

        content_type = (
            response.headers.get(
                "content-type",
                ""
            ).lower()
        )

        url = response.url

        # نهتم خصوصاً بالـ JSON
        if (
            "json" not in content_type
            and
            "application/javascript" not in content_type
        ):
            return

        # لا نريد ملفات ضخمة
        if response.body and len(response.body()) > 5_000_000:
            return

        try:

            data = response.json()

        except Exception:

            return

        numbers = extract_numbers(data)

        if numbers:

            print(
                f"[NETWORK] {len(numbers)} phone(s) "
                f"from {url[:180]}",
                flush=True
            )

            for number in numbers:

                process_number(
                    context,
                    number
                )

    except Exception as e:

        print(
            f"[NETWORK ERROR] {repr(e)}",
            flush=True
        )


# =========================================================
# MONITOR
# =========================================================

def monitor_once(playwright):

    browser = None
    context = None

    try:

        print(
            "[MONITOR] Starting Chromium...",
            flush=True
        )

        browser = playwright.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 "
                "(iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 "
                "(KHTML, like Gecko) "
                "Version/17.0 Mobile/15E148 Safari/604.1"
            ),
            viewport={
                "width": 390,
                "height": 844
            },
            locale="fr-FR",
            timezone_id="Europe/Paris"
        )

        page = context.new_page()

        # كل استجابة تمر هنا
        def on_response(response):

            inspect_response(
                response,
                context
            )

        page.on(
            "response",
            on_response
        )

        print(
            f"[MONITOR] Opening {TARGET_URL}",
            flush=True
        )

        response = page.goto(
            TARGET_URL,
            wait_until="domcontentloaded",
            timeout=30000
        )

        if response:

            print(
                f"[MONITOR] HTTP STATUS: "
                f"{response.status}",
                flush=True
            )

        print(
            f"[MONITOR] URL: {page.url}",
            flush=True
        )

        print(
            f"[MONITOR] TITLE: {page.title()}",
            flush=True
        )

        # إعطاء JavaScript فرصة لإنهاء الطلبات
        page.wait_for_timeout(5000)

        # نراقب الصفحة فترة قصيرة
        # بدون الضغط على أي شيء
        end_time = time.time() + 20

        while time.time() < end_time:

            try:

                page.wait_for_timeout(1000)

            except Exception as e:

                print(
                    f"[PAGE ERROR] {repr(e)}",
                    flush=True
                )

                break

        print(
            "[MONITOR] Scan finished.",
            flush=True
        )

    except Exception as e:

        print(
            "",
            flush=True
        )

        print(
            "========== MONITOR ERROR ==========",
            flush=True
        )

        print(
            repr(e),
            flush=True
        )

        print(
            "====================================",
            flush=True
        )

    finally:

        try:

            if context:
                context.close()

        except Exception as e:

            print(
                f"[CLOSE CONTEXT ERROR] {repr(e)}",
                flush=True
            )

        try:

            if browser:
                browser.close()

        except Exception as e:

            print(
                f"[CLOSE BROWSER ERROR] {repr(e)}",
                flush=True
            )


# =========================================================
# BACKGROUND LOOP
# =========================================================

monitor_started = False
monitor_lock = threading.Lock()


def run_monitor():

    print(
        "🚀 Free Mobile VIP Monitor started",
        flush=True
    )

    with sync_playwright() as playwright:

        while True:

            started = time.time()

            try:

                monitor_once(playwright)

            except Exception as e:

                print(
                    f"[FATAL MONITOR ERROR] {repr(e)}",
                    flush=True
                )

            elapsed = time.time() - started

            wait_time = max(
                1,
                SCAN_DELAY - elapsed
            )

            print(
                f"[MONITOR] Next scan in "
                f"{wait_time:.1f}s",
                flush=True
            )

            time.sleep(wait_time)


def start_background_monitor():

    global monitor_started

    with monitor_lock:

        if monitor_started:
            return

        monitor_started = True

        thread = threading.Thread(
            target=run_monitor,
            name="FreeMobileVIPMonitor",
            daemon=True
        )

        thread.start()

        print(
            "[SYSTEM] Background monitor thread started",
            flush=True
        )


# =========================================================
# START
# =========================================================

start_background_monitor()


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
