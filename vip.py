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

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    ""
)

CHAT_ID = os.environ.get(
    "CHAT_ID",
    ""
)

TARGET_URL = (
    "https://mobile.free.fr/"
    "souscription/options"
)

SESSION_DIR = "vip_sessions"

os.makedirs(
    SESSION_DIR,
    exist_ok=True
)

# ============================================================
# REMOTE SESSION = 5 MINUTES
# ============================================================

REMOTE_SESSION_TIMEOUT = 5 * 60

MIN_DELAY = 2.5
MAX_DELAY = 4.5


# ============================================================
# AUTO PROXY FETCHER
# ============================================================

def fetch_fresh_proxies():
    """جلب بروكسيات فرنسية مجانية وحية تلقائياً من الإنترنت"""
    try:
        res = requests.get(
            "https://api.geonode.com/proxies?limit=10&format=json&country=FR&protocols=http",
            timeout=10
        )

        if res.status_code == 200:
            data = res.json().get("data", [])
            proxies = []

            for p in data:
                ip = p.get("ip")
                port = p.get("port")

                if ip and port:
                    proxies.append(
                        f"http://{ip}:{port}"
                    )

            if proxies:
                print(
                    f"🌐 [PROXY] تم جلب {len(proxies)} بروكسي فرنسي بنجاح",
                    flush=True
                )
                return proxies

    except Exception as e:
        print(
            f"⚠️ [PROXY FETCH ERROR] {repr(e)}",
            flush=True
        )

    return []


# ============================================================
# REMOTE SESSIONS
# ============================================================

LIVE_SESSIONS = {}

LIVE_SESSIONS_LOCK = threading.Lock()


def create_live_session(number):

    session_id = uuid.uuid4().hex

    token = secrets.token_urlsafe(32)

    data = {
        "session_id": session_id,
        "token": token,
        "number": str(number),
        "created": time.time(),
        "queue": queue.Queue(),
        "closed": False
    }

    with LIVE_SESSIONS_LOCK:

        LIVE_SESSIONS[
            session_id
        ] = data

    return data


def get_live_session(session_id):

    with LIVE_SESSIONS_LOCK:

        return LIVE_SESSIONS.get(
            session_id
        )


def remove_live_session(session_id):

    with LIVE_SESSIONS_LOCK:

        LIVE_SESSIONS.pop(
            session_id,
            None
        )


def token_valid(session_id):

    session = get_live_session(
        session_id
    )

    if not session:
        return None

    supplied = (
        request.args.get("token")
        or request.form.get("token")
    )

    if not supplied:

        try:

            body = (
                request.get_json(
                    silent=True
                )
                or {}
            )

            supplied = body.get(
                "token"
            )

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
# REMOTE COMMAND
# ============================================================

def send_remote_command(
    session_id,
    token,
    command,
    payload=None,
    timeout=10
):

    session = get_live_session(
        session_id
    )

    if not session:

        return {
            "ok": False,
            "error": "SESSION_NOT_FOUND"
        }

    if not secrets.compare_digest(
        str(token),
        str(session["token"])
    ):

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

    session["queue"].put(
        command_data
    )

    if not event.wait(timeout):

        return {
            "ok": False,
            "error": "COMMAND_TIMEOUT"
        }

    return (
        command_data.get(
            "result"
        )
        or
        {
            "ok": False,
            "error": "NO_RESULT"
        }
    )


# ============================================================
# PLAYWRIGHT COMMAND PROCESSOR
# ============================================================

def process_remote_commands(
    page,
    session
):

    processed = 0

    while processed < 10:

        try:

            command_data = (
                session["queue"]
                .get_nowait()
            )

        except queue.Empty:

            break

        processed += 1

        command = command_data[
            "command"
        ]

        payload = command_data.get(
            "payload",
            {}
        )

        try:

            # ------------------------------------------------
            # SCREEN
            # ------------------------------------------------

            if command == "screen":

                image = page.screenshot(
                    type="jpeg",
                    quality=72
                )

                command_data["result"] = {
                    "ok": True,
                    "image": image
                }

            # ------------------------------------------------
            # CLICK
            # ------------------------------------------------

            elif command == "click":

                x = float(
                    payload.get(
                        "x",
                        0
                    )
                )

                y = float(
                    payload.get(
                        "y",
                        0
                    )
                )

                display_width = float(
                    payload.get(
                        "display_width",
                        390
                    )
                )

                display_height = float(
                    payload.get(
                        "display_height",
                        844
                    )
                )

                viewport = (
                    page.viewport_size
                    or
                    {
                        "width": 390,
                        "height": 844
                    }
                )

                real_x = (
                    x
                    *
                    viewport["width"]
                    /
                    display_width
                )

                real_y = (
                    y
                    *
                    viewport["height"]
                    /
                    display_height
                )

                page.mouse.click(
                    real_x,
                    real_y
                )

                command_data["result"] = {
                    "ok": True
                }

            # ------------------------------------------------
            # DOUBLE CLICK
            # ------------------------------------------------

            elif command == "dblclick":

                x = float(
                    payload.get(
                        "x",
                        0
                    )
                )

                y = float(
                    payload.get(
                        "y",
                        0
                    )
                )

                display_width = float(
                    payload.get(
                        "display_width",
                        390
                    )
                )

                display_height = float(
                    payload.get(
                        "display_height",
                        844
                    )
                )

                viewport = (
                    page.viewport_size
                    or
                    {
                        "width": 390,
                        "height": 844
                    }
                )

                real_x = (
                    x
                    *
                    viewport["width"]
                    /
                    display_width
                )

                real_y = (
                    y
                    *
                    viewport["height"]
                    /
                    display_height
                )

                page.mouse.dblclick(
                    real_x,
                    real_y
                )

                command_data["result"] = {
                    "ok": True
                }

            # ------------------------------------------------
            # WHEEL / SCROLL
            # ------------------------------------------------

            elif command == "wheel":

                dx = float(
                    payload.get(
                        "dx",
                        0
                    )
                )

                dy = float(
                    payload.get(
                        "dy",
                        0
                    )
                )

                page.mouse.wheel(
                    dx,
                    dy
                )

                command_data["result"] = {
                    "ok": True
                }

            # ------------------------------------------------
            # TYPE
            # ------------------------------------------------

            elif command == "type":

                text = str(
                    payload.get(
                        "text",
                        ""
                    )
                )

                if text:

                    page.keyboard.insert_text(
                        text
                    )

                command_data["result"] = {
                    "ok": True
                }

            # ------------------------------------------------
            # KEY
            # ------------------------------------------------

            elif command == "key":

                key = str(
                    payload.get(
                        "key",
                        ""
                    )
                )

                ctrl = bool(
                    payload.get(
                        "ctrl",
                        False
                    )
                )

                shift = bool(
                    payload.get(
                        "shift",
                        False
                    )
                )

                alt = bool(
                    payload.get(
                        "alt",
                        False
                    )
                )

                meta = bool(
                    payload.get(
                        "meta",
                        False
                    )
                )

                modifiers = []

                if ctrl:
                    modifiers.append(
                        "Control"
                    )

                if shift:
                    modifiers.append(
                        "Shift"
                    )

                if alt:
                    modifiers.append(
                        "Alt"
                    )

                if meta:
                    modifiers.append(
                        "Meta"
                    )

                if (
                    len(key) == 1
                    and not modifiers
                ):

                    page.keyboard.insert_text(
                        key
                    )

                else:

                    combo = "+".join(
                        modifiers + [key]
                    )

                    page.keyboard.press(
                        combo
                    )

                command_data["result"] = {
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

                time.sleep(1)

                command_data["result"] = {
                    "ok": True
                }

            # ------------------------------------------------
            # CLOSE
            # ------------------------------------------------

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

            command_data[
                "event"
            ].set()


# ============================================================
# REMOTE BROWSER PAGE
# ============================================================

@app.route("/vip/<session_id>")
def remote_page(session_id):

    session = get_live_session(
        session_id
    )

    if not session:

        return (
            """
            <h2 style="font-family:Arial;text-align:center">
            ⚠️ انتهت جلسة Remote Browser
            </h2>
            """,
            404
        )

    token = request.args.get(
        "token",
        ""
    )

    if (
        not token
        or
        not secrets.compare_digest(
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

    number = html.escape(
        str(session["number"])
    )

    sid = json.dumps(
        session_id
    )

    tok = json.dumps(
        token
    )

    page_html = f"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">

<head>

<meta charset="UTF-8">

<meta name="viewport"
      content="width=device-width,
               initial-scale=1,
               maximum-scale=1,
               user-scalable=no">

<title>Free Mobile Remote Browser</title>

<style>

* {{
    box-sizing:border-box;
}}

html,
body {{
    margin:0;
    padding:0;
    width:100%;
    min-height:100%;
}}

body {{
    background:#0f172a;
    color:#fff;
    font-family:Arial,sans-serif;
    overscroll-behavior:none;
}}

.header {{
    background:#1e293b;
    padding:14px;
    text-align:center;
    position:sticky;
    top:0;
    z-index:10;
}}

.number {{
    direction:ltr;
    color:#facc15;
    font-size:25px;
    font-weight:bold;
    margin-top:5px;
}}

.status {{
    margin-top:6px;
    color:#94a3b8;
    font-size:13px;
}}

.viewer {{
    padding:15px;
    display:flex;
    justify-content:center;
}}

.screen-box {{
    width:min(390px,100%);
    background:#000;
    border-radius:15px;
    overflow:hidden;
    box-shadow:
        0 10px 40px rgba(0,0,0,.5);
    position:relative;
}}

#screen {{
    display:block;
    width:100%;
    height:auto;
    background:#000;

    user-select:none;
    -webkit-user-select:none;

    -webkit-touch-callout:none;

    touch-action:none;

    cursor:pointer;
}}

.controls {{
    max-width:500px;
    margin:auto;
    padding:0 15px 30px;
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
    cursor:pointer;
    touch-action:manipulation;
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

.blue {{
    background:#2563eb;
}}

input {{
    flex:1;
    min-width:0;
    border:0;
    border-radius:10px;
    padding:13px;
    font-size:16px;
}}

</style>

</head>

<body>

<div class="header">

    <div>
        🔥 Free Mobile Remote Browser
    </div>

    <div class="number">
        {number}
    </div>

    <div id="status"
         class="status">
        🟡 الاتصال...
    </div>

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

        <button
            class="blue"
            onclick="sendWheel(0, -350)">
            ⬆️ Scroll Up
        </button>

        <button
            class="blue"
            onclick="sendWheel(0, 350)">
            ⬇️ Scroll Down
        </button>

    </div>


    <div class="row">

        <button onclick="sendKey('ArrowUp')">
            ↑
        </button>

    </div>


    <div class="row">

        <button onclick="sendKey('ArrowLeft')">
            ←
        </button>

        <button
            class="green"
            onclick="sendKey('Enter')">
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
            placeholder="اكتب نصاً...">

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
            onclick="closeBrowser()">
            🛑 إغلاق المتصفح
        </button>

    </div>

</div>


<script>

const SESSION_ID = {sid};

const TOKEN = {tok};

const BASE =
    window.location.origin
    + "/vip/"
    + encodeURIComponent(SESSION_ID);

const screen =
    document.getElementById("screen");

const status =
    document.getElementById("status");

let loading = false;


/* ============================================================
   SCREEN REFRESH
   ============================================================ */

async function refreshScreen() {{

    if (loading) return;

    loading = true;

    try {{

        const response = await fetch(
            BASE
            + "/screen?token="
            + encodeURIComponent(TOKEN)
            + "&t="
            + Date.now(),
            {{
                cache:"no-store"
            }}
        );

        if (!response.ok) {{

            status.innerText =
                "🔴 الجلسة غير متاحة";

            loading = false;

            return;
        }}

        const blob =
            await response.blob();

        const oldSrc =
            screen.src;

        screen.src =
            URL.createObjectURL(blob);

        if (oldSrc &&
            oldSrc.startsWith("blob:")) {{

            try {{
                URL.revokeObjectURL(oldSrc);
            }} catch(e) {{}}
        }}

        status.innerText =
            "🟢 Remote Browser متصل";

    }}
    catch(e) {{

        status.innerText =
            "🔴 انقطع الاتصال";
    }}

    loading = false;
}}


/* ============================================================
   TOUCH / SWIPE VARIABLES
   ============================================================ */

let pointerStartX = 0;

let pointerStartY = 0;

let pointerLastX = 0;

let pointerLastY = 0;

let isDragging = false;

let movedDistance = 0;

let wheelSending = false;

let pendingDy = 0;


/* ============================================================
   POINTER DOWN
   ============================================================ */

screen.addEventListener(
    "pointerdown",
    function(event) {{

        event.preventDefault();

        pointerStartX =
            event.clientX;

        pointerStartY =
            event.clientY;

        pointerLastX =
            event.clientX;

        pointerLastY =
            event.clientY;

        isDragging = false;

        movedDistance = 0;

        try {{

            screen.setPointerCapture(
                event.pointerId
            );

        }} catch(e) {{}}

    }}
);


/* ============================================================
   POINTER MOVE
   ============================================================ */

screen.addEventListener(
    "pointermove",
    async function(event) {{

        event.preventDefault();

        const dx =
            event.clientX
            - pointerLastX;

        const dy =
            event.clientY
            - pointerLastY;

        pointerLastX =
            event.clientX;

        pointerLastY =
            event.clientY;

        movedDistance +=
            Math.abs(dx)
            +
            Math.abs(dy);

        /*
         * حركة أقل من 8 بكسل تعتبر ضغطة
         */

        if (movedDistance < 8) {{
            return;
        }}

        isDragging = true;

        /*
         * إصبع يتحرك للأعلى
         * = الصفحة تنزل
         */

        const scrollDy =
            -dy;

        pendingDy +=
            scrollDy;

        if (wheelSending) {{
            return;
        }}

        wheelSending = true;

        try {{

            while (
                Math.abs(pendingDy) >= 1
            ) {{

                const amount =
                    Math.max(
                        -150,
                        Math.min(
                            150,
                            pendingDy
                        )
                    );

                pendingDy -=
                    amount;

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
                            dx:0,
                            dy:amount
                        }})
                    }}
                );
            }}

        }}
        catch(e) {{}}

        wheelSending = false;

        setTimeout(
            refreshScreen,
            150
        );

    }}
);


/* ============================================================
   POINTER UP
   ============================================================ */

screen.addEventListener(
    "pointerup",
    async function(event) {{

        event.preventDefault();

        /*
         * إذا كان المستخدم يسحب،
         * لا نرسل Click
         */

        if (isDragging) {{

            setTimeout(
                refreshScreen,
                200
            );

            return;
        }

        const rect =
            screen.getBoundingClientRect();

        if (
            !rect.width ||
            !rect.height
        ) {{
            return;
        }}

        const x =
            event.clientX
            - rect.left;

        const y =
            event.clientY
            - rect.top;

        try {{

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

                        display_width:
                            rect.width,

                        display_height:
                            rect.height
                    }})
                }}
            );

            setTimeout(
                refreshScreen,
                300
            );

        }}
        catch(e) {{}}

    }}
);


/* ============================================================
   POINTER CANCEL
   ============================================================ */

screen.addEventListener(
    "pointercancel",
    function(event) {{

        isDragging = false;

    }}
);


/* ============================================================
   WHEEL
   ============================================================ */

screen.addEventListener(
    "wheel",
    async function(event) {{

        event.preventDefault();

        try {{

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

            setTimeout(
                refreshScreen,
                150
            );

        }}
        catch(e) {{}}

    }},
    {{
        passive:false
    }}
);


/* ============================================================
   BUTTON SCROLL
   ============================================================ */

async function sendWheel(dx, dy) {{

    try {{

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
                    dx:dx,
                    dy:dy
                }})
            }}
        );

        setTimeout(
            refreshScreen,
            300
        );

    }}
    catch(e) {{}}
}}


/* ============================================================
   KEY
   ============================================================ */

async function sendKey(key) {{

    try {{

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

        setTimeout(
            refreshScreen,
            300
        );

    }}
    catch(e) {{}}
}}


/* ============================================================
   TEXT
   ============================================================ */

async function sendText() {{

    const input =
        document.getElementById(
            "textInput"
        );

    const text =
        input.value;

    if (!text) return;

    try {{

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

        setTimeout(
            refreshScreen,
            300
        );

    }}
    catch(e) {{}}
}}


/* ============================================================
   RELOAD
   ============================================================ */

async function reloadPage() {{

    status.innerText =
        "🔄 إعادة تحميل...";

    try {{

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

        setTimeout(
            refreshScreen,
            500
        );

    }}
    catch(e) {{}}
}}


/* ============================================================
   CLOSE
   ============================================================ */

async function closeBrowser() {{

    if (
        !confirm(
            "هل تريد إغلاق المتصفح؟"
        )
    ) {{
        return;
    }}

    try {{

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
    catch(e) {{}}
}}


/* ============================================================
   START
   ============================================================ */

refreshScreen();

setInterval(
    refreshScreen,
    700
);

</script>

</body>

</html>
"""

    response = make_response(
        page_html
    )

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

@app.route(
    "/vip/<session_id>/screen"
)
def remote_screen(session_id):

    session = token_valid(
        session_id
    )

    if not session:

        return "Unauthorized", 403

    result = send_remote_command(
        session_id,
        session["token"],
        "screen",
        timeout=8
    )

    if not result.get("ok"):

        return (
            result.get(
                "error",
                "SCREEN_ERROR"
            ),
            500
        )

    return Response(
        result["image"],
        mimetype="image/jpeg",
        headers={
            "Cache-Control":
                "no-store, no-cache, must-revalidate"
        }
    )


# ============================================================
# REMOTE JSON COMMAND
# ============================================================

def remote_json_command(
    session_id,
    command
):

    session = token_valid(
        session_id
    )

    if not session:

        return jsonify({
            "ok": False,
            "error": "UNAUTHORIZED"
        }), 403

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    data.pop(
        "token",
        None
    )

    result = send_remote_command(
        session_id,
        session["token"],
        command,
        data
    )

    return jsonify(
        result
    )


# ============================================================
# REMOTE ROUTES
# ============================================================

@app.route(
    "/vip/<session_id>/click",
    methods=["POST"]
)
def remote_click(session_id):

    return remote_json_command(
        session_id,
        "click"
    )


@app.route(
    "/vip/<session_id>/wheel",
    methods=["POST"]
)
def remote_wheel(session_id):

    return remote_json_command(
        session_id,
        "wheel"
    )


@app.route(
    "/vip/<session_id>/key",
    methods=["POST"]
)
def remote_key(session_id):

    return remote_json_command(
        session_id,
        "key"
    )


@app.route(
    "/vip/<session_id>/type",
    methods=["POST"]
)
def remote_type(session_id):

    return remote_json_command(
        session_id,
        "type"
    )


@app.route(
    "/vip/<session_id>/reload",
    methods=["POST"]
)
def remote_reload(session_id):

    return remote_json_command(
        session_id,
        "reload"
    )


@app.route(
    "/vip/<session_id>/close",
    methods=["POST"]
)
def remote_close(session_id):

    return remote_json_command(
        session_id,
        "close"
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

        <title>
            Free Mobile VIP Bot
        </title>

    </head>

    <body
        style="
        font-family:Arial;
        text-align:center;
        padding:50px;
        "
    >

        <h2>
            🚀 Free Mobile VIP Bot
        </h2>

        <p>
            🟢 Bot يعمل
        </p>

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
            or
            clean.startswith("07")
        )
    ):

        return None

    d = clean[2:]

    if len(set(d)) <= 4:

        return (
            "تنوع منخفض للأرقام (مميز)"
        )

    if d == d[::-1]:

        return (
            "مرآة متناظرة كاملة (Palindrome)"
        )

    if d[:4] == d[4:]:

        return (
            "نصفين متطابقين تماماً"
        )

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

            return (
                "تسلسل أرقام متتالي"
            )

    if (
        len(set(d[-4:])) <= 2
        or
        len(set(d[:4])) <= 2
    ):

        return (
            "تكرار عالي في الأطراف"
        )

    if (
        d[0] == d[1] == d[2]
        or
        d[-3] == d[-2] == d[-1]
    ):

        return (
            "ثلاثية متتالية"
        )

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

        for i in range(
            radios.count()
        ):

            try:

                radio = radios.nth(i)

                value = (
                    radio.get_attribute(
                        "value"
                    )
                    or ""
                )

                radio_id = (
                    radio.get_attribute(
                        "id"
                    )
                    or ""
                )

                combined = (
                    value
                    + " "
                    + radio_id
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

                        radio.click(
                            force=True,
                            timeout=2000
                        )

                    selected = True

                    break

            except Exception:

                continue


        selects = page.locator(
            "select"
        )

        for i in range(
            selects.count()
        ):

            try:

                select = selects.nth(i)

                options = select.locator(
                    "option"
                )

                for j in range(
                    options.count()
                ):

                    try:

                        option = options.nth(j)

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
                            .replace(
                                " ",
                                ""
                            )
                            .replace(
                                "-",
                                ""
                            )
                        )

                        clean_text = (
                            text
                            .replace(
                                " ",
                                ""
                            )
                            .replace(
                                "-",
                                ""
                            )
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

                            selected = True

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
            "session_id":
                session_id,

            "number":
                safe_number,

            "created":
                int(time.time()),

            "state_file":
                state_file
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
            f"💾 [SESSION] تم حفظ جلسة {safe_number}",
            flush=True
        )

        return True

    except Exception as e:

        print(
            f"⚠️ [SESSION ERROR] {repr(e)}",
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
        f"{render_url}"
        f"/vip/{session_id}"
        f"?token={token}"
    )

    message = (
        "🔥 *رقم مميز VIP جديد!*\n\n"
        f"📱 الرقم: `{number}`\n"
        f"💎 التصنيف: {desc}\n\n"
        f"🖥️ [فتح Remote Browser]({open_url})"
    )

    if (
        not TELEGRAM_BOT_TOKEN
        or
        not CHAT_ID
    ):

        return

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}"
        "/sendMessage"
    )

    payload = {
        "chat_id":
            CHAT_ID,

        "text":
            message,

        "parse_mode":
            "Markdown",

        "disable_web_page_preview":
            True
    }

    try:

        requests.post(
            url,
            json=payload,
            timeout=10
        )

    except Exception as e:

        print(
            f"⚠️ [TELEGRAM ERROR] {repr(e)}",
            flush=True
        )


# ============================================================
# REMOTE SESSION
# ============================================================

def run_remote_session(
    page,
    session
):

    started = time.time()

    print(
        "🖥️ [REMOTE] جلسة Remote Browser بدأت - المدة 5 دقائق",
        flush=True
    )

    try:

        while True:

            process_remote_commands(
                page,
                session
            )

            if session.get(
                "closed"
            ):

                break

            # =================================================
            # 5 MINUTE TIMEOUT
            # =================================================

            if (
                time.time()
                - started
                >
                REMOTE_SESSION_TIMEOUT
            ):

                print(
                    "⏰ [REMOTE] انتهت جلسة Remote Browser بعد 5 دقائق",
                    flush=True
                )

                break

            try:

                _ = page.url

            except Exception:

                break

            time.sleep(
                0.08
            )

    except Exception:

        pass

    finally:

        session["closed"] = True

        remove_live_session(
            session["session_id"]
        )


# ============================================================
# GET NUMBERS
# ============================================================

def get_numbers(page):

    result = page.evaluate(
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

                    const text =
                        await res.text();

                    let data = null;

                    try {
                        data = JSON.parse(text);
                    }
                    catch(e) {}

                    if (!res.ok) {

                        lastError =
                            'HTTP '
                            + res.status
                            + ' URL='
                            + url;

                        if (
                            res.status === 404
                        ) {
                            continue;
                        }

                        return {
                            error:
                                lastError
                        };
                    }

                    return {
                        status:
                            res.status,

                        url:
                            url,

                        data:
                            data,

                        raw:
                            text.substring(
                                0,
                                1000
                            )
                    };

                }
                catch(e) {

                    lastError =
                        String(e);
                }
            }

            return {
                error:
                    lastError
                    ||
                    'API_REQUEST_FAILED'
            };
        }
        """
    )

    return result


# ============================================================
# SMART MONITOR
# ============================================================

def run_smart_monitor():

    print(
        "🔥🔥🔥 [THREAD ACTIVE] محرك الفحص بدأ",
        flush=True
    )

    os.environ[
        "PLAYWRIGHT_BROWSERS_PATH"
    ] = (
        "/opt/render/project/src/"
        "pw-browsers"
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

                        # =====================================
                        # PROXY REFRESH
                        # =====================================

                        if (
                            time.time()
                            -
                            proxy_refresh_time
                            >
                            600
                            or
                            not current_proxies
                        ):

                            current_proxies = (
                                fetch_fresh_proxies()
                            )

                            proxy_refresh_time = (
                                time.time()
                            )

                        proxy = None

                        if current_proxies:

                            proxy = random.choice(
                                current_proxies
                            )

                        launch_args = {

                            "headless":
                                True,

                            "args": [
                                "--no-sandbox",
                                "--disable-setuid-sandbox",
                                "--disable-dev-shm-usage"
                            ]
                        }

                        if proxy:

                            launch_args[
                                "proxy"
                            ] = {
                                "server":
                                    proxy
                            }

                        # =====================================
                        # LAUNCH
                        # =====================================

                        browser = p.chromium.launch(
                            **launch_args
                        )

                        context = (
                            browser.new_context(
                                user_agent=
                                    "Mozilla/5.0 "
                                    "(iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                                    "AppleWebKit/605.1.15 "
                                    "(KHTML, like Gecko) "
                                    "Version/16.0 "
                                    "Mobile/15E148 "
                                    "Safari/604.1",

                                viewport={
                                    "width":390,
                                    "height":844
                                },

                                locale="fr-FR"
                            )
                        )

                        page = (
                            context.new_page()
                        )

                        # =====================================
                        # OPEN FREE MOBILE
                        # =====================================

                        page.goto(
                            TARGET_URL,
                            wait_until=
                                "domcontentloaded",
                            timeout=25000
                        )

                        try:

                            page.mouse.move(
                                100,
                                100
                            )

                            page.mouse.down()

                            page.mouse.up()

                        except Exception:

                            pass

                        time.sleep(
                            2.0
                        )

                        # =====================================
                        # API
                        # =====================================

                        api_result = (
                            get_numbers(page)
                        )

                        if (
                            isinstance(
                                api_result,
                                dict
                            )
                            and
                            api_result.get(
                                "error"
                            )
                        ):

                            err = str(
                                api_result[
                                    "error"
                                ]
                            )

                            print(
                                f"⚠️ [API ERROR] "
                                f"{err} "
                                f"(البروكسي المستخدم: {proxy})",
                                flush=True
                            )

                            if (
                                proxy
                                and
                                proxy in current_proxies
                            ):

                                current_proxies.remove(
                                    proxy
                                )

                            if "429" in err:

                                time.sleep(
                                    random.uniform(
                                        5,
                                        10
                                    )
                                )

                            else:

                                time.sleep(
                                    random.uniform(
                                        3,
                                        6
                                    )
                                )

                        else:

                            status = (
                                api_result.get(
                                    "status"
                                )
                            )

                            data = (
                                api_result.get(
                                    "data"
                                )
                            )

                            raw = (
                                api_result.get(
                                    "raw",
                                    ""
                                )
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
                                f"📱 [API] "
                                f"HTTP={status} | "
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

                                number = (
                                    item.get(
                                        "value"
                                    )
                                    if isinstance(
                                        item,
                                        dict
                                    )
                                    else
                                    str(item)
                                )

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

                                token = (
                                    session[
                                        "token"
                                    ]
                                )

                                saved = (
                                    save_vip_session(
                                        context,
                                        number,
                                        session_id
                                    )
                                )

                                if saved:

                                    send_telegram_alert(
                                        number,
                                        desc,
                                        session_id,
                                        token
                                    )

                                    run_remote_session(
                                        page,
                                        session
                                    )

                                else:

                                    remove_live_session(
                                        session_id
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

            time.sleep(
                5
            )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    print(
        "🚀 [START] تشغيل Free Mobile VIP Bot",
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
