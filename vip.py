import os
import json
import time
import random
import uuid
import secrets
import requests
import threading
import sys
import html
import queue

from flask import Flask, make_response, request, Response, jsonify
from playwright.sync_api import sync_playwright


# ============================================================
# BASIC CONFIG
# ============================================================

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

TARGET_URL = "https://mobile.free.fr/souscription/options"

# لا نحفظ جلسات VIP على القرص.
# الجلسة تبقى في الذاكرة فقط أثناء عمل Remote Browser.
REMOTE_SESSION_TIMEOUT = 5 * 60

# دورة الفحص بين المحاولات
MIN_DELAY = 2.5
MAX_DELAY = 4.5

# إعدادات الصورة لتخفيف استهلاك Render والشبكة
SCREEN_QUALITY = 50

LIVE_SESSIONS = {}
LIVE_SESSIONS_LOCK = threading.Lock()


# ============================================================
# PROXY FETCHER
# ============================================================

def fetch_fresh_proxies():
    """جلب بروكسيات فرنسية HTTP من المصدر المستخدم سابقاً."""
    try:
        res = requests.get(
            "https://api.geonode.com/proxies?limit=10&format=json&country=FR&protocols=http",
            timeout=10
        )

        if res.status_code == 200:
            data = res.json().get("data", [])
            proxies = []

            for item in data:
                ip = item.get("ip")
                port = item.get("port")

                if ip and port:
                    proxies.append(f"http://{ip}:{port}")

            if proxies:
                print(
                    f"🌐 [PROXY] تم جلب {len(proxies)} بروكسي فرنسي",
                    flush=True
                )
                return proxies

    except Exception as e:
        print(f"⚠️ [PROXY FETCH ERROR] {repr(e)}", flush=True)

    return []


# ============================================================
# LIVE SESSIONS
# ============================================================

def create_live_session(number):
    session_id = uuid.uuid4().hex

    data = {
        "session_id": session_id,
        "token": secrets.token_urlsafe(32),
        "number": str(number),
        "created": time.time(),
        "queue": queue.Queue(maxsize=30),
        "closed": False
    }

    with LIVE_SESSIONS_LOCK:
        LIVE_SESSIONS[session_id] = data

    return data


def get_live_session(session_id):
    with LIVE_SESSIONS_LOCK:
        return LIVE_SESSIONS.get(session_id)


def remove_live_session(session_id):
    with LIVE_SESSIONS_LOCK:
        LIVE_SESSIONS.pop(session_id, None)


def token_valid(session_id):
    session = get_live_session(session_id)

    if not session:
        return None

    supplied = (
        request.args.get("token")
        or request.form.get("token")
    )

    if not supplied:
        try:
            body = request.get_json(silent=True) or {}
            supplied = body.get("token")
        except Exception:
            supplied = None

    if not supplied:
        return None

    try:
        if not secrets.compare_digest(
            str(supplied),
            str(session["token"])
        ):
            return None
    except Exception:
        return None

    return session


# ============================================================
# REMOTE COMMAND QUEUE
# ============================================================

def send_remote_command(
    session_id,
    token,
    command,
    payload=None,
    timeout=6
):
    session = get_live_session(session_id)

    if not session:
        return {
            "ok": False,
            "error": "SESSION_NOT_FOUND"
        }

    try:
        if not secrets.compare_digest(
            str(token),
            str(session["token"])
        ):
            return {
                "ok": False,
                "error": "INVALID_TOKEN"
            }
    except Exception:
        return {
            "ok": False,
            "error": "INVALID_TOKEN"
        }

    event = threading.Event()

    command_data = {
        "command": command,
        "payload": payload or {},
        "event": event,
        "result": None
    }

    try:
        session["queue"].put_nowait(command_data)
    except queue.Full:
        return {
            "ok": False,
            "error": "COMMAND_QUEUE_FULL"
        }

    if not event.wait(timeout):
        return {
            "ok": False,
            "error": "COMMAND_TIMEOUT"
        }

    return command_data.get("result") or {
        "ok": False,
        "error": "NO_RESULT"
    }


# ============================================================
# PLAYWRIGHT HELPERS
# ============================================================

def coords_from_payload(page, payload):
    viewport = page.viewport_size or {
        "width": 390,
        "height": 844
    }

    display_width = float(
        payload.get("display_width") or 390
    )
    display_height = float(
        payload.get("display_height") or 844
    )

    x = float(payload.get("x") or 0)
    y = float(payload.get("y") or 0)

    if display_width <= 0:
        display_width = 390

    if display_height <= 0:
        display_height = 844

    real_x = x * viewport["width"] / display_width
    real_y = y * viewport["height"] / display_height

    real_x = max(0, min(real_x, viewport["width"] - 1))
    real_y = max(0, min(real_y, viewport["height"] - 1))

    return real_x, real_y


def process_remote_commands(page, session):
    """
    يعالج الأوامر بسرعة.
    لا يوجد sleep داخل المعالج حتى لا تتراكم أوامر الهاتف.
    """
    processed = 0

    while processed < 25:
        try:
            command_data = session["queue"].get_nowait()
        except queue.Empty:
            break

        processed += 1

        command = command_data["command"]
        payload = command_data.get("payload") or {}

        try:
            if command == "screen":
                image = page.screenshot(
                    type="jpeg",
                    quality=SCREEN_QUALITY,
                    animations="disabled"
                )

                command_data["result"] = {
                    "ok": True,
                    "image": image
                }

            elif command == "click":
                x, y = coords_from_payload(page, payload)
                page.mouse.click(x, y)

                command_data["result"] = {
                    "ok": True
                }

            elif command == "dblclick":
                x, y = coords_from_payload(page, payload)
                page.mouse.dblclick(x, y)

                command_data["result"] = {
                    "ok": True
                }

            elif command == "wheel":
                dx = float(payload.get("dx") or 0)
                dy = float(payload.get("dy") or 0)

                page.mouse.wheel(dx, dy)

                command_data["result"] = {
                    "ok": True
                }

            elif command == "type":
                text = str(payload.get("text") or "")

                if text:
                    page.keyboard.insert_text(text)

                command_data["result"] = {
                    "ok": True
                }

            elif command == "key":
                key = str(payload.get("key") or "")

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
                    combo = "+".join(modifiers + [key])
                    page.keyboard.press(combo)

                command_data["result"] = {
                    "ok": True
                }

            elif command == "reload":
                page.reload(
                    wait_until="domcontentloaded",
                    timeout=25000
                )

                command_data["result"] = {
                    "ok": True
                }

            elif command == "close":
                session["closed"] = True

                command_data["result"] = {
                    "ok": True
                }

            else:
                command_data["result"] = {
                    "ok": False,
                    "error": "UNKNOWN_COMMAND"
                }

        except Exception as e:
            command_data["result"] = {
                "ok": False,
                "error": repr(e)
            }

        finally:
            command_data["event"].set()


# ============================================================
# REMOTE BROWSER HTML
# ============================================================

@app.route("/vip/<session_id>")
def remote_page(session_id):
    session = get_live_session(session_id)

    if not session:
        return (
            """
            <h2 style="font-family:Arial;text-align:center">
            ⚠️ انتهت جلسة Remote Browser
            </h2>
            """,
            404
        )

    token = request.args.get("token", "")

    if (
        not token
        or not secrets.compare_digest(
            str(token),
            str(session["token"])
        )
    ):
        return (
            """
            <h2 style="font-family:Arial;text-align:center">
            🔒 رابط غير صالح
            </h2>
            """,
            403
        )

    number = html.escape(str(session["number"]))

    page_html = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover">

<title>Free Mobile Remote Browser</title>

<style>
* {
    box-sizing: border-box;
}

html, body {
    margin: 0;
    padding: 0;
    background: #0f172a;
    color: white;
    font-family: Arial, sans-serif;
}

body {
    min-height: 100vh;
}

.header {
    background: #1e293b;
    padding: 14px 10px;
    text-align: center;
}

.number {
    direction: ltr;
    color: #facc15;
    font-size: 25px;
    font-weight: bold;
    margin-top: 5px;
}

.status {
    margin-top: 6px;
    color: #94a3b8;
    font-size: 13px;
}

.viewer {
    padding: 10px;
    display: flex;
    justify-content: center;
}

.screen-box {
    width: min(390px, 100%);
    background: #000;
    border-radius: 12px;
    overflow: hidden;
    position: relative;
    box-shadow: 0 8px 30px rgba(0,0,0,.45);
}

#screen {
    display: block;
    width: 100%;
    height: auto;
    background: #000;
    user-select: none;
    -webkit-user-select: none;
    -webkit-touch-callout: none;
    touch-action: none;
}

.controls {
    max-width: 500px;
    margin: auto;
    padding: 0 10px 25px;
}

.row {
    display: flex;
    gap: 7px;
    margin-top: 7px;
}

button {
    flex: 1;
    border: 0;
    border-radius: 9px;
    padding: 11px 7px;
    background: #334155;
    color: white;
    font-size: 14px;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
}

button:active {
    transform: scale(.98);
}

.green {
    background: #16a34a;
}

.red {
    background: #dc2626;
}

.blue {
    background: #2563eb;
}

input {
    flex: 1;
    min-width: 0;
    border: 0;
    border-radius: 9px;
    padding: 11px;
    font-size: 16px;
}

.small {
    font-size: 12px;
}
</style>
</head>

<body>

<div class="header">
    <div>🔥 Free Mobile Remote Browser</div>
    <div class="number">__NUMBER__</div>
    <div id="status" class="status">🟡 الاتصال...</div>
</div>

<div class="viewer">
    <div class="screen-box">
        <img id="screen"
             draggable="false"
             alt="Remote Browser">
    </div>
</div>

<div class="controls">

    <div class="row">
        <button class="blue" onclick="sendWheel(0, -500)">
            ⬆️ Scroll Up
        </button>

        <button class="blue" onclick="sendWheel(0, 500)">
            ⬇️ Scroll Down
        </button>
    </div>

    <div class="row">
        <button onclick="sendKey('ArrowUp')">↑</button>
    </div>

    <div class="row">
        <button onclick="sendKey('ArrowLeft')">←</button>
        <button class="green" onclick="sendKey('Enter')">ENTER</button>
        <button onclick="sendKey('ArrowRight')">→</button>
    </div>

    <div class="row">
        <button onclick="sendKey('ArrowDown')">↓</button>
    </div>

    <div class="row">
        <input id="textInput" placeholder="اكتب نصاً...">
        <button class="green" onclick="sendText()">إرسال</button>
    </div>

    <div class="row">
        <button onclick="sendKey('Backspace')">⌫</button>
        <button onclick="sendKey('Tab')">TAB</button>
        <button onclick="sendKey('Escape')">ESC</button>
        <button onclick="reloadPage()">🔄</button>
    </div>

    <div class="row">
        <button class="red" onclick="closeBrowser()">
            🛑 إغلاق المتصفح
        </button>
    </div>

</div>

<script>
const SESSION_ID = "__SID__";
const TOKEN = "__TOKEN__";

const BASE =
    window.location.origin +
    "/vip/" +
    encodeURIComponent(SESSION_ID);

const screen = document.getElementById("screen");
const status = document.getElementById("status");

let screenBusy = false;
let lastObjectUrl = null;

let pointerStart = null;
let pointerMoved = false;


/* ==========================================================
   SCREEN
   ========================================================== */

async function refreshScreen() {

    if (screenBusy) return;

    screenBusy = true;

    try {

        const response = await fetch(
            BASE +
            "/screen?token=" +
            encodeURIComponent(TOKEN) +
            "&t=" +
            Date.now(),
            {
                cache: "no-store"
            }
        );

        if (!response.ok) {
            status.innerText = "🔴 الجلسة غير متاحة";
            screenBusy = false;
            return;
        }

        const blob = await response.blob();

        const objectUrl = URL.createObjectURL(blob);

        const oldUrl = lastObjectUrl;

        screen.onload = function() {

            if (oldUrl) {
                URL.revokeObjectURL(oldUrl);
            }
        };

        lastObjectUrl = objectUrl;
        screen.src = objectUrl;

        status.innerText = "🟢 Remote Browser متصل";

    } catch (e) {

        status.innerText = "🔴 انقطع الاتصال";

    } finally {

        screenBusy = false;
    }
}


/* ==========================================================
   CLICK + SWIPE
   ========================================================== */

screen.addEventListener("pointerdown", function(event) {

    event.preventDefault();

    pointerStart = {
        x: event.clientX,
        y: event.clientY,
        time: Date.now()
    };

    pointerMoved = false;
});


screen.addEventListener("pointermove", function(event) {

    if (!pointerStart) return;

    const dx = event.clientX - pointerStart.x;
    const dy = event.clientY - pointerStart.y;

    if (Math.abs(dx) > 8 || Math.abs(dy) > 8) {
        pointerMoved = true;
    }
});


screen.addEventListener("pointerup", async function(event) {

    if (!pointerStart) return;

    event.preventDefault();

    const start = pointerStart;
    pointerStart = null;

    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;

    const duration = Date.now() - start.time;

    /*
      إذا كان تحريكاً، نرسله كـ wheel.
      هذا يجعل السحب على iPhone أسرع وأقرب للـ scroll الحقيقي.
    */
    if (pointerMoved) {

        await sendWheel(
            0,
            -dy * 2.0
        );

        return;
    }

    /*
      Click عادي
    */
    const rect = screen.getBoundingClientRect();

    if (!rect.width || !rect.height) {
        return;
    }

    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;

    try {

        await fetch(
            BASE + "/click",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    token: TOKEN,
                    x: x,
                    y: y,
                    display_width: rect.width,
                    display_height: rect.height
                })
            }
        );

        /*
          تحديث سريع بعد click بدون انتظار طويل.
        */
        setTimeout(refreshScreen, 80);

    } catch (e) {}
});


screen.addEventListener("pointercancel", function() {
    pointerStart = null;
});


/* ==========================================================
   WHEEL
   ========================================================== */

async function sendWheel(dx, dy) {

    try {

        await fetch(
            BASE + "/wheel",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    token: TOKEN,
                    dx: dx,
                    dy: dy
                })
            }
        );

        /*
          إعادة الصورة بعد الـ scroll بسرعة.
        */
        setTimeout(refreshScreen, 80);

    } catch (e) {}
}


/* ==========================================================
   KEYS
   ========================================================== */

async function sendKey(key) {

    try {

        await fetch(
            BASE + "/key",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    token: TOKEN,
                    key: key
                })
            }
        );

        setTimeout(refreshScreen, 80);

    } catch (e) {}
}


/* ==========================================================
   TEXT
   ========================================================== */

async function sendText() {

    const input =
        document.getElementById("textInput");

    const text = input.value;

    if (!text) return;

    try {

        await fetch(
            BASE + "/type",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    token: TOKEN,
                    text: text
                })
            }
        );

        input.value = "";

        setTimeout(refreshScreen, 80);

    } catch (e) {}
}


/* ==========================================================
   RELOAD
   ========================================================== */

async function reloadPage() {

    status.innerText = "🔄 إعادة تحميل...";

    try {

        await fetch(
            BASE + "/reload",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    token: TOKEN
                })
            }
        );

        setTimeout(refreshScreen, 300);

    } catch (e) {}
}


/* ==========================================================
   CLOSE
   ========================================================== */

async function closeBrowser() {

    if (!confirm("هل تريد إغلاق المتصفح؟")) {
        return;
    }

    try {

        await fetch(
            BASE + "/close",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    token: TOKEN
                })
            }
        );

        status.innerText =
            "🔴 تم إغلاق المتصفح";

    } catch (e) {}
}


/* ==========================================================
   FAST SCREEN REFRESH
   ========================================================== */

/*
   1200ms بدلاً من 700ms:
   يقلل الضغط على Render، بينما click/swipe/key تقوم
   بتحديث الصورة فوراً تقريباً بعد تنفيذ الأمر.
*/
refreshScreen();
setInterval(refreshScreen, 1200);

</script>

</body>
</html>
"""

    page_html = (
        page_html
        .replace("__NUMBER__", number)
        .replace("__SID__", json.dumps(session_id)[1:-1])
        .replace("__TOKEN__", json.dumps(token)[1:-1])
    )

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

    session = token_valid(session_id)

    if not session:
        return "Unauthorized", 403

    result = send_remote_command(
        session_id,
        session["token"],
        "screen",
        timeout=6
    )

    if not result.get("ok"):
        return result.get("error", "SCREEN_ERROR"), 500

    return Response(
        result["image"],
        mimetype="image/jpeg",
        headers={
            "Cache-Control":
                "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache"
        }
    )


# ============================================================
# GENERIC REMOTE COMMAND
# ============================================================

def remote_json_command(session_id, command):

    session = token_valid(session_id)

    if not session:
        return jsonify({
            "ok": False,
            "error": "UNAUTHORIZED"
        }), 403

    data = request.get_json(silent=True) or {}

    data.pop("token", None)

    result = send_remote_command(
        session_id,
        session["token"],
        command,
        data,
        timeout=6
    )

    return jsonify(result)


@app.route("/vip/<session_id>/click", methods=["POST"])
def remote_click(session_id):
    return remote_json_command(session_id, "click")


@app.route("/vip/<session_id>/wheel", methods=["POST"])
def remote_wheel(session_id):
    return remote_json_command(session_id, "wheel")


@app.route("/vip/<session_id>/key", methods=["POST"])
def remote_key(session_id):
    return remote_json_command(session_id, "key")


@app.route("/vip/<session_id>/type", methods=["POST"])
def remote_type(session_id):
    return remote_json_command(session_id, "type")


@app.route("/vip/<session_id>/reload", methods=["POST"])
def remote_reload(session_id):
    return remote_json_command(session_id, "reload")


@app.route("/vip/<session_id>/close", methods=["POST"])
def remote_close(session_id):
    return remote_json_command(session_id, "close")


# ============================================================
# TELEGRAM
# ============================================================

def telegram_api(method, payload):
    if not TELEGRAM_BOT_TOKEN:
        return None

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/"
        + method
    )

    try:
        return requests.post(
            url,
            json=payload,
            timeout=10
        )
    except Exception as e:
        print(
            f"⚠️ [TELEGRAM API ERROR] {repr(e)}",
            flush=True
        )

    return None


def send_telegram_alert(number, desc, session_id, token):

    render_url = os.environ.get(
        "RENDER_EXTERNAL_URL",
        "https://freemobile-bot.onrender.com"
    ).rstrip("/")

    open_url = (
        f"{render_url}/vip/"
        f"{session_id}?token={token}"
    )

    message = (
        "🔥 *رقم مميز VIP جديد!*\n\n"
        f"📱 الرقم: `{number}`\n"
        f"💎 التصنيف: {desc}\n\n"
        "🖥️ اضغط لفتح Remote Browser."
    )

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "🖥️ فتح Remote Browser",
                    "url": open_url
                }
            ],
            [
                {
                    "text": "❌ لا يعجبني — تخطي الرقم",
                    "callback_data": f"skip:{session_id}"
                }
            ]
        ]
    }

    if not TELEGRAM_BOT_TOKEN or not CHAT_ID:
        return

    response = telegram_api(
        "sendMessage",
        {
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
            "reply_markup": keyboard
        }
    )

    if response is not None and response.status_code != 200:
        print(
            f"⚠️ [TELEGRAM] HTTP={response.status_code} "
            f"{response.text[:300]}",
            flush=True
        )


@app.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():

    update = request.get_json(silent=True) or {}

    callback = update.get("callback_query")

    if not callback:
        return jsonify({"ok": True})

    callback_id = callback.get("id")
    data = str(callback.get("data") or "")

    if not data.startswith("skip:"):
        return jsonify({"ok": True})

    session_id = data[5:].strip()

    session = get_live_session(session_id)

    if session:
        session["closed"] = True

        # لا ننتظر انتهاء الخمس دقائق.
        # وضع close في الطابور يجعل المتصفح يخرج فوراً.
        try:
            session["queue"].put_nowait({
                "command": "close",
                "payload": {},
                "event": threading.Event(),
                "result": None
            })
        except queue.Full:
            pass

        print(
            f"⏭️ [SKIP] تم تخطي الرقم {session['number']}",
            flush=True
        )

    if callback_id:
        telegram_api(
            "answerCallbackQuery",
            {
                "callback_query_id": callback_id,
                "text": "⏭️ تم تخطي الرقم والعودة للبحث",
                "show_alert": False
            }
        )

    message = callback.get("message")

    if message:
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")

        if chat_id and message_id:
            try:
                telegram_api(
                    "editMessageReplyMarkup",
                    {
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "reply_markup": {
                            "inline_keyboard": [
                                [
                                    {
                                        "text": "⏭️ تم تخطي هذا الرقم",
                                        "callback_data": "done"
                                    }
                                ]
                            ]
                        }
                    }
                )
            except Exception:
                pass

    return jsonify({"ok": True})


def configure_telegram_webhook():

    if not TELEGRAM_BOT_TOKEN:
        print(
            "ℹ️ [TELEGRAM] لا يوجد TELEGRAM_BOT_TOKEN",
            flush=True
        )
        return

    render_url = os.environ.get(
        "RENDER_EXTERNAL_URL",
        "https://freemobile-bot.onrender.com"
    ).rstrip("/")

    webhook_url = render_url + "/telegram/webhook"

    response = telegram_api(
        "setWebhook",
        {
            "url": webhook_url,
            "allowed_updates": ["callback_query"]
        }
    )

    if response is not None:
        print(
            f"📨 [TELEGRAM WEBHOOK] "
            f"HTTP={response.status_code}",
            flush=True
        )


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
        <title>Free Mobile VIP Bot</title>
    </head>
    <body style="font-family:Arial;text-align:center;padding:50px;">
        <h2>🚀 Free Mobile VIP Bot</h2>
        <p>🟢 Bot يعمل</p>
        <p>⚡ Remote Browser محسّن للاستجابة</p>
        <p>⏱️ مدة الجلسة القصوى: 5 دقائق</p>
    </body>
    </html>
    """


# ============================================================
# VIP DETECTOR
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
        "0123", "1234", "2345", "3456",
        "4567", "5678", "6789",
        "9876", "8765", "7654",
        "6543", "5432", "4321", "3210"
    ]

    for seq in sequences:
        if seq in d:
            return "تسلسل أرقام متتالي"

    if (
        len(set(d[-4:])) <= 2
        or len(set(d[:4])) <= 2
    ):
        return "تكرار عالي في الأطراف"

    if (
        d[0] == d[1] == d[2]
        or d[-3] == d[-2] == d[-1]
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

    selected = False

    try:
        radios = page.locator(
            'input[type="radio"]'
        )

        for i in range(radios.count()):

            try:
                radio = radios.nth(i)

                value = radio.get_attribute("value") or ""
                radio_id = radio.get_attribute("id") or ""

                combined = (
                    value + " " + radio_id
                ).lower()

                if (
                    "new" in combined
                    or "nouveau" in combined
                ):
                    try:
                        radio.check(
                            force=True,
                            timeout=2000
                        )
                    except Exception:
                        radio.click(
                            force=True,
                            timeout=2000
                        )

                    selected = True
                    break

            except Exception:
                continue

        selects = page.locator("select")

        for i in range(selects.count()):

            try:
                select = selects.nth(i)

                options = select.locator("option")

                for j in range(options.count()):

                    try:
                        option = options.nth(j)

                        value = (
                            option.get_attribute("value")
                            or ""
                        )

                        text = option.inner_text() or ""

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
                            or target in clean_text
                        ):
                            select.select_option(
                                value=value,
                                timeout=2000
                            )

                            print(
                                f"🎯 [SELECT] تم اختيار {number}",
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

    return selected


# ============================================================
# REMOTE SESSION LOOP
# ============================================================

def run_remote_session(page, session):

    started = time.time()

    try:

        while True:

            if session.get("closed"):
                break

            if (
                time.time() - started
                >= REMOTE_SESSION_TIMEOUT
            ):
                print(
                    f"⏱️ [REMOTE] انتهت 5 دقائق "
                    f"للرقم {session['number']}",
                    flush=True
                )
                break

            process_remote_commands(
                page,
                session
            )

            time.sleep(0.02)

    except Exception as e:
        print(
            f"⚠️ [REMOTE LOOP ERROR] {repr(e)}",
            flush=True
        )

    finally:

        session["closed"] = True

        remove_live_session(
            session["session_id"]
        )


# ============================================================
# GET NUMBERS API
# ============================================================

def get_numbers(page):

    return page.evaluate(
        """
        async () => {

            const urls = [
                './api/msisdns?' + Date.now(),
                '/api/msisdns?' + Date.now()
            ];

            let lastError = null;

            for (const url of urls) {

                try {

                    const res = await fetch(
                        url,
                        {
                            method: 'GET',
                            credentials: 'include',
                            headers: {
                                'X-Requested-With':
                                    'XMLHttpRequest',
                                'Cache-Control':
                                    'no-cache'
                            }
                        }
                    );

                    const text = await res.text();

                    let data = null;

                    try {
                        data = JSON.parse(text);
                    } catch(e) {}

                    if (!res.ok) {

                        lastError =
                            'HTTP ' +
                            res.status +
                            ' URL=' +
                            url;

                        if (res.status === 404) {
                            continue;
                        }

                        return {
                            error: lastError
                        };
                    }

                    return {
                        status: res.status,
                        url: url,
                        data: data,
                        raw: text.substring(0, 1000)
                    };

                } catch(e) {

                    lastError = String(e);
                }
            }

            return {
                error:
                    lastError ||
                    'API_REQUEST_FAILED'
            };
        }
        """
    )


# ============================================================
# MAIN MONITOR
# ============================================================

def run_smart_monitor():

    print(
        "🔥🔥🔥 [THREAD ACTIVE] محرك الفحص بدأ",
        flush=True
    )

    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = (
        "/opt/render/project/src/pw-browsers"
    )

    current_proxies = []
    proxy_refresh_time = 0

    while True:

        browser = None

        try:

            with sync_playwright() as p:

                while True:

                    browser = None
                    context = None
                    page = None

                    try:

                        # تحديث قائمة البروكسي كل 10 دقائق
                        # كما هو في النسخة الأصلية.
                        if (
                            time.time() - proxy_refresh_time > 600
                            or not current_proxies
                        ):
                            current_proxies = (
                                fetch_fresh_proxies()
                            )
                            proxy_refresh_time = time.time()

                        proxy = None

                        if current_proxies:
                            proxy = random.choice(
                                current_proxies
                            )

                        launch_args = {
                            "headless": True,
                            "args": [
                                "--no-sandbox",
                                "--disable-setuid-sandbox",
                                "--disable-dev-shm-usage"
                            ]
                        }

                        if proxy:
                            launch_args["proxy"] = {
                                "server": proxy
                            }

                        browser = p.chromium.launch(
                            **launch_args
                        )

                        context = browser.new_context(
                            user_agent=(
                                "Mozilla/5.0 "
                                "(iPhone; CPU iPhone OS 16_0 like Mac OS X) "
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

                        page.goto(
                            TARGET_URL,
                            wait_until="domcontentloaded",
                            timeout=25000
                        )

                        time.sleep(1.2)

                        api_result = get_numbers(page)

                        if (
                            isinstance(api_result, dict)
                            and api_result.get("error")
                        ):

                            err = str(
                                api_result["error"]
                            )

                            print(
                                f"⚠️ [API ERROR] {err} "
                                f"(البروكسي: {proxy})",
                                flush=True
                            )

                            # إبقاء منطق الـ IP/Proxy كما هو.
                            if (
                                proxy
                                and proxy in current_proxies
                            ):
                                current_proxies.remove(
                                    proxy
                                )

                            if "429" in err:
                                time.sleep(
                                    random.uniform(5, 10)
                                )
                            else:
                                time.sleep(
                                    random.uniform(3, 6)
                                )

                        else:

                            status = api_result.get(
                                "status"
                            )

                            data = api_result.get(
                                "data"
                            )

                            raw = api_result.get(
                                "raw",
                                ""
                            )

                            numbers_list = []

                            if isinstance(
                                data,
                                list
                            ):
                                numbers_list = data

                            elif isinstance(
                                data,
                                dict
                            ):
                                numbers_list = (
                                    data.get(
                                        "msisdns",
                                        []
                                    )
                                )

                            print(
                                f"📱 [API] HTTP={status} | "
                                f"عدد الأرقام: "
                                f"{len(numbers_list)} | "
                                f"البروكسي: {proxy}",
                                flush=True
                            )

                            if (
                                not numbers_list
                                and raw
                            ):
                                print(
                                    f"📄 [API RAW] "
                                    f"{raw[:300]}",
                                    flush=True
                                )

                            found = False

                            for item in numbers_list:

                                if isinstance(
                                    item,
                                    dict
                                ):
                                    number = item.get(
                                        "value"
                                    )
                                else:
                                    number = str(item)

                                if not number:
                                    continue

                                desc = (
                                    evaluate_vip_expanded(
                                        number
                                    )
                                )

                                if not desc:
                                    continue

                                found = True

                                print(
                                    f"🔥🔥🔥 VIP FOUND: "
                                    f"{number}",
                                    flush=True
                                )

                                # اختيار الرقم في الصفحة
                                select_number(
                                    page,
                                    number
                                )

                                session = (
                                    create_live_session(
                                        number
                                    )
                                )

                                session_id = (
                                    session[
                                        "session_id"
                                    ]
                                )

                                token = session[
                                    "token"
                                ]

                                # لا يوجد save_vip_session
                                # ولا تخزين JSON.
                                send_telegram_alert(
                                    number,
                                    desc,
                                    session_id,
                                    token
                                )

                                # ينتظر 5 دقائق كحد أقصى
                                # أو يخرج فور ضغط Skip.
                                run_remote_session(
                                    page,
                                    session
                                )

                                break

                            if not found:

                                print(
                                    "🔍 [MONITOR] "
                                    "لا يوجد VIP هذه المرة",
                                    flush=True
                                )

                    except Exception as e:

                        print(
                            f"⚠️ [LOOP ERROR] "
                            f"{repr(e)}",
                            flush=True
                        )

                    finally:

                        if browser:

                            try:
                                browser.close()
                            except Exception:
                                pass

                    time.sleep(
                        random.uniform(
                            MIN_DELAY,
                            MAX_DELAY
                        )
                    )

        except Exception as e:

            print(
                f"❌ [PLAYWRIGHT ERROR] "
                f"{repr(e)}",
                flush=True
            )

            time.sleep(5)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    print(
        "🚀 [START] تشغيل Free Mobile VIP Bot",
        flush=True
    )

    # Telegram webhook للزر "تخطي"
    try:
        configure_telegram_webhook()
    except Exception as e:
        print(
            f"⚠️ [WEBHOOK ERROR] {repr(e)}",
            flush=True
        )

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
