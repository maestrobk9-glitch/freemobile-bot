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


# =========================================================
# SYSTEM
# =========================================================

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    ""
)

CHAT_ID = os.environ.get(
    "CHAT_ID",
    ""
)

TARGET_URL = "https://mobile.free.fr/souscription/options"

SESSION_DIR = "vip_sessions"
os.makedirs(SESSION_DIR, exist_ok=True)


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():
    return """
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>FreeMobile VIP Bot</title>
    </head>
    <body style="font-family:Arial;text-align:center;padding:50px">
        <h2>🚀 FreeMobile VIP Bot يعمل</h2>
        <p>محرك البحث يعمل في الخلفية.</p>
    </body>
    </html>
    """


# =========================================================
# VIP PAGE
# =========================================================

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

    if not os.path.exists(meta_file):
        return """
        <h3 style="font-family:Arial;text-align:center">
        ⚠️ هذه الجلسة غير موجودة.
        </h3>
        """, 404

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
                    font-family:Arial,sans-serif;
                    text-align:center;
                    padding:50px 15px;
                }}

                .card {{
                    max-width:500px;
                    margin:auto;
                    background:#1e293b;
                    padding:35px 20px;
                    border-radius:18px;
                    box-shadow:0 10px 30px rgba(0,0,0,.4);
                }}

                h1 {{
                    font-size:25px;
                }}

                .number {{
                    direction:ltr;
                    color:#facc15;
                    font-size:38px;
                    font-weight:bold;
                    margin:25px 0;
                }}

                .info {{
                    color:#cbd5e1;
                    line-height:1.8;
                }}

                .button {{
                    display:block;
                    margin-top:25px;
                    padding:16px;
                    background:#16a34a;
                    color:white;
                    text-decoration:none;
                    border-radius:12px;
                    font-weight:bold;
                    font-size:18px;
                }}

            </style>

        </head>

        <body>

            <div class="card">

                <h1>
                    🔥 تم العثور على رقم VIP
                </h1>

                <div class="number">
                    {number}
                </div>

                <div class="info">
                    الرقم الذي وجده البوت:
                    <br>
                    <strong>{number}</strong>
                    <br><br>
                    سيتم فتح صفحة Free Mobile.
                </div>

                <a
                    class="button"
                    href="https://mobile.free.fr/souscription/options"
                >
                    فتح Free Mobile
                </a>

            </div>

        </body>

        </html>
        """

        response = make_response(html)

        response.set_cookie(
            "vip_active_session",
            session_id,
            max_age=600,
            httponly=True,
            samesite="Lax"
        )

        return response

    except Exception as e:

        print(
            f"⚠️ VIP PAGE ERROR: {e}",
            flush=True
        )

        return f"""
        <h3 style="font-family:Arial;text-align:center">
        ⚠️ حدث خطأ: {e}
        </h3>
        """, 500


# =========================================================
# VIP NUMBER EVALUATION
# =========================================================

def evaluate_vip_expanded(num):

    clean = (
        str(num)
        .replace(" ", "")
        .replace("-", "")
        .strip()
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

    for seq in sequences:

        if seq in d:
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
# SAVE SESSION
# =========================================================

def save_vip_session(context, number):

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

        print(
            f"💾 [SESSION] تم حفظ جلسة الرقم {safe_number}",
            flush=True
        )

        return session_id

    except Exception as e:

        print(
            f"⚠️ [SESSION] فشل حفظ الجلسة: {e}",
            flush=True
        )

        return None


# =========================================================
# TELEGRAM
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
        f"🔗 [عرض الرقم وفتح Free Mobile]({open_url})"
    )

    if not TELEGRAM_BOT_TOKEN:

        print(
            "⚠️ [TELEGRAM] TELEGRAM_BOT_TOKEN غير موجود",
            flush=True
        )

        return

    if not CHAT_ID:

        print(
            "⚠️ [TELEGRAM] CHAT_ID غير موجود",
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
                "📨 [TELEGRAM] تم إرسال التنبيه",
                flush=True
            )

        else:

            print(
                "⚠️ [TELEGRAM] رفض الرسالة:",
                response.text,
                flush=True
            )

    except Exception as e:

        print(
            f"⚠️ [TELEGRAM] خطأ: {e}",
            flush=True
        )


# =========================================================
# SELECT NUMBER
# =========================================================

def select_number(page, number):

    target = (
        str(number)
        .replace(" ", "")
        .replace("-", "")
        .strip()
    )

    print(
        f"🎯 [SELECT] محاولة اختيار: {target}",
        flush=True
    )

    try:

        # -------------------------------------------------
        # 1. اختيار "Je choisis un nouveau numéro"
        # -------------------------------------------------

        radio_count = page.locator(
            'input[type="radio"]'
        ).count()

        print(
            f"🔘 [SELECT] Radio count: {radio_count}",
            flush=True
        )

        for i in range(radio_count):

            try:

                radio = page.locator(
                    'input[type="radio"]'
                ).nth(i)

                value = (
                    radio.get_attribute("value")
                    or ""
                )

                rid = (
                    radio.get_attribute("id")
                    or ""
                )

                name = (
                    radio.get_attribute("name")
                    or ""
                )

                combined = (
                    value
                    + " "
                    + rid
                    + " "
                    + name
                ).lower()

                if (
                    "new" in combined
                    or
                    "nouveau" in combined
                ):

                    try:

                        radio.check(
                            force=True,
                            timeout=3000
                        )

                    except Exception:

                        radio.click(
                            force=True,
                            timeout=3000
                        )

                    print(
                        "✅ [SELECT] تم اختيار nouveau numéro",
                        flush=True
                    )

                    time.sleep(.5)

            except Exception:
                continue

        # -------------------------------------------------
        # 2. البحث في select
        # -------------------------------------------------

        select_count = page.locator(
            "select"
        ).count()

        print(
            f"🔎 [SELECT] Select count: {select_count}",
            flush=True
        )

        for i in range(select_count):

            try:

                select = page.locator(
                    "select"
                ).nth(i)

                option_count = select.locator(
                    "option"
                ).count()

                for j in range(option_count):

                    try:

                        option = select.locator(
                            "option"
                        ).nth(j)

                        value = (
                            option.get_attribute(
                                "value"
                            )
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
                                "✅ [SELECT] الرقم موجود في القائمة",
                                flush=True
                            )

                            try:

                                select.select_option(
                                    value=value,
                                    timeout=3000
                                )

                            except Exception:

                                select.select_option(
                                    index=j,
                                    timeout=3000
                                )

                            try:
                                select.dispatch_event(
                                    "input"
                                )
                            except Exception:
                                pass

                            try:
                                select.dispatch_event(
                                    "change"
                                )
                            except Exception:
                                pass

                            time.sleep(.5)

                            return True

                    except Exception:
                        continue

            except Exception:
                continue

        # -------------------------------------------------
        # 3. البحث عن الرقم كنص
        # -------------------------------------------------

        try:

            loc = page.get_by_text(
                target,
                exact=False
            )

            count = loc.count()

            print(
                f"🔎 [SELECT] Text matches: {count}",
                flush=True
            )

            for i in range(
                min(count, 10)
            ):

                try:

                    el = loc.nth(i)

                    if el.is_visible():

                        el.click(
                            force=True,
                            timeout=3000
                        )

                        print(
                            "✅ [SELECT] تم الضغط على الرقم",
                            flush=True
                        )

                        time.sleep(.5)

                        return True

                except Exception:
                    continue

        except Exception:
            pass

    except Exception as e:

        print(
            f"⚠️ [SELECT] خطأ: {e}",
            flush=True
        )

    print(
        f"⚠️ [SELECT] لم يتم اختيار {target}",
        flush=True
    )

    return False


# =========================================================
# MONITOR
# =========================================================

def run_smart_proxy_monitor():

    print(
        "🔥🔥🔥 [THREAD ACTIVE] محرك الفحص بدأ",
        flush=True
    )

    os.environ[
        "PLAYWRIGHT_BROWSERS_PATH"
    ] = "/opt/render/project/src/pw-browsers"

    while True:

        try:

            with sync_playwright() as p:

                print(
                    "✅ [PLAYWRIGHT] تم تشغيل Playwright",
                    flush=True
                )

                while True:

                    browser = None
                    context = None
                    page = None

                    try:

                        print(
                            "🔄 [MONITOR] بدء فحص جديد...",
                            flush=True
                        )

                        # ---------------------------------
                        # Browser
                        # ---------------------------------

                        browser = p.chromium.launch(
                            headless=True,
                            args=[
                                "--no-sandbox",
                                "--disable-setuid-sandbox",
                                "--disable-dev-shm-usage"
                            ]
                        )

                        print(
                            "✅ [BROWSER] تم تشغيل Chromium",
                            flush=True
                        )

                        # ---------------------------------
                        # Context
                        # ---------------------------------

                        context = browser.new_context(
                            user_agent=(
                                "Mozilla/5.0 "
                                "(iPhone; CPU iPhone OS 16_0 "
                                "like Mac OS X) "
                                "AppleWebKit/605.1.15 "
                                "(KHTML, like Gecko) "
                                "Version/16.0 Mobile/15E148 "
                                "Safari/604.1"
                            ),
                            viewport={
                                "width": 390,
                                "height": 844
                            },
                            locale="fr-FR"
                        )

                        page = context.new_page()

                        # ---------------------------------
                        # PAGE LOAD
                        # ---------------------------------

                        print(
                            f"🌐 [PAGE] فتح {TARGET_URL}",
                            flush=True
                        )

                        page.goto(
                            TARGET_URL,
                            wait_until="domcontentloaded",
                            timeout=25000
                        )

                        print(
                            f"✅ [PAGE] تم فتح الصفحة: {page.url}",
                            flush=True
                        )

                        time.sleep(1.5)

                        # ---------------------------------
                        # API
                        # ---------------------------------

                        print(
                            "📡 [API] طلب قائمة الأرقام...",
                            flush=True
                        )

                        numbers_data = page.evaluate("""
                            async () => {

                                try {

                                    const res =
                                        await fetch(
                                            './api/msisdns?' +
                                            Date.now(),
                                            {
                                                method: 'GET',

                                                headers: {
                                                    'X-Requested-With':
                                                        'XMLHttpRequest',

                                                    'Cache-Control':
                                                        'no-cache',

                                                    'Pragma':
                                                        'no-cache'
                                                },

                                                cache: 'no-store',
                                                credentials: 'include'
                                            }
                                        );

                                    if (!res.ok) {
                                        return {
                                            __error:
                                                'HTTP ' +
                                                res.status
                                        };
                                    }

                                    return await res.json();

                                } catch (e) {

                                    return {
                                        __error:
                                            String(e)
                                    };
                                }
                            }
                        """)

                        # ---------------------------------
                        # API RESULT
                        # ---------------------------------

                        if not numbers_data:

                            print(
                                "⚠️ [API] لم تصل بيانات",
                                flush=True
                            )

                        elif isinstance(
                            numbers_data,
                            dict
                        ) and numbers_data.get(
                            "__error"
                        ):

                            print(
                                "⚠️ [API] "
                                + str(
                                    numbers_data.get(
                                        "__error"
                                    )
                                ),
                                flush=True
                            )

                        else:

                            if isinstance(
                                numbers_data,
                                list
                            ):

                                numbers_list = (
                                    numbers_data
                                )

                            elif isinstance(
                                numbers_data,
                                dict
                            ):

                                numbers_list = (
                                    numbers_data.get(
                                        "msisdns",
                                        []
                                    )
                                )

                            else:

                                numbers_list = []

                            print(
                                "📱 [API] عدد الأرقام: "
                                + str(
                                    len(numbers_list)
                                ),
                                flush=True
                            )

                            found = False

                            # ---------------------------------
                            # CHECK NUMBERS
                            # ---------------------------------

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

                                found = True

                                print(
                                    "🔥🔥🔥 VIP FOUND!",
                                    flush=True
                                )

                                print(
                                    f"📱 الرقم: {num_val}",
                                    flush=True
                                )

                                print(
                                    f"💎 التصنيف: {vip_desc}",
                                    flush=True
                                )

                                # ---------------------------------
                                # SELECT
                                # ---------------------------------

                                selected = (
                                    select_number(
                                        page,
                                        num_val
                                    )
                                )

                                print(
                                    "🎯 [SELECT] النتيجة: "
                                    + str(selected),
                                    flush=True
                                )

                                # ---------------------------------
                                # SAVE
                                # ---------------------------------

                                session_id = (
                                    save_vip_session(
                                        context,
                                        num_val
                                    )
                                )

                                if session_id:

                                    print(
                                        "💾 [SESSION] ID: "
                                        + session_id,
                                        flush=True
                                    )

                                    send_telegram_alert(
                                        num_val,
                                        vip_desc,
                                        session_id
                                    )

                                else:

                                    print(
                                        "⚠️ [SESSION] لم يتم حفظ الجلسة",
                                        flush=True
                                    )

                                break

                            if not found:

                                print(
                                    "🔍 [MONITOR] لا يوجد رقم VIP هذه المرة",
                                    flush=True
                                )

                    except PlaywrightTimeoutError as e:

                        print(
                            "⏱️ [TIMEOUT] انتهت مهلة Playwright: "
                            + str(e),
                            flush=True
                        )

                    except Exception as e:

                        print(
                            "⚠️ [LOOP ERROR] "
                            + repr(e),
                            flush=True
                        )

                    finally:

                        # ---------------------------------
                        # CLOSE BROWSER
                        # ---------------------------------

                        if browser:

                            try:

                                browser.close()

                                print(
                                    "🔒 [BROWSER] تم إغلاق المتصفح",
                                    flush=True
                                )

                            except Exception as e:

                                print(
                                    "⚠️ [BROWSER] فشل الإغلاق: "
                                    + str(e),
                                    flush=True
                                )

                    # ---------------------------------
                    # NEXT LOOP
                    # ---------------------------------

                    delay = random.uniform(
                        2.5,
                        4.5
                    )

                    print(
                        f"⏳ [MONITOR] الفحص القادم بعد {delay:.1f}s",
                        flush=True
                    )

                    time.sleep(delay)

        except Exception as e:

            print(
                "❌ [PLAYWRIGHT RESTART ERROR] "
                + repr(e),
                flush=True
            )

            print(
                "🔁 إعادة تشغيل Playwright بعد 5 ثوانٍ...",
                flush=True
            )

            time.sleep(5)


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    print(
        "========================================",
        flush=True
    )

    print(
        "🚀 FreeMobile VIP Bot Starting...",
        flush=True
    )

    print(
        "========================================",
        flush=True
    )

    monitor_thread = threading.Thread(
        target=run_smart_proxy_monitor,
        daemon=True
    )

    monitor_thread.start()

    print(
        "✅ [SYSTEM] Background monitor started",
        flush=True
    )

    port = int(
        os.environ.get(
            "PORT",
            "5000"
        )
    )

    print(
        f"🌐 [FLASK] Starting on port {port}",
        flush=True
    )

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )
