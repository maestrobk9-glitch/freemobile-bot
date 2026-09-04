import os
import json
import time
import random
import uuid
import requests
import threading
import sys

from flask import Flask, jsonify, request, redirect, make_response
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(line_buffering=True)

app = Flask(__name__)

# ضع القيم في Environment Variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

TARGET_URL = "https://mobile.free.fr/souscription/options"

SESSION_DIR = "vip_sessions"
os.makedirs(SESSION_DIR, exist_ok=True)

# الجلسات النشطة على السيرفر
ACTIVE_SESSIONS = {}
ACTIVE_LOCK = threading.Lock()


# =========================================================
# الصفحة الرئيسية
# =========================================================

@app.route("/")
def home():
    return """
    <h2>🚀 FreeMobile VIP Bot يعمل</h2>
    <p>المراقبة تعمل في الخلفية.</p>
    """


# =========================================================
# صفحة VIP
# =========================================================

@app.route("/vip/<session_id>")
def view_vip_session(session_id):

    with ACTIVE_LOCK:
        session = ACTIVE_SESSIONS.get(session_id)

    meta_file = os.path.join(
        SESSION_DIR,
        f"{session_id}.meta.json"
    )

    if not session and not os.path.exists(meta_file):
        return """
        <h3>
        ⚠️ هذه الجلسة غير موجودة أو انتهت.
        </h3>
        """, 404

    number = "غير معروف"

    try:
        if os.path.exists(meta_file):
            with open(meta_file, "r", encoding="utf-8") as f:
                metadata = json.load(f)

            number = metadata.get("number", number)

    except Exception:
        pass

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

            * {{
                box-sizing: border-box;
            }}

            body {{
                margin: 0;
                background: #0f172a;
                color: white;
                font-family: Arial, sans-serif;
                text-align: center;
                padding: 30px 15px;
            }}

            .card {{
                max-width: 500px;
                margin: auto;
                background: #1e293b;
                padding: 30px 20px;
                border-radius: 18px;
                box-shadow:
                    0 15px 40px rgba(0,0,0,.35);
            }}

            h1 {{
                font-size: 25px;
                margin-bottom: 20px;
            }}

            .number {{
                font-size: 36px;
                font-weight: bold;
                color: #facc15;
                margin: 25px 0;
                direction: ltr;
            }}

            .status {{
                margin: 20px 0;
                color: #94a3b8;
                line-height: 1.6;
            }}

            button {{
                border: 0;
                width: 100%;
                padding: 16px;
                border-radius: 12px;
                background: #16a34a;
                color: white;
                font-size: 18px;
                font-weight: bold;
                cursor: pointer;
            }}

            button:active {{
                transform: scale(.98);
            }}

            .small {{
                margin-top: 18px;
                color: #94a3b8;
                font-size: 13px;
            }}

        </style>
    </head>

    <body>

        <div class="card">

            <h1>🔥 رقم VIP تم العثور عليه</h1>

            <div class="number">
                {number}
            </div>

            <div class="status">
                الرقم تم العثور عليه داخل جلسة البوت.
                <br>
                يجب استخدام جلسة البوت نفسها لإتمام العملية.
            </div>

            <button onclick="openFree()">
                فتح Free Mobile
            </button>

            <div class="small">
                Session: {session_id}
            </div>

        </div>

        <script>

            function openFree() {{

                window.location.href =
                    "/vip/{session_id}/free";

            }}

        </script>

    </body>
    </html>
    """

    response = make_response(html)

    response.set_cookie(
        "vip_active_session",
        session_id,
        max_age=900,
        httponly=True,
        samesite="Lax"
    )

    return response


# =========================================================
# فتح الجلسة النشطة
# =========================================================

@app.route("/vip/<session_id>/free")
def open_free_session(session_id):

    with ACTIVE_LOCK:
        session = ACTIVE_SESSIONS.get(session_id)

    if not session:
        return """
        <h3>
        ⚠️ انتهت جلسة المتصفح.
        أعد انتظار رقم VIP جديد.
        </h3>
        """, 410

    try:

        page = session["page"]
        number = session["number"]

        # التأكد أن الصفحة ما زالت موجودة
        if page.is_closed():
            return """
            <h3>⚠️ جلسة المتصفح مغلقة.</h3>
            """, 410

        # إعادة فتح صفحة الاشتراك داخل نفس جلسة Playwright
        page.goto(
            TARGET_URL,
            wait_until="domcontentloaded",
            timeout=30000
        )

        time.sleep(1.5)

        # محاولة إعادة اختيار الرقم داخل نفس الجلسة
        select_number(page, number)

        # لا نغلق المتصفح هنا
        return redirect(TARGET_URL)

    except Exception as e:

        print(
            f"⚠️ فتح جلسة VIP فشل: {e}",
            flush=True
        )

        return """
        <h3>
        ⚠️ حدث خطأ أثناء فتح جلسة Free Mobile.
        </h3>
        """, 500


# =========================================================
# تحليل الرقم
# =========================================================

def evaluate_vip_expanded(num):

    clean = str(num).replace(" ", "").replace("-", "")

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
        return "تنوع منخفض للأرقام (مميز)"

    if d == d[::-1]:
        return "مرآة متناظرة كاملة (Palindrome)"

    if d[:4] == d[4:]:
        return "نصفين متطابقين تماماً"

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

    if any(seq in d for seq in sequences):
        return "تسلسل أرقام متتالي"

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


# =========================================================
# اختيار الرقم داخل Free
# =========================================================

def select_number(page, number):

    target = (
        str(number)
        .replace(" ", "")
        .replace("-", "")
    )

    print(
        f"🎯 محاولة اختيار الرقم: {target}",
        flush=True
    )

    try:

        # ---------------------------------------------
        # اختيار "nouveau numéro"
        # ---------------------------------------------

        radios = page.locator(
            'input[type="radio"]'
        )

        count = radios.count()

        for i in range(count):

            try:

                radio = radios.nth(i)

                value = (
                    radio.get_attribute("value")
                    or ""
                ).lower()

                rid = (
                    radio.get_attribute("id")
                    or ""
                ).lower()

                name = (
                    radio.get_attribute("name")
                    or ""
                ).lower()

                label_text = ""

                try:
                    label_text = radio.evaluate("""
                        el => {
                            const l =
                                document.querySelector(
                                    `label[for="${el.id}"]`
                                );
                            return l ? l.innerText : "";
                        }
                    """) or ""
                except Exception:
                    pass

                text = (
                    value
                    + " "
                    + rid
                    + " "
                    + name
                    + " "
                    + label_text.lower()
                )

                if (
                    "new" in text
                    or
                    "nouveau" in text
                ):

                    try:
                        radio.check(
                            force=True
                        )
                    except Exception:
                        radio.click(
                            force=True
                        )

                    time.sleep(.3)

            except Exception:
                continue

        # ---------------------------------------------
        # البحث عن select الذي يحتوي الرقم
        # ---------------------------------------------

        selects = page.locator("select")

        select_count = selects.count()

        print(
            f"🔎 عدد قوائم select: {select_count}",
            flush=True
        )

        for i in range(select_count):

            try:

                sel = selects.nth(i)

                options = sel.locator("option")

                option_count = options.count()

                for j in range(option_count):

                    try:

                        option = options.nth(j)

                        value = (
                            option.get_attribute("value")
                            or ""
                        )

                        text = (
                            option.inner_text()
                            or ""
                        )

                        clean_value = (
                            value
                            .replace(" ", "")
                            .replace("-", "")
                        )

                        clean_text = (
                            text
                            .replace(" ", "")
                            .replace("-", "")
                        )

                        if (
                            target in clean_value
                            or
                            target in clean_text
                        ):

                            print(
                                "✅ تم العثور على الرقم داخل select",
                                flush=True
                            )

                            try:

                                sel.select_option(
                                    value=value
                                )

                            except Exception:

                                try:
                                    sel.select_option(
                                        index=j
                                    )
                                except Exception:
                                    pass

                            time.sleep(.5)

                            # إطلاق الأحداث التي تحتاجها
                            try:

                                sel.dispatch_event(
                                    "input"
                                )

                                sel.dispatch_event(
                                    "change"
                                )

                            except Exception:
                                pass

                            return True

                    except Exception:
                        continue

            except Exception:
                continue

        # ---------------------------------------------
        # محاولة العناصر التي تحتوي الرقم مباشرة
        # ---------------------------------------------

        try:

            locator = page.get_by_text(
                target,
                exact=False
            )

            if locator.count() > 0:

                for i in range(
                    min(locator.count(), 10)
                ):

                    try:

                        element = locator.nth(i)

                        if element.is_visible():

                            element.click(
                                force=True
                            )

                            time.sleep(.4)

                            print(
                                "✅ تم الضغط على الرقم",
                                flush=True
                            )

                            return True

                    except Exception:
                        continue

        except Exception:
            pass

    except Exception as e:

        print(
            f"⚠️ select_number error: {e}",
            flush=True
        )

    print(
        "⚠️ لم يتم العثور على عنصر اختيار الرقم",
        flush=True
    )

    return False


# =========================================================
# حفظ الجلسة
# =========================================================

def save_vip_session(
    context,
    page,
    number
):

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

    try:

        context.storage_state(
            path=state_file,
            indexed_db=True
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

        # الاحتفاظ بالمتصفح والجلسة مفتوحين
        with ACTIVE_LOCK:

            ACTIVE_SESSIONS[session_id] = {
                "context": context,
                "page": page,
                "number": safe_number,
                "created": time.time()
            }

        print(
            f"💾 جلسة VIP محفوظة: {safe_number}",
            flush=True
        )

        return session_id

    except Exception as e:

        print(
            f"⚠️ فشل حفظ الجلسة: {e}",
            flush=True
        )

        return None


# =========================================================
# Telegram
# =========================================================

def send_telegram_alert(
    number,
    desc,
    session_id
):

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
        f"💎 التصنيف: {desc}\n\n"
        f"🔗 [فتح جلسة VIP]({open_url})"
    )

    if not TELEGRAM_BOT_TOKEN:
        print(
            "⚠️ TELEGRAM_BOT_TOKEN غير موجود",
            flush=True
        )
        return

    if not CHAT_ID:
        print(
            "⚠️ CHAT_ID غير موجود",
            flush=True
        )
        return

    telegram_url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
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
            timeout=10
        )

        if response.ok:

            print(
                "📨 تم إرسال Telegram",
                flush=True
            )

        else:

            print(
                "⚠️ Telegram error:",
                response.text,
                flush=True
            )

    except Exception as e:

        print(
            f"⚠️ Telegram exception: {e}",
            flush=True
        )


# =========================================================
# تنظيف الجلسات القديمة
# =========================================================

def cleanup_sessions():

    while True:

        time.sleep(300)

        now = time.time()

        expired = []

        with ACTIVE_LOCK:

            for sid, data in ACTIVE_SESSIONS.items():

                if now - data["created"] > 1800:

                    expired.append(sid)

            for sid in expired:

                data = ACTIVE_SESSIONS.pop(
                    sid,
                    None
                )

                if data:

                    try:
                        data["context"].close()
                    except Exception:
                        pass

                print(
                    f"🧹 تم تنظيف الجلسة: {sid}",
                    flush=True
                )


# =========================================================
# محرك البحث
# =========================================================

def run_smart_proxy_monitor():

    print(
        "🔥 THREAD ACTIVE",
        flush=True
    )

    os.environ[
        "PLAYWRIGHT_BROWSERS_PATH"
    ] = "/opt/render/project/src/pw-browsers"

    while True:

        try:

            with sync_playwright() as p:

                print(
                    "✅ PLAYWRIGHT بدأ",
                    flush=True
                )

                while True:

                    browser = None
                    context = None
                    page = None

                    try:

                        browser = p.chromium.launch(
                            headless=True,
                            args=[
                                "--no-sandbox",
                                "--disable-setuid-sandbox",
                                "--disable-dev-shm-usage"
                            ]
                        )

                        context = browser.new_context(
                            user_agent=(
                                "Mozilla/5.0 "
                                "(iPhone; CPU iPhone OS 16_0 "
                                "like Mac OS X) "
                                "AppleWebKit/605.1.15 "
                                "(KHTML, like Gecko) "
                                "Version/16.0 Mobile/15E148 "
                                "Safari/604.1"
                            )
                        )

                        page = context.new_page()

                        page.goto(
                            TARGET_URL,
                            wait_until="domcontentloaded",
                            timeout=25000
                        )

                        time.sleep(1.5)

                        numbers_data = page.evaluate("""
                            async () => {
                                try {
                                    const res =
                                        await fetch(
                                            './api/msisdns?' +
                                            Math.random(),
                                            {
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

                                } catch (e) {}

                                return null;
                            }
                        """)

                        if numbers_data:

                            if isinstance(
                                numbers_data,
                                list
                            ):
                                numbers_list = (
                                    numbers_data
                                )
                            else:
                                numbers_list = (
                                    numbers_data.get(
                                        "msisdns",
                                        []
                                    )
                                )

                            if numbers_list:

                                for item in numbers_list:

                                    if isinstance(
                                        item,
                                        dict
                                    ):
                                        num_val = item.get(
                                            "value"
                                        )
                                    else:
                                        num_val = str(
                                            item
                                        )

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
                                        "🔥 VIP FOUND: "
                                        f"{num_val} | "
                                        f"{vip_desc}",
                                        flush=True
                                    )

                                    # اختيار الرقم
                                    selected = (
                                        select_number(
                                            page,
                                            num_val
                                        )
                                    )

                                    print(
                                        "🎯 نتيجة الاختيار: "
                                        f"{selected}",
                                        flush=True
                                    )

                                    # حفظ الجلسة
                                    session_id = (
                                        save_vip_session(
                                            context,
                                            page,
                                            num_val
                                        )
                                    )

                                    if session_id:

                                        send_telegram_alert(
                                            num_val,
                                            vip_desc,
                                            session_id
                                        )

                                        # مهم:
                                        # لا تغلق browser/context
                                        # لأن الجلسة أصبحت VIP نشطة
                                        browser = None
                                        context = None
                                        page = None

                                    break

                        # إذا لم تصبح الجلسة VIP
                        if browser:

                            try:
                                browser.close()
                            except Exception:
                                pass

                    except Exception as e:

                        print(
                            f"⚠️ LOOP ERROR: {e}",
                            flush=True
                        )

                        try:

                            if browser:
                                browser.close()

                        except Exception:
                            pass

                    time.sleep(
                        random.uniform(
                            2.5,
                            4.5
                        )
                    )

        except Exception as e:

            print(
                "❌ PLAYWRIGHT RESTART ERROR: "
                f"{e}",
                flush=True
            )

            time.sleep(5)


# =========================================================
# التشغيل
# =========================================================

if __name__ == "__main__":

    cleanup_thread = threading.Thread(
        target=cleanup_sessions,
        daemon=True
    )

    cleanup_thread.start()

    monitor_thread = threading.Thread(
        target=run_smart_proxy_monitor,
        daemon=True
    )

    monitor_thread.start()

    print(
        "[SYSTEM] Background monitor started",
        flush=True
    )

    port = int(
        os.environ.get(
            "PORT",
            "5000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )
