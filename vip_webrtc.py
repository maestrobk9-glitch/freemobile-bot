import os

# IMPORTANT: Render was previously pointing Playwright at /opt/render/project/src/pw-browsers.
# Force the official Playwright Docker browser directory before importing Playwright.
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/ms-playwright"
os.environ.setdefault("PLAYWRIGHT_SKIP_BROWSER_GC", "1")
os.environ.setdefault("DISPLAY", ":99")

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
import asyncio

from flask import Flask, make_response, request, Response, jsonify
from playwright.sync_api import sync_playwright

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc.mediastreams import MediaStreamTrack
from av import VideoFrame
import mss
import numpy as np

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
TARGET_URL = "https://mobile.free.fr/souscription/options"
REMOTE_SESSION_TIMEOUT = 5 * 60
MIN_DELAY = 2.5
MAX_DELAY = 4.5
VIDEO_FPS = int(os.environ.get("VIDEO_FPS", "24"))
DISPLAY_WIDTH = 390
DISPLAY_HEIGHT = 844
LIVE_SESSIONS = {}
LIVE_SESSIONS_LOCK = threading.Lock()

# WebRTC needs a real media path. On Render, public HTTP/WebSocket traffic is
# proxied to the single web port, so a TURN server is strongly recommended.
# Set TURN_URL, TURN_USERNAME and TURN_CREDENTIAL in Render for reliable
# connections from iPhone networks.
TURN_URL = os.environ.get("TURN_URL", "").strip()
TURN_USERNAME = os.environ.get("TURN_USERNAME", "").strip()
TURN_CREDENTIAL = os.environ.get("TURN_CREDENTIAL", "").strip()

RTC_LOOP = asyncio.new_event_loop()
RTC_THREAD = None
RTC_PEERS = set()
RTC_PEERS_LOCK = threading.Lock()


def start_rtc_loop():
    global RTC_THREAD
    def runner():
        asyncio.set_event_loop(RTC_LOOP)
        print("🟢 [WEBRTC] event loop started", flush=True)
        RTC_LOOP.run_forever()
    RTC_THREAD = threading.Thread(target=runner, daemon=True, name="webrtc-loop")
    RTC_THREAD.start()


def rtc_call(coro, timeout=20):
    future = asyncio.run_coroutine_threadsafe(coro, RTC_LOOP)
    return future.result(timeout=timeout)


def rtc_configuration():
    servers = []
    if TURN_URL:
        servers.append(RTCIceServer(
            urls=[TURN_URL],
            username=TURN_USERNAME or None,
            credential=TURN_CREDENTIAL or None,
        ))
    # STUN helps discover public candidates, but it is not a TURN relay.
    servers.append(RTCIceServer(urls=["stun:stun.l.google.com:19302"]))
    return RTCConfiguration(iceServers=servers)


class ScreenTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, session):
        super().__init__()
        self.session = session
        self.sct = mss.mss()
        self.monitor = {
            "left": 0,
            "top": 0,
            "width": DISPLAY_WIDTH,
            "height": DISPLAY_HEIGHT,
        }

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        if self.session.get("closed"):
            self.stop()
            raise asyncio.CancelledError
        try:
            shot = self.sct.grab(self.monitor)
            # MSS returns BGRA. Drop alpha and convert to RGB for PyAV.
            rgb = np.asarray(shot, dtype=np.uint8)[..., :3][:, :, ::-1]
            frame = VideoFrame.from_ndarray(rgb, format="rgb24")
            frame.pts = pts
            frame.time_base = time_base
            return frame
        except Exception as e:
            print(f"⚠️ [WEBRTC SCREEN] {repr(e)}", flush=True)
            await asyncio.sleep(0.05)
            raise

    def stop(self):
        try:
            self.sct.close()
        except Exception:
            pass
        super().stop()


def fetch_fresh_proxies():
    try:
        res = requests.get(
            "https://api.geonode.com/proxies?limit=10&format=json&country=FR&protocols=http",
            timeout=10,
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
                print(f"🌐 [PROXY] تم جلب {len(proxies)} بروكسي فرنسي", flush=True)
                return proxies
    except Exception as e:
        print(f"⚠️ [PROXY FETCH ERROR] {repr(e)}", flush=True)
    return []


def create_live_session(number):
    session_id = uuid.uuid4().hex
    data = {
        "session_id": session_id,
        "token": secrets.token_urlsafe(32),
        "number": str(number),
        "created": time.time(),
        "queue": queue.Queue(maxsize=100),
        "closed": False,
        "rtc_channel": None,
        "rtc_peer": None,
        "rtc_connected": False,
        "keyboard_ready": False,
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


def token_matches(session, supplied):
    if not session or not supplied:
        return False
    try:
        return secrets.compare_digest(str(supplied), str(session["token"]))
    except Exception:
        return False


def token_valid(session_id):
    session = get_live_session(session_id)
    supplied = request.args.get("token") or request.form.get("token")
    if not supplied:
        try:
            supplied = (request.get_json(silent=True) or {}).get("token")
        except Exception:
            supplied = None
    return session if token_matches(session, supplied) else None


def queue_remote_command(session, command, payload=None):
    if not session or session.get("closed"):
        return False
    item = {
        "command": command,
        "payload": payload or {},
        "event": threading.Event(),
        "result": None,
    }
    try:
        session["queue"].put_nowait(item)
        return True
    except queue.Full:
        return False


def send_rtc_json(session, obj):
    channel = session.get("rtc_channel") if session else None
    if not channel:
        return
    try:
        if getattr(channel, "readyState", "") == "open":
            channel.send(json.dumps(obj, ensure_ascii=False))
    except Exception:
        pass


def process_remote_commands(page, session):
    processed = 0
    while processed < 30:
        try:
            command_data = session["queue"].get_nowait()
        except queue.Empty:
            break
        processed += 1
        command = command_data["command"]
        payload = command_data.get("payload") or {}
        try:
            if command == "click":
                x, y = coords_from_payload(page, payload)
                page.mouse.click(x, y)
                try:
                    focus = page.evaluate("""() => {
                        const e=document.activeElement;
                        if(!e) return {editable:false,type:'',tag:''};
                        const tag=(e.tagName||'').toLowerCase();
                        const type=(e.getAttribute('type')||'').toLowerCase();
                        const editable=!!(e.isContentEditable || tag==='textarea' || (tag==='input' && !['button','checkbox','radio','submit','file','hidden'].includes(type)));
                        return {editable,type,tag};
                    }""")
                    ready = bool(focus.get("editable"))
                    session["keyboard_ready"] = ready
                    send_rtc_json(session, {
                        "type": "keyboard",
                        "editable": ready,
                        "inputMode": "numeric" if focus.get("type") in ("number", "tel") else "text",
                    })
                except Exception:
                    session["keyboard_ready"] = False
                result = {"ok": True}
            elif command == "dblclick":
                x, y = coords_from_payload(page, payload)
                page.mouse.dblclick(x, y)
                result = {"ok": True}
            elif command == "wheel":
                page.mouse.wheel(float(payload.get("dx") or 0), float(payload.get("dy") or 0))
                result = {"ok": True}
            elif command == "type":
                text = str(payload.get("text") or "")
                if text:
                    page.keyboard.insert_text(text)
                result = {"ok": True}
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
                    page.keyboard.press("+".join(modifiers + [key]))
                result = {"ok": True}
            elif command == "reload":
                page.reload(wait_until="domcontentloaded", timeout=25000)
                result = {"ok": True}
            elif command == "close":
                session["closed"] = True
                result = {"ok": True}
            else:
                result = {"ok": False, "error": "UNKNOWN_COMMAND"}
        except Exception as e:
            result = {"ok": False, "error": repr(e)}
        command_data["result"] = result
        command_data["event"].set()


def coords_from_payload(page, payload):
    viewport = page.viewport_size or {"width": DISPLAY_WIDTH, "height": DISPLAY_HEIGHT}
    display_width = float(payload.get("display_width") or DISPLAY_WIDTH)
    display_height = float(payload.get("display_height") or DISPLAY_HEIGHT)
    x = float(payload.get("x") or 0)
    y = float(payload.get("y") or 0)
    if display_width <= 0:
        display_width = DISPLAY_WIDTH
    if display_height <= 0:
        display_height = DISPLAY_HEIGHT
    real_x = x * viewport["width"] / display_width
    real_y = y * viewport["height"] / display_height
    return (
        max(0, min(real_x, viewport["width"] - 1)),
        max(0, min(real_y, viewport["height"] - 1)),
    )


def remote_html(session_id, token, number):
    safe_number = html.escape(str(number))
    page_html = r'''<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,viewport-fit=cover">
<title>Free Mobile — WebRTC</title>
<style>
*{box-sizing:border-box}html,body{margin:0;padding:0;background:#0b1220;color:#fff;font-family:Arial,sans-serif}
.header{background:#1e293b;padding:10px;text-align:center;position:sticky;top:0;z-index:5}.number{direction:ltr;color:#38bdf8;font-size:23px;font-weight:700}.status{margin-top:4px;color:#a8b3c7;font-size:13px}
.viewer{padding:8px;display:flex;justify-content:center}.screen-box{width:min(390px,100%);background:#000;border-radius:10px;overflow:hidden;box-shadow:0 5px 22px #0008;position:relative}
#video{display:block;width:100%;height:auto;user-select:none;-webkit-user-select:none;touch-action:none;background:#000}
#keyboardSink{position:fixed;left:50%;bottom:2px;width:2px;height:2px;opacity:.02;border:0;padding:0;margin:0;z-index:1000;background:transparent;color:transparent;font-size:16px;-webkit-appearance:none}
.controls{max-width:500px;margin:auto;padding:0 8px 18px}.row{display:flex;gap:6px;margin-top:6px}button{flex:1;border:0;border-radius:8px;padding:10px 6px;background:#334155;color:#fff;font-size:14px}button:active{transform:scale(.98)}.green{background:#16a34a}.red{background:#dc2626}.blue{background:#2563eb}input{flex:1;min-width:0;border:0;border-radius:8px;padding:10px;font-size:16px}
</style></head>
<body>
<div class="header"><div>⚡ Free Mobile — WebRTC Remote</div><div class="number">__NUMBER__</div><div id="status" class="status">🟡 إنشاء اتصال منخفض التأخير...</div></div>
<div class="viewer"><div class="screen-box"><video id="video" autoplay playsinline muted></video></div></div>
<input id="keyboardSink" type="text" inputmode="text" autocomplete="off" autocorrect="off" autocapitalize="none" spellcheck="false" aria-label="Keyboard">
<div class="controls">
<div class="row"><button class="blue" onclick="wheel(0,-650)">⬆️ Scroll</button><button class="blue" onclick="wheel(0,650)">⬇️ Scroll</button></div>
<div class="row"><input id="textInput" placeholder="اكتب نصاً..."><button class="green" onclick="sendText()">إرسال</button></div>
<div class="row"><button onclick="key('Backspace')">⌫</button><button onclick="key('Tab')">TAB</button><button onclick="key('Escape')">ESC</button><button onclick="reloadPage()">🔄</button></div>
<div class="row"><button class="red" onclick="closeBrowser()">🛑 إغلاق</button></div>
</div>
<script>
const SID=__SID_JSON__, TOKEN=__TOKEN_JSON__;
const video=document.getElementById('video'),status=document.getElementById('status'),keyboardSink=document.getElementById('keyboardSink');
let pc=null,dc=null,pointer=null,moved=false,reconnectTimer=null;
function send(o){if(dc&&dc.readyState==='open')dc.send(JSON.stringify(o));}
function focusKeyboard(){keyboardSink.value='';try{keyboardSink.focus({preventScroll:true})}catch(_){keyboardSink.focus()}}
async function connect(){
  if(pc){try{pc.close()}catch(_){}pc=null}
  status.textContent='🟡 WebRTC: جاري الاتصال...';
  pc=new RTCPeerConnection({iceServers:[{urls:'stun:stun.l.google.com:19302'}]});
  pc.addTransceiver('video',{direction:'recvonly'});
  dc=pc.createDataChannel('input',{ordered:true});
  dc.onopen=()=>{status.textContent='🟢 WebRTC متصل — تفاعل مباشر';send({command:'ping'})};
  dc.onclose=()=>{status.textContent='🟠 قناة الإدخال أُغلقت'};
  dc.onmessage=e=>{try{const m=JSON.parse(e.data);if(m.type==='keyboard'&&m.editable){keyboardSink.inputMode=m.inputMode||'text';focusKeyboard();}if(m.type==='status')status.textContent=m.text;}catch(_){}};
  pc.ontrack=e=>{video.srcObject=e.streams[0];video.play().catch(()=>{})};
  pc.onconnectionstatechange=()=>{if(['failed','disconnected','closed'].includes(pc.connectionState)){status.textContent='🔴 انقطع الاتصال — إعادة المحاولة';clearTimeout(reconnectTimer);reconnectTimer=setTimeout(connect,1500)}};
  const offer=await pc.createOffer();await pc.setLocalDescription(offer);
  await new Promise(resolve=>{if(pc.iceGatheringState==='complete')return resolve();const f=()=>{if(pc.iceGatheringState==='complete'){pc.removeEventListener('icegatheringstatechange',f);resolve()}};pc.addEventListener('icegatheringstatechange',f);setTimeout(resolve,5000)});
  const r=await fetch('/rtc/'+encodeURIComponent(SID)+'/offer?token='+encodeURIComponent(TOKEN),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:pc.localDescription.type,sdp:pc.localDescription.sdp})});
  if(!r.ok)throw new Error('offer HTTP '+r.status);const ans=await r.json();await pc.setRemoteDescription(ans);
}
function coords(e){const r=video.getBoundingClientRect();return{x:e.clientX-r.left,y:e.clientY-r.top,display_width:r.width,display_height:r.height}}
video.addEventListener('pointerdown',e=>{e.preventDefault();pointer={x:e.clientX,y:e.clientY,t:Date.now()};moved=false});
video.addEventListener('pointermove',e=>{if(pointer&&(Math.abs(e.clientX-pointer.x)>8||Math.abs(e.clientY-pointer.y)>8))moved=true});
video.addEventListener('pointerup',e=>{if(!pointer)return;e.preventDefault();const p=pointer;pointer=null;const dx=e.clientX-p.x,dy=e.clientY-p.y;if(moved){send({command:'wheel',dx:0,dy:-dy*2.2});return}send({command:'click',...coords(e)});});
video.addEventListener('dblclick',e=>{e.preventDefault();send({command:'dblclick',...coords(e)})});
video.addEventListener('pointercancel',()=>pointer=null);
keyboardSink.addEventListener('beforeinput',e=>{if(e.inputType==='deleteContentBackward'){e.preventDefault();send({command:'key',key:'Backspace'});return}if(e.inputType==='deleteContentForward'){e.preventDefault();send({command:'key',key:'Delete'});return}if(e.inputType==='insertLineBreak'){e.preventDefault();send({command:'key',key:'Enter'});return}if(e.inputType==='insertText'&&e.data){e.preventDefault();send({command:'type',text:e.data});keyboardSink.value=''}});
keyboardSink.addEventListener('input',()=>{const v=keyboardSink.value;if(v){send({command:'type',text:v});keyboardSink.value=''}});
keyboardSink.addEventListener('keydown',e=>{const special=['Backspace','Delete','Tab','Enter','Escape','ArrowUp','ArrowDown','ArrowLeft','ArrowRight'];if(special.includes(e.key)){e.preventDefault();send({command:'key',key:e.key})}});
function wheel(dx,dy){send({command:'wheel',dx,dy})}function key(k){send({command:'key',key:k});focusKeyboard()}function sendText(){const i=document.getElementById('textInput'),t=i.value;if(!t)return;send({command:'type',text:t});i.value='';focusKeyboard()}function reloadPage(){status.textContent='🔄 إعادة تحميل...';send({command:'reload'})}function closeBrowser(){if(confirm('هل تريد إغلاق الجلسة؟'))send({command:'close'})}
connect().catch(e=>{status.textContent='🔴 تعذر إنشاء WebRTC';setTimeout(connect,2000)});
</script></body></html>'''
    return (page_html.replace('__NUMBER__', safe_number)
            .replace('__SID_JSON__', json.dumps(session_id))
            .replace('__TOKEN_JSON__', json.dumps(token)))


@app.route('/vip/<session_id>')
def remote_page(session_id):
    session = get_live_session(session_id)
    token = request.args.get('token', '')
    if not session:
        return '<h2 style="font-family:Arial;text-align:center">⚠️ انتهت الجلسة</h2>', 404
    if not token_matches(session, token):
        return '<h2 style="font-family:Arial;text-align:center">🔒 رابط غير صالح</h2>', 403
    response = make_response(remote_html(session_id, token, session['number']))
    response.set_cookie('vip_active_session', session_id, max_age=REMOTE_SESSION_TIMEOUT, httponly=True, samesite='Lax')
    return response


async def handle_rtc_offer(session, offer_sdp, offer_type):
    pc = RTCPeerConnection(configuration=rtc_configuration())
    track = ScreenTrack(session)
    session['rtc_peer'] = pc
    session['rtc_track'] = track
    with RTC_PEERS_LOCK:
        RTC_PEERS.add(pc)

    @pc.on("datachannel")
    def on_datachannel(channel):
        # The browser creates the channel; the server receives it here.
        session['rtc_channel'] = channel
        session['rtc_connected'] = True
        send_rtc_json(session, {'type': 'status', 'text': '🟢 WebRTC متصل — تفاعل مباشر'})

        @channel.on("message")
        def on_message(message):
            try:
                if isinstance(message, bytes):
                    message = message.decode('utf-8', 'ignore')
                obj = json.loads(message)
                command = str(obj.get('command') or '')
                if command not in {'click', 'dblclick', 'wheel', 'type', 'key', 'reload', 'close', 'ping'}:
                    return
                if command == 'ping':
                    send_rtc_json(session, {'type': 'status', 'text': '🟢 WebRTC متصل — تفاعل مباشر'})
                    return
                obj.pop('command', None)
                queue_remote_command(session, command, obj)
            except Exception:
                pass

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        state = pc.connectionState
        if state in ('failed', 'closed', 'disconnected'):
            session['rtc_connected'] = False
        if state == 'closed':
            try:
                track.stop()
            except Exception:
                pass
            with RTC_PEERS_LOCK:
                RTC_PEERS.discard(pc)

    offer = RTCSessionDescription(sdp=offer_sdp, type=offer_type)
    await pc.setRemoteDescription(offer)
    pc.addTrack(track)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return {'sdp': pc.localDescription.sdp, 'type': pc.localDescription.type}


@app.route('/rtc/<session_id>/offer', methods=['POST'])
def rtc_offer(session_id):
    session = get_live_session(session_id)
    supplied = request.args.get('token', '')
    if not session or not token_matches(session, supplied):
        return jsonify({'ok': False, 'error': 'UNAUTHORIZED'}), 403
    data = request.get_json(silent=True) or {}
    if not data.get('sdp') or not data.get('type'):
        return jsonify({'ok': False, 'error': 'BAD_SDP'}), 400
    try:
        answer = rtc_call(handle_rtc_offer(session, data['sdp'], data['type']), timeout=30)
        return jsonify(answer)
    except Exception as e:
        print(f'⚠️ [WEBRTC OFFER ERROR] {repr(e)}', flush=True)
        return jsonify({'ok': False, 'error': 'WEBRTC_FAILED'}), 500


def close_rtc_session(session):
    pc = session.get('rtc_peer')
    if not pc:
        return
    async def closer():
        try:
            await pc.close()
        except Exception:
            pass
    try:
        rtc_call(closer(), timeout=5)
    except Exception:
        pass
    session['rtc_peer'] = None
    session['rtc_channel'] = None
    session['rtc_connected'] = False


def run_remote_session(page, session):
    started = time.time()
    try:
        while not session.get('closed') and time.time() - started < REMOTE_SESSION_TIMEOUT:
            process_remote_commands(page, session)
            time.sleep(0.005)
    except Exception as e:
        print(f'⚠️ [REMOTE LOOP ERROR] {repr(e)}', flush=True)
    finally:
        session['closed'] = True
        close_rtc_session(session)
        remove_live_session(session['session_id'])


def reset_page(page):
    page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=25000)
    page.evaluate("window.scrollTo(0,0)")
    time.sleep(0.35)


def install_fast_routes(context):
    blocked_hosts = ('google-analytics.com','googletagmanager.com','doubleclick.net','facebook.net','facebook.com','hotjar.com','clarity.ms','connect.facebook.net')
    def handler(route):
        req = route.request
        url = req.url.lower()
        if any(host in url for host in blocked_hosts) or req.resource_type in ('font','media','texttrack'):
            return route.abort()
        return route.continue_()
    context.route('**/*', handler)


def evaluate_vip_expanded(num):
    clean = str(num).replace(' ','').replace('-','').strip()
    if not (len(clean) == 10 and (clean.startswith('06') or clean.startswith('07'))):
        return None
    d = clean[2:]
    if len(set(d)) <= 4: return 'تنوع منخفض للأرقام (مميز)'
    if d == d[::-1]: return 'مرآة متناظرة كاملة (Palindrome)'
    if d[:4] == d[4:]: return 'نصفين متطابقين تماماً'
    sequences = ['0123','1234','2345','3456','4567','5678','6789','9876','8765','7654','6543','5432','4321','3210']
    for seq in sequences:
        if seq in d: return 'تسلسل أرقام متتالي'
    if len(set(d[-4:])) <= 2 or len(set(d[:4])) <= 2: return 'تكرار عالي في الأطراف'
    if d[0] == d[1] == d[2] or d[-3] == d[-2] == d[-1]: return 'ثلاثية متتالية'
    return None


def select_number(page, number):
    target = str(number).replace(' ','').replace('-','').strip()
    try:
        selectors = [
            f'input[type="radio"][value*="{target}"]',
            f'option[value*="{target}"]',
            f'[data-msisdn*="{target}"]',
            f'[data-number*="{target}"]',
            f'[value*="{target}"]',
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    el = loc.first
                    tag = (el.evaluate('(e)=>e.tagName') or '').lower()
                    if tag == 'option':
                        el.locator('xpath=..').select_option(value=el.get_attribute('value') or '')
                    elif tag == 'input':
                        try: el.check(force=True, timeout=1500)
                        except Exception: el.click(force=True, timeout=1500)
                    else:
                        el.click(force=True, timeout=1500)
                    print(f'🎯 [SELECT EXACT] تم تحديد {number}', flush=True)
                    return True
            except Exception:
                pass
        loc = page.get_by_text(str(number), exact=False)
        count = min(loc.count(), 30)
        for i in range(count):
            try:
                el = loc.nth(i)
                if el.is_visible(timeout=700):
                    el.click(force=True, timeout=1500)
                    print(f'🎯 [SELECT TEXT] تم اختيار {number}', flush=True)
                    return True
            except Exception:
                pass
        radios = page.locator('input[type="radio"]')
        for i in range(radios.count()):
            try:
                radio = radios.nth(i)
                combined = ((radio.get_attribute('value') or '') + ' ' + (radio.get_attribute('id') or '')).lower()
                if 'new' in combined or 'nouveau' in combined:
                    try: radio.check(force=True, timeout=1500)
                    except Exception: radio.click(force=True, timeout=1500)
                    print(f'⚠️ [SELECT FALLBACK] اختيار مسار الرقم الجديد لـ {number}', flush=True)
                    return True
            except Exception:
                pass
    except Exception as e:
        print(f'⚠️ [SELECT ERROR] {repr(e)}', flush=True)
    return False


def get_numbers(page):
    return page.evaluate('''async()=>{const urls=['./api/msisdns?'+Date.now(),'/api/msisdns?'+Date.now()];let lastError=null;for(const url of urls){try{const res=await fetch(url,{method:'GET',credentials:'include',headers:{'X-Requested-With':'XMLHttpRequest','Cache-Control':'no-cache'}});const text=await res.text();let data=null;try{data=JSON.parse(text)}catch(e){}if(!res.ok){lastError='HTTP '+res.status+' URL='+url;if(res.status===404)continue;return {error:lastError}}return {status:res.status,url,data,raw:text.substring(0,1000)}}catch(e){lastError=String(e)}}return {error:lastError||'API_REQUEST_FAILED'}}''')


def telegram_api(method, payload):
    if not TELEGRAM_BOT_TOKEN:
        return None
    try:
        return requests.post(f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}', json=payload, timeout=10)
    except Exception as e:
        print(f'⚠️ [TELEGRAM API ERROR] {repr(e)}', flush=True)
    return None


def send_telegram_alert(number, desc, session_id, token):
    render_url = os.environ.get('RENDER_EXTERNAL_URL', 'https://freemobile-bot.onrender.com').rstrip('/')
    open_url = f'{render_url}/vip/{session_id}?token={token}'
    message = (f'🔥 *رقم مميز VIP جديد!*\n\n📱 الرقم: `{number}`\n💎 التصنيف: {desc}\n\n'
               '⚡ افتح الجلسة — نفس Chromium ونفس الرقم المحدد مسبقاً (WebRTC).')
    keyboard = {'inline_keyboard': [[{'text':'⚡ فتح Free — WebRTC','url':open_url}], [{'text':'❌ لا يعجبني — تخطي','callback_data':f'skip:{session_id}'}]]}
    if not TELEGRAM_BOT_TOKEN or not CHAT_ID:
        return
    r = telegram_api('sendMessage', {'chat_id':CHAT_ID,'text':message,'parse_mode':'Markdown','disable_web_page_preview':True,'reply_markup':keyboard})
    if r is not None and r.status_code != 200:
        print(f'⚠️ [TELEGRAM] HTTP={r.status_code} {r.text[:300]}', flush=True)


@app.route('/telegram/webhook', methods=['POST'])
def telegram_webhook():
    update = request.get_json(silent=True) or {}
    callback = update.get('callback_query')
    if not callback:
        return jsonify({'ok':True})
    callback_id = callback.get('id')
    data = str(callback.get('data') or '')
    if not data.startswith('skip:'):
        return jsonify({'ok':True})
    session_id = data[5:].strip()
    message = callback.get('message') or {}
    callback_chat_id = str((message.get('chat') or {}).get('id',''))
    if CHAT_ID and callback_chat_id != str(CHAT_ID):
        return jsonify({'ok':True})
    session = get_live_session(session_id)
    if session:
        session['closed'] = True
        queue_remote_command(session, 'close', {})
        print(f'⏭️ [SKIP] تم تخطي الرقم {session["number"]}', flush=True)
    if callback_id:
        telegram_api('answerCallbackQuery', {'callback_query_id':callback_id,'text':'⏭️ تم التخطي — البحث مستمر','show_alert':False})
    if message:
        chat_id = message.get('chat',{}).get('id'); message_id = message.get('message_id')
        if chat_id and message_id:
            telegram_api('editMessageReplyMarkup', {'chat_id':chat_id,'message_id':message_id,'reply_markup':{'inline_keyboard':[[{'text':'⏭️ تم تخطي هذا الرقم','callback_data':'done'}]]}})
    return jsonify({'ok':True})


def configure_telegram_webhook():
    if not TELEGRAM_BOT_TOKEN:
        print('ℹ️ [TELEGRAM] لا يوجد TELEGRAM_BOT_TOKEN', flush=True)
        return
    render_url = os.environ.get('RENDER_EXTERNAL_URL','https://freemobile-bot.onrender.com').rstrip('/')
    r = telegram_api('setWebhook', {'url':render_url+'/telegram/webhook','allowed_updates':['callback_query']})
    if r is not None:
        print(f'📨 [TELEGRAM WEBHOOK] HTTP={r.status_code}', flush=True)


@app.route('/')
def home():
    turn = 'مفعل' if TURN_URL else 'غير مضبوط'
    return f'<h2 style="font-family:Arial;text-align:center;padding:50px">🚀 Free Mobile VIP Bot<br><br>⚡ WebRTC Remote يعمل<br>🎯 الرقم VIP محدد داخل نفس جلسة Chromium<br>🛰️ TURN: {turn}</h2>'


def run_smart_monitor():
    print('🔥🔥🔥 [THREAD ACTIVE] محرك الفحص بدأ', flush=True)
    current_proxies = []
    proxy_refresh_time = 0
    while True:
        browser = None; context = None; page = None; proxy = None
        try:
            with sync_playwright() as p:
                if time.time() - proxy_refresh_time > 600 or not current_proxies:
                    current_proxies = fetch_fresh_proxies(); proxy_refresh_time = time.time()
                if current_proxies:
                    proxy = random.choice(current_proxies)
                launch_args = {
                    'headless': False,
                    'args': [
                        '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
                        '--disable-background-networking', '--disable-background-timer-throttling',
                        '--disable-renderer-backgrounding', '--window-size=390,844', '--kiosk',
                        '--force-device-scale-factor=1', '--hide-scrollbars=false',
                    ],
                }
                if proxy:
                    launch_args['proxy'] = {'server': proxy}
                browser_path = p.chromium.executable_path
                print(
                    f'🔎 [PLAYWRIGHT] browsers_path={os.environ.get("PLAYWRIGHT_BROWSERS_PATH")} '
                    f'chromium={browser_path} exists={os.path.exists(browser_path)}',
                    flush=True
                )
                if not os.path.exists(browser_path):
                    raise RuntimeError(
                        f"Chromium غير موجود في {browser_path}. "
                        "تأكد من تشغيل: PLAYWRIGHT_BROWSERS_PATH=/ms-playwright "
                        "playwright install chromium داخل Docker."
                    )
                print(f'🚀 [BROWSER] تشغيل Chromium GUI/WebRTC | البروكسي: {proxy}', flush=True)
                browser = p.chromium.launch(**launch_args)
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
                    viewport={'width': DISPLAY_WIDTH, 'height': DISPLAY_HEIGHT},
                    device_scale_factor=1,
                    locale='fr-FR',
                    reduced_motion='reduce',
                    is_mobile=True,
                    has_touch=True,
                )
                install_fast_routes(context)
                page = context.new_page(); page.set_default_timeout(5000); page.set_default_navigation_timeout(25000)
                page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=25000); time.sleep(0.5)
                while True:
                    api_result = get_numbers(page)
                    if not isinstance(api_result, dict):
                        break
                    if api_result.get('error'):
                        err = str(api_result['error']); print(f'⚠️ [API ERROR] {err} (البروكسي: {proxy})', flush=True)
                        if proxy in current_proxies:
                            current_proxies.remove(proxy)
                        time.sleep(random.uniform(5,10) if '429' in err else random.uniform(3,6)); break
                    status = api_result.get('status'); data = api_result.get('data'); raw = api_result.get('raw','')
                    if isinstance(data, list):
                        numbers_list = data
                    elif isinstance(data, dict):
                        numbers_list = (
                            data.get('msisdns')
                            or data.get('numbers')
                            or data.get('data')
                            or []
                        )
                    else:
                        numbers_list = []
                    if not isinstance(numbers_list, list):
                        numbers_list = []
                    print(f'📱 [API] HTTP={status} | عدد الأرقام: {len(numbers_list)} | البروكسي: {proxy}', flush=True)
                    if not numbers_list and raw:
                        print(f'📄 [API RAW] {raw[:300]}', flush=True)
                    found = False
                    for item in numbers_list:
                        if isinstance(item, dict):
                            number = (
                                item.get('value')
                                or item.get('msisdn')
                                or item.get('number')
                                or item.get('phone')
                            )
                        else:
                            number = str(item)
                        if not number:
                            continue
                        desc = evaluate_vip_expanded(number)
                        if not desc:
                            continue
                        found = True
                        print(f'🔥🔥🔥 VIP FOUND: {number}', flush=True)
                        selected = select_number(page, number)
                        if not selected:
                            print(f'⚠️ [SELECT] تعذر تحديد الرقم {number} بشكل مباشر', flush=True)
                        session = create_live_session(number)
                        send_telegram_alert(number, desc, session['session_id'], session['token'])
                        run_remote_session(page, session)
                        try:
                            reset_page(page)
                        except Exception as e:
                            print(f'⚠️ [RESET PAGE ERROR] {repr(e)}', flush=True); raise
                        break
                    if not found:
                        print('🔍 [MONITOR] لا يوجد VIP هذه المرة', flush=True)
                    time.sleep(random.uniform(MIN_DELAY,MAX_DELAY))
        except Exception as e:
            print(f'❌ [PLAYWRIGHT ERROR] {repr(e)}', flush=True); time.sleep(3)
        finally:
            try:
                if context: context.close()
            except Exception: pass
            try:
                if browser: browser.close()
            except Exception: pass


if __name__ == '__main__':
    print('🚀 [START] Free Mobile VIP Bot + WebRTC Remote', flush=True)
    start_rtc_loop()
    try:
        configure_telegram_webhook()
    except Exception as e:
        print(f'⚠️ [WEBHOOK ERROR] {repr(e)}', flush=True)
    threading.Thread(target=run_smart_monitor, daemon=True, name='vip-monitor').start()
    port = int(os.environ.get('PORT','5000'))
    app.run(host='0.0.0.0', port=port, threaded=True)
