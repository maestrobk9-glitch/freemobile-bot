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

REMOTE_SESSION_TIMEOUT = 20 * 60

# تم إرجاع السرعة كما كانت في الكود الأصلي الخاص بك
MIN_DELAY = 2.5
MAX_DELAY = 4.5

# نظام تدوير البروكسيات لتغيير الـ IP عند حدوث خطأ 429
CURRENT_PROXY_INDEX = 0

def get_next_working_proxy():
    global CURRENT_PROXY_INDEX
    proxies_env = os.environ.get("PROXIES_LIST", "")
    proxy_list = [p.strip() for p in proxies_env.split(",") if p.strip()]
    if not proxy_list:
        return None
    proxy = proxy_list[CURRENT_PROXY_INDEX % len(proxy_list)]
    CURRENT_PROXY_INDEX += 1
    return proxy


# ============================================================
# REMOTE SESSION STORAGE & COMMAND SYSTEM
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
    if not session: return None
    supplied = request.args.get("token") or (request.get_json(silent=True) or {}).get("token") or request.form.get("token")
    if not supplied or not secrets.compare_digest(str(supplied), str(session["token"])):
        return None
    return session

def send_remote_command(session_id, token, command, payload=None, timeout=10):
    session = get_live_session(session_id)
    if not session or not secrets.compare_digest(str(token), str(session["token"])):
        return {"ok": False, "error": "UNAUTHORIZED"}
    event = threading.Event()
    cmd_data = {"command": command, "payload": payload or {}, "event": event, "result": None}
    session["queue"].put(cmd_data)
    if not event.wait(timeout): return {"ok": False, "error": "TIMEOUT"}
    return cmd_data.get("result", {"ok": False, "error": "NO_RESULT"})

def process_remote_commands(page, session):
    processed = 0
    while processed < 10:
        try:
            cmd = session["queue"].get_nowait()
        except queue.Empty:
            break
        processed += 1
        command, payload = cmd["command"], cmd.get("payload", {})
        try:
            if command == "screen":
                cmd["result"] = {"ok": True, "image": page.screenshot(type="jpeg", quality=70)}
            elif command == "click":
                x, y = float(payload.get("x", 0)), float(payload.get("y", 0))
                vw = page.viewport_size or {"width": 390, "height": 844}
                page.mouse.click(x * vw["width"] / float(payload.get("display_width", 390)), y * vw["height"] / float(payload.get("display_height", 844)))
                cmd["result"] = {"ok": True}
            elif command == "wheel":
                page.mouse.wheel(float(payload.get("dx", 0)), float(payload.get("dy", 0)))
                cmd["result"] = {"ok": True}
            elif command == "type":
                text = str(payload.get("text", ""))
                if text: page.keyboard.insert_text(text)
                cmd["result"] = {"ok": True}
            elif command == "key":
                page.keyboard.press(str(payload.get("key", "")))
                cmd["result"] = {"ok": True}
            elif command == "reload":
                page.reload(wait_until="domcontentloaded", timeout=25000)
                cmd["result"] = {"ok": True}
            elif command == "close":
                session["closed"] = True
                cmd["result"] = {"ok": True}
            else:
                cmd["result"] = {"ok": False, "error": "UNKNOWN"}
        except Exception as e:
            cmd["result"] = {"ok": False, "error": repr(e)}
        finally:
            cmd["event"].set()


# ============================================================
# FLASK WEB ROUTES
# ============================================================

@app.route("/vip/<session_id>")
def view_vip_session(session_id):
    session = get_live_session(session_id)
    if not session: return "الجلسة غير موجودة", 404
    token = request.args.get("token", "")
    if not secrets.compare_digest(token, session["token"]): return "غير مرخص", 403
    return f"<h2>Remote Browser للرقم: {session['number']}</h2>"

@app.route("/")
def home():
    return "Bot is running."


# ============================================================
# SMART MONITOR (مع دعم تدوير البروكسي عند ظهور 429)
# ============================================================

def evaluate_vip_expanded(num):
    clean = str(num).replace(" ", "").replace("-", "").strip()
    if not (len(clean) == 10 and (clean.startswith("06") or clean.startswith("07"))):
        return None
    d = clean[2:]
    if len(set(d)) <= 4: return "تنوع منخفض للأرقام (مميز)"
    if d == d[::-1]: return "مرآة متناظرة كاملة (Palindrome)"
    if d[:4] == d[4:]: return "نصفين متطابقين تماماً"
    return None

def run_smart_monitor():
    print("🔥🔥🔥 [THREAD ACTIVE] محرك الفحص بدأ", flush=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/opt/render/project/src/pw-browsers"

    while True:
        browser = None
        try:
            with sync_playwright() as p:
                while True:
                    current_proxy = get_next_working_proxy()
                    launch_args = {
                        "headless": True,
                        "args": ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
                    }
                    if current_proxy:
                        launch_args["proxy"] = {"server": current_proxy}
                        print(f"🔄 [PROXY] استخدام بروكسي جديد: {current_proxy}", flush=True)

                    try:
                        browser = p.chromium.launch(**launch_args)
                        context = browser.new_context(
                            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
                            viewport={"width": 390, "height": 844},
                            locale="fr-FR"
                        )
                        page = context.new_page()
                        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=25000)
                        time.sleep(1.5)

                        numbers_data = page.evaluate("""
                            async () => {
                                try {
                                    const res = await fetch('./api/msisdns?' + Date.now(), {
                                        headers: { 'X-Requested-With': 'XMLHttpRequest', 'Cache-Control': 'no-cache' }
                                    });
                                    if (!res.ok) return { __error: 'HTTP ' + res.status };
                                    return await res.json();
                                } catch (e) { return { __error: String(e) }; }
                            }
                        """)

                        if isinstance(numbers_data, dict) and numbers_data.get("__error__"):
                            err_msg = str(numbers_data.get("__error__"))
                            print(f"⚠️ [API] {err_msg}", flush=True)
                            if "429" in err_msg:
                                print("🚨 [429 BLOCKED] تم رصد حظر، تغيير البروكسي فورا...", flush=True)
                                break  # كسر الحلقة الحالية لتغيير الـ IP فوراً في المحاولة القادمة
                        else:
                            numbers_list = numbers_data if isinstance(numbers_data, list) else numbers_data.get("msisdns", [])
                            print(f"📱 [API] عدد الأرقام: {len(numbers_list)}", flush=True)
                            
                            for item in numbers_list:
                                num_val = item.get("value") if isinstance(item, dict) else str(item)
                                if not num_val: continue
                                vip_desc = evaluate_vip_expanded(num_val)
                                if vip_desc:
                                    print(f"🔥🔥🔥 VIP FOUND: {num_val}", flush=True)
                                    break

                    except Exception as loop_err:
                        print(f"⚠️ [LOOP ERROR] {repr(loop_err)}", flush=True)
                        break
                    finally:
                        if browser:
                            try: browser.close()
                            except: pass

                    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

        except Exception as e:
            print(f"❌ [PLAYWRIGHT ERROR] {repr(e)}", flush=True)
            time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_smart_monitor, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), threaded=True)
