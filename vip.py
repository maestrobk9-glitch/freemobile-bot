import os
import json
import time
import random
import uuid
import secrets
import requests
import threading
import sys
import io
import html
import queue

from flask import Flask, make_response, request, Response, jsonify
from playwright.sync_api import sync_playwright

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass


# ============================================================
# CONFIG
# ============================================================

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

TARGET_URL = "https://mobile.free.fr/souscription/options"

SESSION_DIR = "vip_sessions"
os.makedirs(SESSION_DIR, exist_ok=True)

# مدة بقاء Remote Browser مفتوحاً
REMOTE_SESSION_TIMEOUT = 20 * 60

# الفاصل بين فحوصات الأرقام
MIN_DELAY = 2.5
MAX_DELAY = 4.5

# ============================================================
# REMOTE SESSION STORAGE
# ============================================================

LIVE_SESSIONS = {}

LIVE_SESSIONS_LOCK = threading.Lock()


def create_live_session(number):
    session_id = uuid.uuid4().hex
    token = secrets.token_urlsafe(32)

    session_data = {
        "session_id": session_id,
        "token": token,
        "number": str(number),
        "created": time.time(),
        "queue": queue.Queue(),
        "closed": False,
    }

    with LIVE_SESSIONS_LOCK:
        LIVE_SESSIONS[session_id] = session_data

    return session_data


def get_live_session(session_id):
    with LIVE_SESSIONS_LOCK:
        return LIVE_SESSIONS.get(session_id)


def remove_live_session(session_id):
    with LIVE_SESSIONS_LOCK:
        LIVE_SESSIONS.pop(session_id, None)


def check_token(session_id):
    session = get_live_session(session_id)

    if not session:
        return None

    supplied = request.args.get("token")

    if not supplied and request.is_json:
        data = request.get_json(silent=True) or {}
        supplied = data.get("token")

    if not supplied:
        supplied = request.form.get("token")

    if not supplied:
        return None

    if not secrets.compare_digest(str(supplied), str(session["token"])):
        return None

    return session


# ============================================================
# REMOTE COMMAND SYSTEM
# ============================================================

def send_remote_command(session_id, token, command, payload=None, timeout=10):
    session = get_live_session(session_id)

    if not session:
        return {
            "ok": False,
            "error": "SESSION_NOT_FOUND"
        }

    if not secrets.compare_digest(str(token), str(session["token"])):
        return {
            "ok": False,
            "error": "INVALID_TOKEN"
        }

    event = threading.Event()

    command_data = {
        "command": command,
        "payload": payload or {},
        "event": event,
        "result": None,
    }

    session["queue"].put(command_data)

    if not event.wait(timeout):
        return {
            "ok": False,
            "error": "COMMAND_TIMEOUT"
        }

    return command_data.get(
        "result",
        {
            "ok": False,
            "error": "NO_RESULT"
        }
    )


def process_remote_commands(page, session):
    """
    مهم جداً:
    Playwright يبقى في نفس thread الذي أنشأه.
    Flask لا يتعامل مباشرة مع page.
    Flask يضع الأوامر في Queue.
    هذا الجزء ينفذها داخل Thread الخاص بـ Playwright.
    """

    processed = 0

    while processed < 10:

        try:
            cmd = session["queue"].get_nowait()
        except queue.Empty:
            break

        processed += 1

        command = cmd["command"]
        payload = cmd.get("payload", {})

        try:

            # ------------------------------------------------
            # SCREEN
            # ------------------------------------------------

            if command == "screen":

                image_bytes = page.screenshot(
                    type="jpeg",
                    quality=70
                )

                cmd["result"] = {
                    "ok": True,
                    "image": image_bytes
                }

            # ------------------------------------------------
            # CLICK
            # ------------------------------------------------

            elif command == "click":

                x = float(payload.get("x", 0))
                y = float(payload.get("y", 0))

                display_width = float(
                    payload.get("display_width", 390)
                )

                display_height = float(
                    payload.get("display_height", 844)
                )

                viewport = page.viewport_size

                if not viewport:
                    viewport = {
                        "width": 390,
                        "height": 844
                    }

                real_x = x * viewport["width"] / display_width
                real_y = y * viewport["height"] / display_height

                page.mouse.click(
                    real_x,
                    real_y
                )

                cmd["result"] = {
                    "ok": True
                }

            # ------------------------------------------------
            # DOUBLE CLICK
            # ------------------------------------------------

            elif command == "dblclick":

                x = float(payload.get("x", 0))
                y = float(payload.get("y", 0))

                display_width = float(
                    payload.get("display_width", 390)
                )

                display_height = float(
                    payload.get("display_height", 844)
                )

                viewport = page.viewport_size or {
                    "width": 390,
                    "height": 844
                }

                real_x = x * viewport["width"] / display_width
                real_y = y * viewport["height"] / display_height

                page.mouse.dblclick(
                    real_x,
                    real_y
                )

                cmd["result"] = {
                    "ok": True
                }

            # ------------------------------------------------
            # WHEEL / SCROLL
            # ------------------------------------------------

            elif command == "wheel":

                dx = float(payload.get("dx", 0))
                dy = float(payload.get("dy", 0))

                page.mouse.wheel(dx, dy)

                cmd["result"] = {
                    "ok": True
                }

            # ------------------------------------------------
            # TYPE TEXT
            # ------------------------------------------------

            elif command == "type":

                text = str(payload.get("text", ""))

                if text:
                    page.keyboard.insert_text(text)

                cmd["result"] = {
                    "ok": True
                }

            # ------------------------------------------------
            # KEYBOARD
            # ------------------------------------------------

            elif command == "key":

                key = str(payload.get("key", ""))

                ctrl = bool(payload.get("ctrl", False))
                shift = bool(payload.get("shift", False))
                alt = bool(payload.get("alt", False))
                meta = bool(payload.get("meta", False))

                modifiers = []

                if ctrl:
                    modifiers.append("Control")

                if shift:
                    modifiers.append("Shift")

                if alt:
                    modifiers.append("Alt")

                if meta:
                    modifiers.append("Meta")

                if len(key) == 1 and not modifiers:
                    page.keyboard.insert_text(key)
                else:

                    combo = "+".join(
                        modifiers + [key]
                    )

                    page.keyboard.press(combo)

                cmd["result"] = {
                    "ok": True
                }

            # ------------------------------------------------
            # RELOAD
            # ------------------------------------------------

            elif command == "reload":

                page.reload(
                    wait_until="domcontentloaded",
                    timeout=25000
                )

                cmd["result"] = {
                    "ok": True
                }

            # ------------------------------------------------
            # CLOSE
            # ------------------------------------------------

            elif command == "close":

                session["closed"] = True

                cmd["result"] = {
                    "ok": True
                }

            else:

                cmd["result"] = {
                    "ok": False,
                    "error": "UNKNOWN_COMMAND"
                }

        except Exception as e:

            cmd["result"] = {
                "ok": False,
                "error": repr(e)
            }

        finally:

            try:
                cmd["event"].set()
            except Exception:
                pass


# ============================================================
# REMOTE SESSION PAGE
# ============================================================

@app.route("/vip/<session_id>")
def view_vip_session(session_id):

    session = get_live_session(session_id)

    if not session:
        return """
        <h2 style="font-family:Arial;text-align:center">
        ⚠️ هذه الجلسة غير موجودة أو انتهت.
        </h2>
        """, 404

    token = request.args.get("token", "")

    if not token or not secrets.compare_digest(
        str(token),
        str(session["token"])
    ):
        return """
        <h2 style="font-family:Arial;text-align:center">
        🔒 رابط غير صالح.
        </h2>
        """, 403

    number = html.escape(
        str(session["number"])
    )

    session_id_js = json.dumps(session_id)
    token_js = json.dumps(token)

    page_html = f"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">

<head>

<meta charset="UTF-8">

<meta name="viewport"
      content="width=device-width,
               initial-scale=1,
               maximum-scale=1">

<title>Free Mobile Remote Browser</title>

<style>

* {{
    box-sizing:border-box;
}}

body {{
    margin:0;
    background:#0f172a;
    color:white;
    font-family:Arial,sans-serif;
}}

.header {{
    padding:15px;
    background:#1e293b;
    text-align:center;
    position:sticky;
    top:0;
    z-index:20;
}}

.number {{
    color:#facc15;
    font-size:25px;
    font-weight:bold;
    direction:ltr;
}}

.status {{
    margin-top:7px;
    font-size:13px;
    color:#94a3b8;
}}

.viewer {{
    display:flex;
    justify-content:center;
    padding:15px;
}}

.screen-wrapper {{
    width:min(390px, 100%);
    position:relative;
    background:#000;
    border-radius:14px;
    overflow:hidden;
    box-shadow:0 10px 40px rgba(0,0,0,.5);
}}

#screen {{
    display:block;
    width:100%;
    height:auto;
    min-height:200px;
    background:#000;
    user-select:none;
    -webkit-user-select:none;
    touch-action:none;
}}

.controls {{
    max-width:500px;
    margin:auto;
    padding:10px 15px 30px;
}}

.row {{
    display:flex;
    gap:8px;
    margin-top:8px;
}}

button {{
    flex:1;
    border:0;
    border-radius:10px;
    padding:13px 8px;
    background:#334155;
    color:white;
    font-size:15px;
}}

button:active {{
    transform:scale(.97);
}}

.green {{
    background:#16a34a;
}}

.red {{
    background:#dc2626;
}}

input {{
    flex:1;
    min-width:0;
    border:0;
    border-radius:10px;
    padding:13px;
    font-size:16px;
    direction:auto;
}}

.small {{
    font-size:12px;
}}

</style>

</head>

<body>

<div class="header">

    <div>🔥 Free Mobile Remote Browser</div>

    <div class="number">{number}</div>

    <div id="status" class="status">
        الاتصال بالمتصفح...
    </div>

</div>


<div class="viewer">

    <div class="screen-wrapper">

        <img
            id="screen"
            src=""
            draggable="false"
            alt="Remote Browser"
        >

    </div>

</div>


<div class="controls">

    <div class="row">

        <button onclick="sendKey('ArrowUp')">
            ↑
        </button>

    </div>

    <div class="row">

        <button onclick="sendKey('ArrowLeft')">
            ←
        </button>

        <button onclick="sendKey('Enter')" class="green">
            ENTER
        </button>

        <button onclick="sendKey('ArrowRight')">
            →
        </button>

    </div>

    <div class="row">

        <button onclick="sendKey('ArrowDown')">
            ↓
        </button>

    </div>


    <div class="row">

        <input
            id="textInput"
            placeholder="اكتب نصاً داخل المتصفح..."
        >

        <button
            class="green"
            onclick="sendText()">
            إرسال
        </button>

    </div>


    <div class="row">

        <button onclick="sendKey('Backspace')">
            ⌫
        </button>

        <button onclick="sendKey('Tab')">
            TAB
        </button>

        <button onclick="sendKey('Escape')">
            ESC
        </button>

        <button onclick="reloadPage()">
            🔄
        </button>

    </div>


    <div class="row">

        <button
            class="red"
            onclick="closeSession()">
            إغلاق المتصفح
        </button>

    </div>

</div>


<script>

const SESSION_ID = {session_id_js};
const TOKEN = {token_js};

const BASE =
    window.location.origin +
    "/vip/" +
    encodeURIComponent(SESSION_ID);

const screen =
    document.getElementById("screen");

const status =
    document.getElementById("status");


let busy = false;


/* =========================================================
   SCREENSHOT
========================================================= */

async function refreshScreen() {{

    if (busy) return;

    try {{

        const url =
            BASE +
            "/screen?token=" +
            encodeURIComponent(TOKEN) +
            "&t=" +
            Date.now();

        const response =
            await fetch(url, {{
                cache:"no-store"
            }});

        if (!response.ok) {{

            status.innerText =
                "⚠️ انتهت الجلسة";

            return;
        }}

        const blob =
            await response.blob();

        const imageUrl =
            URL.createObjectURL(blob);

        const old =
            screen.src;

        screen.onload = function() {{

            if (old &&
                old.startsWith("blob:")) {{

                URL.revokeObjectURL(old);

            }}

        }};

        screen.src = imageUrl;

        status.innerText =
            "🟢 المتصفح متصل";

    }} catch(e) {{

        status.innerText =
            "🔴 الاتصال بالمتصفح انقطع";

    }}

}}


/* =========================================================
   CLICK
========================================================= */

async function sendClick(event) {{

    const rect =
        screen.getBoundingClientRect();

    if (!rect.width ||
        !rect.height) return;

    const x =
        event.clientX - rect.left;

    const y =
        event.clientY - rect.top;

    await fetch(
        BASE + "/click",
        {{
            method:"POST",

            headers:{{
                "Content-Type":
                "application/json"
            }},

            body:JSON.stringify({{
                token:TOKEN,
                x:x,
                y:y,
                display_width:rect.width,
                display_height:rect.height
            }})
        }}
    );

}}


/* =========================================================
   TOUCH / MOUSE
========================================================= */

screen.addEventListener(
    "pointerup",
    function(event) {{

        event.preventDefault();

        sendClick(event);

    }}
);


/* =========================================================
   WHEEL
========================================================= */

screen.addEventListener(
    "wheel",
    async function(event) {{

        event.preventDefault();

        await fetch(
            BASE + "/wheel",
            {{
                method:"POST",

                headers:{{
                    "Content-Type":
                    "application/json"
                }},

                body:JSON.stringify({{
                    token:TOKEN,
                    dx:event.deltaX,
                    dy:event.deltaY
                }})
            }}
        );

    }},
    {{passive:false}}
);


/* =========================================================
   KEY
========================================================= */

async function sendKey(key) {{

    await fetch(
        BASE + "/key",
        {{
            method:"POST",

            headers:{{
                "Content-Type":
                "application/json"
            }},

            body:JSON.stringify({{
                token:TOKEN,
                key:key
            }})
        }}
    );

}}


/* =========================================================
   TEXT
========================================================= */

async function sendText() {{

    const input =
        document.getElementById(
            "textInput"
        );

    const text =
        input.value;

    if (!text) return;

    await fetch(
        BASE + "/type",
        {{
            method:"POST",

            headers:{{
                "Content-Type":
                "application/json"
            }},

            body:JSON.stringify({{
                token:TOKEN,
                text:text
            }})
        }}
    );

    input.value = "";

}}


/* =========================================================
   RELOAD
========================================================= */

async function reloadPage() {{

    status.innerText =
        "🔄 إعادة تحميل الصفحة...";

    await fetch(
        BASE + "/reload",
        {{
            method:"POST",

            headers:{{
                "Content-Type":
                "application/json"
            }},

            body:JSON.stringify({{
                token:TOKEN
            }})
        }}
    );

}}


/* =========================================================
   CLOSE
========================================================= */

async function closeSession() {{

    if (!confirm(
        "هل تريد إغلاق المتصفح؟"
    )) return;

    await fetch(
        BASE + "/close",
        {{
            method:"POST",

            headers:{{
                "Content-Type":
                "application/json"
            }},

            body:JSON.stringify({{
                token:TOKEN
            }})
        }}
    );

    status.innerText =
        "🔴 تم إغلاق المتصفح";

}}


/* =========================================================
   REFRESH LOOP
========================================================= */

refreshScreen();

setInterval(
    refreshScreen,
    700
);

</script>

</body>
</html>
"""

    response = make_response(page_html)

    response.set_cookie(
        "vip_active_session",
        session_id,
        max_age=REMOTE_SESSION_TIMEOUT,
        httponly=True,
        samesite="Lax"
    )

    return response


# ============================================================
# SCREEN ENDPOINT
# ============================================================

@app.route("/vip/<session_id>/screen")
def remote_screen(session_id):

    session = check_token(session_id)

    if not session:
        return "Unauthorized", 403

    result = send_remote_command(
        session_id,
        session["token"],
        "screen",
        timeout=8
    )

    if not result.get("ok"):
        return result.get(
            "error",
            "SCREEN_ERROR"
        ), 500

    return Response(
        result["image"],
        mimetype="image/jpeg",
        headers={
            "Cache-Control":
            "no-store, no-cache, must-revalidate"
        }
    )


# ============================================================
# CLICK
# ============================================================

@app.route("/vip/<session_id>/click", methods=["POST"])
def remote_click(session_id):

    session = check_token(session_id)

    if not session:
        return jsonify({
            "ok": False,
            "error": "Unauthorized"
        }), 403

    data = request.get_json(
        silent=True
    ) or {}

    data.pop("token", None)

    return jsonify(
        send_remote_command(
            session_id,
            session["token"],
            "click",
            data
        )
    )


# ============================================================
# DOUBLE CLICK
# ============================================================

@app.route("/vip/<session_id>/dblclick", methods=["POST"])
def remote_dblclick(session_id):

    session = check_token(session)

    if not session:
        return jsonify({
            "ok": False
        }), 403

    data = request.get_json(
        silent=True
    ) or {}

    data.pop("token", None)

    return jsonify(
        send_remote_command(
            session_id,
            session["token"],
            "dblclick",
            data
        )
    )


# ============================================================
# WHEEL
# ============================================================

@app.route("/vip/<session_id>/wheel", methods=["POST"])
def remote_wheel(session_id):

    session = check_token(session_id)

    if not session:
        return jsonify({
            "ok": False
        }), 403

    data = request.get_json(
        silent=True
    ) or {}

    data.pop("token", None)

    return jsonify(
        send_remote_command(
            session_id,
            session["token"],
            "wheel",
            data
        )
    )


# ============================================================
# KEY
# ============================================================

@app.route("/vip/<session_id>/key", methods=["POST"])
def remote_key(session_id):

    session = check_token(session_id)

    if not session:
        return jsonify({
            "ok": False
        }), 403

    data = request.get_json(
        silent=True
    ) or {}

    data.pop("token", None)

    return jsonify(
        send_remote_command(
            session_id,
            session["token"],
            "key",
            data
        )
    )


# ============================================================
# TYPE
# ============================================================

@app.route("/vip/<session_id>/type", methods=["POST"])
def remote_type(session_id):

    session = check_token(session_id)

    if not session:
        return jsonify({
            "ok": False
        }), 403

    data = request.get_json(
        silent=True
    ) or {}

    data.pop("token", None)

    return jsonify(
        send_remote_command(
            session_id,
            session["token"],
            "type",
            data
        )
    )


# ============================================================
# RELOAD
# ============================================================

@app.route("/vip/<session_id>/reload", methods=["POST"])
def remote_reload(session_id):

    session = check_token(session_id)

    if not session:
        return jsonify({
            "ok": False
        }), 403

    return jsonify(
        send_remote_command(
            session_id,
            session["token"],
            "reload",
            {}
        )
    )


# ============================================================
# CLOSE
# ============================================================

@app.route("/vip/<session_id>/close", methods=["POST"])
def remote_close(session_id):

    session = check_token(session_id)

    if not session:
        return jsonify({
            "ok": False
        }), 403

    result = send_remote_command(
        session_id,
        session["token"],
        "close",
        {}
    )

    return jsonify(result)


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
<title>FreeMobile VIP Bot</title>
</head>

<body style="
font-family:Arial;
text-align:center;
padding:50px;
">

<h2>
🚀 FreeMobile VIP Bot يعمل
</h2>

<p>
Remote Browser جاهز.
</p>

</body>
</html>
"""


# ============================================================
# VIP EVALUATION
# ============================================================

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


# ============================================================
# SELECT NUMBER
# ============================================================

def select_number(page, number):

    target = (
        str(number)
        .replace(" ", "")
        .replace("-", "")
        .strip()
    )

    try:

        # --------------------------------------------
        # RADIO
        # --------------------------------------------

        radio_count = page.locator(
            'input[type="radio"]'
        ).count()

        for i in range(radio_count):

            try:

                radio = page.locator(
                    'input[type="radio"]'
                ).nth(i)

                value = (
                    radio.get_attribute("value")
                    or ""
                )

                radio_id = (
                    radio.get_attribute("id")
                    or ""
                )

                combined = (
                    value + " " + radio_id
                ).lower()

                if (
                    "new" in combined
                    or
                    "nouveau" in combined
                ):

                    try:

                        radio.check(
                            force=True,
                            timeout=2000
                        )

                    except Exception:

                        try:

                            radio.click(
                                force=True,
                                timeout=2000
                            )

                        except Exception:
                            pass

                    time.sleep(.3)

            except Exception:
                continue

        # --------------------------------------------
        # SELECT
        # --------------------------------------------

        select_count = page.locator(
            "select"
        ).count()

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

                            select.select_option(
                                value=value,
                                timeout=2000
                            )

                            print(
                                "✅ [SELECT] "
                                f"تم اختيار الرقم {number}",
                                flush=True
                            )

                            return True

                    except Exception:
                        continue

            except Exception:
                continue

    except Exception as e:

        print(
            f"⚠️ [SELECT ERROR] {repr(e)}",
            flush=True
        )

    return False


# ============================================================
# SAVE SESSION
# ============================================================

def save_vip_session(
    context,
    number,
    session_id
):

    safe_number = "".join(
        c
        for c in str(number)
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
            f"💾 [SESSION] "
            f"تم حفظ جلسة الرقم {safe_number}",
            flush=True
        )

        return True

    except Exception as e:

        print(
            f"⚠️ [SESSION] "
            f"فشل حفظ الجلسة: {e}",
            flush=True
        )

        return False


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram_alert(
    number,
    desc,
    session_id,
    token
):

    render_url = os.environ.get(
        "RENDER_EXTERNAL_URL",
        "https://freemobile-bot.onrender.com"
    ).rstrip("/")

    open_url = (
        f"{render_url}/vip/"
        f"{session_id}?token={token}"
    )

    message = (
        f"🔥 *رقم مميز VIP جديد!*\n\n"
        f"📱 الرقم: `{number}`\n"
        f"💎 التصنيف: {desc}\n\n"
        f"🖥️ [فتح Remote Browser]"
        f"({open_url})"
    )

    if (
        not TELEGRAM_BOT_TOKEN
        or
        not CHAT_ID
    ):
        print(
            "⚠️ [TELEGRAM] "
            "TELEGRAM_BOT_TOKEN أو CHAT_ID غير موجود",
            flush=True
        )

        return

    telegram_url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
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

        print(
            "📨 [TELEGRAM] "
            f"status={response.status_code}",
            flush=True
        )

    except Exception as e:

        print(
            f"⚠️ [TELEGRAM ERROR] {repr(e)}",
            flush=True
        )


# ============================================================
# REMOTE BROWSER SESSION
# ============================================================

def run_remote_browser_session(
    page,
    session
):

    session_id = session["session_id"]

    print(
        "🖥️ [REMOTE] "
        f"بدأ Remote Browser للجلسة {session_id}",
        flush=True
    )

    started = time.time()

    try:

        while True:

            # تنفيذ أوامر الهاتف/المتصفح
            process_remote_commands(
                page,
                session
            )

            # المستخدم أغلق الجلسة
            if session.get("closed"):
                print(
                    "🛑 [REMOTE] "
                    "تم طلب إغلاق المتصفح",
                    flush=True
                )
                break

            # انتهاء الوقت
            if (
                time.time() - started
                >
                REMOTE_SESSION_TIMEOUT
            ):

                print(
                    "⏰ [REMOTE] "
                    "انتهت مدة الجلسة",
                    flush=True
                )

                break

            # فحص بسيط أن الصفحة ما زالت حية
            try:

                page.url

            except Exception:

                print(
                    "⚠️ [REMOTE] "
                    "الصفحة لم تعد متاحة",
                    flush=True
                )

                break

            time.sleep(.08)

    except Exception as e:

        print(
            f"⚠️ [REMOTE ERROR] {repr(e)}",
            flush=True
        )

    finally:

        session["closed"] = True

        remove_live_session(
            session_id
        )

        print(
            "🧹 [REMOTE] "
            f"تم إنهاء الجلسة {session_id}",
            flush=True
        )


# ============================================================
# MONITOR
# ============================================================

def run_smart_monitor():

    print(
        "🔥🔥🔥 [THREAD ACTIVE] "
        "محرك الفحص بدأ",
        flush=True
    )

    os.environ[
        "PLAYWRIGHT_BROWSERS_PATH"
    ] = "/opt/render/project/src/pw-browsers"

    while True:

        try:

            with sync_playwright() as p:

                print(
                    "✅ [PLAYWRIGHT] "
                    "تم تشغيل Playwright",
                    flush=True
                )

                while True:

                    browser = None
                    context = None
                    page = None

                    try:

                        # ------------------------------------------------
                        # PROXY CONFIGURATION
                        # ------------------------------------------------
                        #
                        # إذا كان لديك PROXIES_LIST سيتم استخدام أول
                        # بروكسي ثابت في هذه الجلسة.
                        #
                        # لا يتم تدوير الـ IP تلقائياً عند 429.
                        # ------------------------------------------------

                        proxies_env = os.environ.get(
                            "PROXIES_LIST",
                            ""
                        )

                        proxy_list = [
                            p.strip()
                            for p in proxies_env.split(",")
                            if p.strip()
                        ]

                        launch_args = {
                            "headless": True,
                            "args": [
                                "--no-sandbox",
                                "--disable-setuid-sandbox",
                                "--disable-dev-shm-usage"
                            ]
                        }

                        if proxy_list:

                            current_proxy = (
                                proxy_list[0]
                            )

                            launch_args["proxy"] = {
                                "server": current_proxy
                            }

                            print(
                                "🌐 [PROXY] "
                                f"استخدام البروكسي: "
                                f"{current_proxy}",
                                flush=True
                            )

                        else:

                            print(
                                "🌐 [IP NORMAL] "
                                "العمل بالـ IP العادي",
                                flush=True
                            )

                        # ------------------------------------------------
                        # LAUNCH
                        # ------------------------------------------------

                        browser = p.chromium.launch(
                            **launch_args
                        )

                        context = browser.new_context(

                            user_agent=(
                                "Mozilla/5.0 "
                                "(iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                                "AppleWebKit/605.1.15 "
                                "(KHTML, like Gecko) "
                                "Version/16.0 "
                                "Mobile/15E148 "
                                "Safari/604.1"
                            ),

                            viewport={
                                "width":390,
                                "height":844
                            },

                            locale="fr-FR"

                        )

                        page = context.new_page()

                        # ------------------------------------------------
                        # OPEN FREE MOBILE
                        # ------------------------------------------------

                        print(
                            "🌐 [PAGE] "
                            "فتح Free Mobile...",
                            flush=True
                        )

                        page.goto(
                            TARGET_URL,
                            wait_until="domcontentloaded",
                            timeout=25000
                        )

                        time.sleep(1.5)

                        # ------------------------------------------------
                        # API
                        # ------------------------------------------------

                        numbers_data = page.evaluate(
                            """
                            async () => {

                                try {

                                    const res =
                                        await fetch(
                                            './api/msisdns?' +
                                            Date.now(),
                                            {
                                                headers: {
                                                    'X-Requested-With':
                                                        'XMLHttpRequest',

                                                    'Cache-Control':
                                                        'no-cache'
                                                }
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

                                } catch(e) {

                                    return {
                                        __error:
                                            String(e)
                                    };

                                }

                            }
                            """
                        )

                        # ------------------------------------------------
                        # ERROR
                        # ------------------------------------------------

                        if (
                            isinstance(
                                numbers_data,
                                dict
                            )
                            and
                            numbers_data.get(
                                "__error"
                            )
                        ):

                            err_msg = str(
                                numbers_data.get(
                                    "__error"
                                )
                            )

                            print(
                                f"⚠️ [API] {err_msg}",
                                flush=True
                            )

                            # عند 429 ننتظر بدلاً من محاولة
                            # تجاوز الـ rate limit بتغيير IP.
                            if "429" in err_msg:

                                print(
                                    "⏳ [RATE LIMIT] "
                                    "انتظار قبل المحاولة التالية...",
                                    flush=True
                                )

                                time.sleep(
                                    random.uniform(
                                        15,
                                        30
                                    )
                                )

                        else:

                            # ------------------------------------------------
                            # NUMBERS
                            # ------------------------------------------------

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
                                "📱 [API] "
                                f"عدد الأرقام: "
                                f"{len(numbers_list)}",
                                flush=True
                            )

                            found = False

                            # ------------------------------------------------
                            # SEARCH VIP
                            # ------------------------------------------------

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
                                    "🔥🔥🔥 "
                                    f"VIP FOUND! "
                                    f"الرقم: {num_val}",
                                    flush=True
                                )

                                # ------------------------------------------------
                                # SELECT NUMBER
                                # ------------------------------------------------

                                selected = select_number(
                                    page,
                                    num_val
                                )

                                print(
                                    "🎯 [SELECT] "
                                    f"نتيجة اختيار الرقم: "
                                    f"{selected}",
                                    flush=True
                                )

                                # ------------------------------------------------
                                # CREATE REMOTE SESSION
                                # ------------------------------------------------

                                session = (
                                    create_live_session(
                                        num_val
                                    )
                                )

                                session_id = (
                                    session[
                                        "session_id"
                                    ]
                                )

                                token = (
                                    session[
                                        "token"
                                    ]
                                )

                                # ------------------------------------------------
                                # SAVE STORAGE STATE
                                # ------------------------------------------------

                                saved = (
                                    save_vip_session(
                                        context,
                                        num_val,
                                        session_id
                                    )
                                )

                                if saved:

                                    # ------------------------------------------------
                                    # TELEGRAM
                                    # ------------------------------------------------

                                    send_telegram_alert(
                                        num_val,
                                        vip_desc,
                                        session_id,
                                        token
                                    )

                                    print(
                                        "🖥️ [REMOTE] "
                                        "المتصفح سيبقى مفتوحاً "
                                        "حتى إغلاق الجلسة أو انتهاء "
                                        "20 دقيقة.",
                                        flush=True
                                    )

                                    # ------------------------------------------------
                                    # IMPORTANT:
                                    # DO NOT CLOSE BROWSER HERE
                                    # ------------------------------------------------

                                    run_remote_browser_session(
                                        page,
                                        session
                                    )

                                else:

                                    remove_live_session(
                                        session_id
                                    )

                                break

                            # ------------------------------------------------
                            # NO VIP
                            # ------------------------------------------------

                            if not found:

                                print(
                                    "🔍 [MONITOR] "
                                    "لا يوجد رقم VIP هذه المرة",
                                    flush=True
                                )

                    except Exception as e:

                        print(
                            "⚠️ [LOOP ERROR] "
                            f"{repr(e)}",
                            flush=True
                        )

                    finally:

                        # ------------------------------------------------
                        # بعد Remote Session فقط يتم الإغلاق
                        # ------------------------------------------------

                        if browser:

                            try:
                                browser.close()

                            except Exception:
                                pass

                    # ------------------------------------------------
                    # NORMAL DELAY
                    # ------------------------------------------------

                    delay = random.uniform(
                        MIN_DELAY,
                        MAX_DELAY
                    )

                    time.sleep(delay)

        except Exception as e:

            print(
                "❌ [PLAYWRIGHT RESTART ERROR] "
                f"{repr(e)}",
                flush=True
            )

            time.sleep(5)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    monitor_thread = threading.Thread(
        target=run_smart_monitor,
        daemon=True
    )

    monitor_thread.start()

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
