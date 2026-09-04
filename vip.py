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

REMOTE_SESSION_TIMEOUT = 20 * 60

MIN_DELAY = 2.5
MAX_DELAY = 4.5


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
        or {
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

            if command == "screen":

                image = page.screenshot(
                    type="jpeg",
                    quality=72
                )

                command_data["result"] = {
                    "ok": True,
                    "image": image
                }

            elif command == "click":

                x = float(
                    payload.get("x", 0)
                )

                y = float(
                    payload.get("y", 0)
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

            elif command == "dblclick":

                x = float(
                    payload.get("x", 0)
                )

                y = float(
                    payload.get("y", 0)
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

            elif command == "reload":

                page.reload(
                    wait_until="domcontentloaded",
                    timeout=25000
                )

                time.sleep(1)

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
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Free Mobile Remote Browser</title>
<style>
* {{ box-sizing:border-box; }}
body {{ margin:0; background:#0f172a; color:#fff; font-family:Arial,sans-serif; }}
.header {{ background:#1e293b; padding:14px; text-align:center; position:sticky; top:0; z-index:10; }}
.number {{ direction:ltr; color:#facc15; font-size:25px; font-weight:bold; margin-top:5px; }}
.status {{ margin-top:6px; color:#94a3b8; font-size:13px; }}
.viewer {{ padding:15px; display:flex; justify-content:center; }}
.screen-box {{ width:min(390px,100%); background:#000; border-radius:15px; overflow:hidden; box-shadow:0 10px 40px rgba(0,0,0,.5); }}
#screen {{ display:block; width:100%; height:auto; background:#000; user-select:none; -webkit-user-select:none; touch-action:none; }}
.controls {{ max-width:500px; margin:auto; padding:0 15px 30px; }}
.row {{ display:flex; gap:8px; margin-top:8px; }}
button {{ flex:1; border:0; border-radius:10px; padding:13px 8px; background:#334155; color:white; font-size:15px; }}
button:active {{ transform:scale(.97); }}
.green {{ background:#16a34a; }}
.red {{ background:#dc2626; }}
input {{ flex:1; min-width:0; border:0; border-radius:10px; padding:13px; font-size:16px; }}
</style>
</head>
<body>
<div class="header">
<div>🔥 Free Mobile Remote Browser</div>
<div class="number">{number}</div>
<div id="status" class="status">🟡 الاتصال...</div>
</div>
<div class="viewer">
<div class="screen-box">
<img id="screen" draggable="false" alt="Remote Browser">
</div>
</div>
<div class="controls">
<div class="row"><button onclick="sendKey('ArrowUp')">↑</button></div>
<div class="row"><button onclick="sendKey('ArrowLeft')">←</button><button class="green" onclick="sendKey('Enter')">ENTER</button><button onclick="sendKey('ArrowRight')">→</button></div>
<div class="row"><button onclick="sendKey('ArrowDown')">↓</button></div>
<div class="row"><input id="textInput" placeholder="اكتب نصاً..."><button class="green" onclick="sendText()">إرسال</button></div>
<div class="row"><button onclick="sendKey('Backspace')">⌫</button><button onclick="sendKey('Tab')">TAB</button><button onclick="sendKey('Escape')">ESC</button><button onclick="reloadPage()">🔄</button></div>
<div class="row"><button class="red" onclick="closeBrowser()">🛑 إغلاق المتصفح</button></div>
</div>
<script>
const SESSION_ID = {sid};
const TOKEN = {tok};
const BASE = window.location.origin + "/vip/" + encodeURIComponent(SESSION_ID);
const screen = document.getElementById("screen");
const status = document.getElementById("status");
let loading = false;

async function refreshScreen() {{
    if (loading) return;
    loading = true;
    try {{
        const response = await fetch(BASE + "/screen?token=" + encodeURIComponent(TOKEN) + "&t=" + Date.now(), {{ cache:"no-store" }});
        if (!response.ok) {{ status.innerText = "🔴 الجلسة غير متاحة"; loading = false; return; }}
        const blob = await response.blob();
        screen.src = URL.createObjectURL(blob);
        status.innerText = "🟢 Remote Browser متصل";
    }} catch(e) {{ status.innerText = "🔴 انقطع الاتصال"; }}
    loading = false;
}}

screen.addEventListener("pointerup", async function(event) {{
    event.preventDefault();
    const rect = screen.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    try {{
        await fetch(BASE + "/click", {{
            method:"POST",
            headers:{{"Content-Type": "application/json"}},
            body: JSON.stringify({{ token:TOKEN, x:x, y:y, display_width:rect.width, display_height:rect.height }})
        }});
    }} catch(e) {{}}
}});

screen.addEventListener("wheel", async function(event) {{
    event.preventDefault();
    try {{
        await fetch(BASE + "/wheel", {{
            method:"POST",
            headers:{{"Content-Type": "application/json"}},
            body: JSON.stringify({{ token:TOKEN, dx:event.deltaX, dy:event.deltaY }})
        }});
    }} catch(e) {{}}
}}, {{passive:false}});

async function sendKey(key) {{
    try {{
        await fetch(BASE + "/key", {{
            method:"POST",
            headers:{{"Content-Type": "application/json"}},
            body: JSON.stringify({{ token:TOKEN, key:key }})
        }});
    }} catch(e) {{}}
}}

async function sendText() {{
    const input = document.getElementById("textInput");
    const text = input.value;
    if (!text) return;
    try {{
        await fetch(BASE + "/type", {{
            method:"POST",
            headers:{{"Content-Type": "application/json"}},
            body: JSON.stringify({{ token:TOKEN, text:text }})
        }});
        input.value = "";
    }} catch(e) {{}}
}}

async function reloadPage() {{
    status.innerText = "🔄 إعادة تحميل...";
    try {{
        await fetch(BASE + "/reload", {{
            method:"POST",
            headers:{{"Content-Type": "application/json"}},
            body: JSON.stringify({{ token:TOKEN }})
        }});
    }} catch(e) {{}}
}}

async function closeBrowser() {{
    if (!confirm("هل تريد إغلاق المتصفح؟")) return;
    try {{
        await fetch(BASE + "/close", {{
            method:"POST",
            headers:{{"Content-Type": "application/json"}},
            body: JSON.stringify({{ token:TOKEN }})
        }});
        status.innerText = "🔴 تم إغلاق المتصفح";
    }} catch(e) {{}}
}}

refreshScreen();
setInterval(refreshScreen, 700);
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
    session = token_valid(session_id)
    if not session:
        return "Unauthorized", 403

    result = send_remote_command(
        session_id,
        session["token"],
        "screen",
        timeout=8
    )

    if not result.get("ok"):
        return result.get("error", "SCREEN_ERROR"), 500

    return Response(
        result["image"],
        mimetype="image/jpeg",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate"
        }
    )


def remote_json_command(session_id, command):
    session = token_valid(session_id)
    if not session:
        return jsonify({"ok": False, "error": "UNAUTHORIZED"}), 403

    data = request.get_json(silent=True) or {}
    data.pop("token", None)

    result = send_remote_command(
        session_id,
        session["token"],
        command,
        data
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


@app.route("/")
def home():
    return """
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head><meta charset="UTF-8"><title>Free Mobile VIP Bot</title></head>
    <body style="font-family:Arial;text-align:center;padding:50px;">
    <h2>🚀 Free Mobile VIP Bot</h2>
    <p>🟢 Bot يعمل</p>
    </body>
    </html>
    """


# ============================================================
# VIP DETECTOR
# ============================================================

def evaluate_vip_expanded(num):
    clean = str(num).replace(" ", "").replace("-", "").strip()
    if not (len(clean) == 10 and (clean.startswith("06") or clean.startswith("07"))):
        return None

    d = clean[2:]

    if len(set(d)) <= 4:
        return "تنوع منخفض للأرقام (مميز)"
    if d == d[::-1]:
        return "مرآة متناظرة كاملة (Palindrome)"
    if d[:4] == d[4:]:
        return "نصفين متطابقين تماماً"

    sequences = ["0123", "1234", "2345", "3456", "4567", "5678", "6789", "9876", "8765", "7654", "6543", "5432", "4321", "3210"]
    for seq in sequences:
        if seq in d:
            return "تسلسل أرقام متتالي"

    if len(set(d[-4:])) <= 2 or len(set(d[:4])) <= 2:
        return "تكرار عالي في الأطراف"

    if d[0] == d[1] == d[2] or d[-3] == d[-2] == d[-1]:
        return "ثلاثية متتالية"

    return None


# ============================================================
# SELECT NUMBER
# ============================================================

def select_number(page, number):
    target = str(number).replace(" ", "").replace("-", "").strip()
    selected = False
    try:
        radios = page.locator('input[type="radio"]')
        for i in range(radios.count()):
            try:
                radio = radios.nth(i)
                value = radio.get_attribute("value") or ""
                radio_id = radio.get_attribute("id") or ""
                combined = (value + " " + radio_id).lower()
                if "new" in combined or "nouveau" in combined:
                    try:
                        radio.check(force=True, timeout=2000)
                    except Exception:
                        radio.click(force=True, timeout=2000)
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
                        value = option.get_attribute("value") or ""
                        text = option.inner_text() or ""
                        if target in value.replace(" ", "").replace("-", "") or target in text.replace(" ", "").replace("-", ""):
                            select.select_option(value=value, timeout=2000)
                            selected = True
                            print(f"🎯 [SELECT] تم اختيار {number}", flush=True)
                            return True
                    except Exception:
                        continue
            except Exception:
                continue
    except Exception as e:
        print(f"⚠️ [SELECT ERROR] {repr(e)}", flush=True)
    return selected


def save_vip_session(context, number, session_id):
    safe_number = "".join(c for c in str(number) if c.isdigit())
    state_file = os.path.join(SESSION_DIR, f"{session_id}.json")
    meta_file = os.path.join(SESSION_DIR, f"{session_id}.meta.json")
    try:
        context.storage_state(path=state_file, indexed_db=True)
        metadata = {
            "session_id": session_id,
            "number": safe_number,
            "created": int(time.time()),
            "state_file": state_file
        }
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        print(f"💾 [SESSION] تم حفظ جلسة {safe_number}", flush=True)
        return True
    except Exception as e:
        print(f"⚠️ [SESSION ERROR] {repr(e)}", flush=True)
        return False


def send_telegram_alert(number, desc, session_id, token):
    render_url = os.environ.get(
        "RENDER_EXTERNAL_URL",
        "https://freemobile-bot.onrender.com"
    ).rstrip("/")

    open_url = f"{render_url}/vip/{session_id}?token={token}"
    message = (
        "🔥 *رقم مميز VIP جديد!*\n\n"
        f"📱 الرقم: `{number}`\n"
        f"💎 التصنيف: {desc}\n\n"
        f"🖥️ [فتح Remote Browser]({open_url})"
    )

    if not TELEGRAM_BOT_TOKEN or not CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"⚠️ [TELEGRAM ERROR] {repr(e)}", flush=True)


def run_remote_session(page, session):
    started = time.time()
    try:
        while True:
            process_remote_commands(page, session)
            if session.get("closed"):
                break
            if time.time() - started > REMOTE_SESSION_TIMEOUT:
                break
            try:
                _ = page.url
            except Exception:
                break
            time.sleep(0.08)
    except Exception:
        pass
    finally:
        session["closed"] = True
        remove_live_session(session["session_id"])


# ============================================================
# GET NUMBERS (محسنة لتجنب 0 أرقام)
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
                    const res = await fetch(url, {
                        method: 'GET',
                        credentials: 'include',
                        headers: {
                            'X-Requested-With': 'XMLHttpRequest',
                            'Cache-Control': 'no-cache'
                        }
                    });
                    const text = await res.text();
                    let data = null;
                    try { data = JSON.parse(text); } catch(e) {}
                    if (!res.ok) {
                        lastError = 'HTTP ' + res.status + ' URL=' + url;
                        if (res.status === 404) { continue; }
                        return { error: lastError };
                    }
                    return { status: res.status, url: url, data: data, raw: text.substring(0, 1000) };
                } catch(e) { lastError = String(e); }
            }
            return { error: lastError || 'API_REQUEST_FAILED' };
        }
        """
    )
    return result


# ============================================================
# MONITOR
# ============================================================

def run_smart_monitor():
    print("🔥🔥🔥 [THREAD ACTIVE] محرك الفحص بدأ", flush=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/opt/render/project/src/pw-browsers"

    while True:
        browser = None
        try:
            with sync_playwright() as p:
                while True:
                    browser = None
                    context = None
                    page = None
                    try:
                        proxy = None
                        proxies_env = os.environ.get("PROXIES_LIST", "")
                        proxy_list = [x.strip() for x in proxies_env.split(",") if x.strip()]
                        if proxy_list:
                            proxy = proxy_list[0]

                        launch_args = {
                            "headless": True,
                            "args": ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
                        }
                        if proxy:
                            launch_args["proxy"] = {"server": proxy}

                        browser = p.chromium.launch(**launch_args)
                        context = browser.new_context(
                            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
                            viewport={"width": 390, "height": 844},
                            locale="fr-FR"
                        )
                        page = context.new_page()

                        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=25000)
                        
                        # محاكاة حركة خفيفة للماوس لتفادي كشف الـ Bot وجلب الأرقام بشكل صحيح
                        try:
                            page.mouse.move(100, 100)
                            page.mouse.down()
                            page.mouse.up()
                        except Exception:
                            pass

                        time.sleep(2.0)

                        api_result = get_numbers(page)

                        if isinstance(api_result, dict) and api_result.get("error"):
                            err = str(api_result["error"])
                            print(f"⚠️ [API ERROR] {err}", flush=True)
                            if "429" in err:
                                time.sleep(random.uniform(15, 30))
                            else:
                                time.sleep(random.uniform(5, 10))
                        else:
                            status = api_result.get("status")
                            data = api_result.get("data")
                            raw = api_result.get("raw", "")

                            numbers_list = []
                            if isinstance(data, list):
                                numbers_list = data
                            elif isinstance(data, dict):
                                numbers_list = data.get("msisdns", [])

                            print(f"📱 [API] HTTP={status} | عدد الأرقام: {len(numbers_list)}", flush=True)

                            if not numbers_list and raw:
                                print(f"📄 [API RAW] {raw[:300]}", flush=True)

                            found = False
                            for item in numbers_list:
                                number = item.get("value") if isinstance(item, dict) else str(item)
                                if not number:
                                    continue

                                desc = evaluate_vip_expanded(number)
                                if not desc:
                                    continue

                                found = True
                                print(f"🔥🔥🔥 VIP FOUND: {number}", flush=True)

                                select_number(page, number)
                                session = create_live_session(number)
                                session_id = session["session_id"]
                                token = session["token"]

                                saved = save_vip_session(context, number, session_id)
                                if saved:
                                    send_telegram_alert(number, desc, session_id, token)
                                    run_remote_session(page, session)
                                else:
                                    remove_live_session(session_id)
                                break

                            if not found:
                                print("🔍 [MONITOR] لا يوجد VIP هذه المرة", flush=True)

                    except Exception as e:
                        print(f"⚠️ [LOOP ERROR] {repr(e)}", flush=True)
                    finally:
                        if browser:
                            try:
                                browser.close()
                            except Exception:
                                pass

                    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

        except Exception as e:
            print(f"❌ [PLAYWRIGHT ERROR] {repr(e)}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    print("🚀 [START] تشغيل Free Mobile VIP Bot", flush=True)
    monitor_thread = threading.Thread(target=run_smart_monitor, daemon=True)
    monitor_thread.start()
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
