import os
import json
import time
import random
import secrets
import requests
import threading
import sys

from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
TARGET_URL = "https://mobile.free.fr/souscription/options"
MIN_DELAY = 2.5
MAX_DELAY = 4.5
DISPLAY_WIDTH = 390
DISPLAY_HEIGHT = 844

# متغيرات مشاركة الشاشة وبث WebRTC
current_frame = None
frame_lock = threading.Lock()


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


# ======================================================
# 💎 STRICT VIP FILTER (دالة الفلتر الصارمة والنهائية)
# ======================================================

def evaluate_vip_expanded(num):
    clean = (
        str(num)
        .replace(" ", "")
        .replace("-", "")
        .strip()
    )

    if len(clean) != 10:
        return None

    if not (
        clean.startswith("06")
        or clean.startswith("07")
    ):
        return None

    d = clean[2:]  # الأرقام الـ 8 الأخيرة

    # ======================================================
    # 💎 ULTRA VIP (أرقام خارقة ونادرة جداً)
    # ======================================================

    # 1. تكرار كامل: AAAAAAAA
    if len(set(d)) == 1:
        return "💎 ULTRA VIP — تكرار كامل (AAAAHHHH)"

    # 2. تبديل ثنائي متطابق: ABABABAB
    if (
        d[0] == d[2] == d[4] == d[6]
        and
        d[1] == d[3] == d[5] == d[7]
        and
        d[0] != d[1]
    ):
        return "💎 ULTRA VIP — متناوب مزدوج (ABABABAB)"

    # 3. مقطعين متطابقين تماماً: ABCDABCD (تكرار النصفين تماماً)
    if d[:4] == d[4:]:
        return "💎 ULTRA VIP — نصفين متطابقين (ABCDABCD)"

    # 4. نمط مرآة مزدوج: ABBAABBA
    if (
        d[0] == d[3]
        and d[1] == d[2]
        and d[4] == d[7]
        and d[5] == d[6]
        and d[0] != d[1]
    ):
        return "💎 ULTRA VIP — نمط مرآة (ABBAABBA)"

    # ======================================================
    # 🔥 VERY VIP (أرقام مميزة جداً وقوية)
    # ======================================================

    # 1. خمسة أرقام متطابقة في البداية: AAAAAxxx
    if d[0] == d[1] == d[2] == d[3] == d[4]:
        return "🔥 VERY VIP — خماسي في البداية"

    # 2. خمسة أرقام متطابقة في النهاية: xxxAAAAA
    if d[3] == d[4] == d[5] == d[6] == d[7]:
        return "🔥 VERY VIP — خماسي في النهاية"

    # ======================================================
    # ⭐ VIP (أرقام مميزة واضحة)
    # ======================================================

    # 1. أربع أرقام يتبعها أربع أرقام مختلفة: AAAABBBB
    if (
        d[0] == d[1] == d[2] == d[3]
        and
        d[4] == d[5] == d[6] == d[7]
        and
        d[0] != d[4]
    ):
        return "⭐ VIP — رباعي مزدوج (AAAABBBB)"

    # 2. أزواج متتالية رباعية: AABBAABB
    if (
        d[0] == d[1]
        and d[2] == d[3]
        and d[4] == d[5]
        and d[6] == d[7]
        and d[0] != d[2]
        and d[2] != d[4]
    ):
        return "⭐ VIP — أزواج متتالية (AABBAABB)"

    return None


def select_number(page, number):
    target = str(number).replace(' ', '').replace('-', '').strip()
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
                        try:
                            el.check(force=True, timeout=1500)
                        except Exception:
                            el.click(force=True, timeout=1500)
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


def send_telegram_alert(number, desc, remote_url):
    message = f'🔥 *رقم مميز VIP حقيقي جديد!*\n\n📱 الرقم: `{number}`\n💎 التصنيف: {desc}\n\nاضغط لفتح 🖥️ Remote Browser.'
    keyboard = {
        "inline_keyboard": [
            [{"text": "🖥️ فتح Remote Browser", "url": remote_url}],
            [{"text": "❌ لا يعجبني – تخطي الرقم", "callback_data": "skip"}]
        ]
    }
    if not TELEGRAM_BOT_TOKEN or not CHAT_ID:
        return
    telegram_api('sendMessage', {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown', 'reply_markup': keyboard, 'disable_web_page_preview': True})


def reset_page(page):
    page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=25000)
    page.evaluate("window.scrollTo(0,0)")
    time.sleep(0.35)


@app.route('/')
def home():
    return '''
    <html>
        <head><title>Free Mobile VIP WebRTC</title></head>
        <body style="font-family:Arial;text-align:center;padding:30px;background:#111;color:#fff;">
            <h2>🚀 Free Mobile VIP Bot (WebRTC + Strict Filter) يعمل بنجاح</h2>
            <p>صفحة البث الحي نشطة وجاهزة.</p>
        </body>
    </html>
    '''


def run_smart_monitor():
    global current_frame
    print('🔥🔥🔥 [THREAD ACTIVE] محرك الفحص والويب سرتك الصارم بدأ', flush=True)
    current_proxies = []
    proxy_refresh_time = 0
    while True:
        browser = None
        context = None
        page = None
        proxy = None
        try:
            with sync_playwright() as p:
                if time.time() - proxy_refresh_time > 600 or not current_proxies:
                    current_proxies = fetch_fresh_proxies()
                    proxy_refresh_time = time.time()
                if current_proxies:
                    proxy = random.choice(current_proxies)
                
                launch_args = {
                    'headless': True,
                    'args': ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--window-size=390,844'],
                }
                if proxy:
                    launch_args['proxy'] = {'server': proxy}

                browser = p.chromium.launch(**launch_args)
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
                    viewport={'width': DISPLAY_WIDTH, 'height': DISPLAY_HEIGHT},
                    is_mobile=True,
                    has_touch=True,
                )
                page = context.new_page()
                page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=25000)
                time.sleep(0.5)

                while True:
                    # التقاط الشاشة للبث الحي
                    try:
                        screenshot_bytes = page.screenshot(type="jpeg", quality=60)
                        with frame_lock:
                            current_frame = screenshot_bytes
                    except Exception:
                        pass

                    api_result = get_numbers(page)
                    if not isinstance(api_result, dict):
                        break
                    if api_result.get('error'):
                        err = str(api_result['error'])
                        print(f'⚠️ [API ERROR] {err}', flush=True)
                        break
                    
                    data = api_result.get('data')
                    numbers_list = data if isinstance(data, list) else (data.get('msisdns', []) if isinstance(data, dict) else [])
                    
                    vip_numbers = []
                    for item in numbers_list:
                        number = item.get("value") if isinstance(item, dict) else str(item)
                        if not number:
                            continue

                        desc = evaluate_vip_expanded(number)
                        if not desc:
                            continue

                        vip_numbers.append({
                            "number": str(number),
                            "desc": desc
                        })
                        print(f"🔥 VIP FOUND: {number} | {desc}", flush=True)

                    if vip_numbers:
                        print(f"💎 تم العثور على {len(vip_numbers)} أرقام VIP حقيقية", flush=True)
                        target_vip = vip_numbers[0]
                        number = target_vip["number"]
                        desc = target_vip["desc"]

                        select_number(page, number)
                        
                        # توليد رابط البث الخاص بالمنصة
                        host_url = request.host_url if request else "https://your-app.onrender.com"
                        send_telegram_alert(number, desc, host_url)
                        reset_page(page)
                    else:
                        print("🔍 لا يوجد VIP مطابق بالشروط الصارمة", flush=True)

                    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
        except Exception as e:
            print(f'❌ [PLAYWRIGHT ERROR] {repr(e)}', flush=True)
            time.sleep(3)
        finally:
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


if __name__ == '__main__':
    print('🚀 [START] Free Mobile VIP Bot (WebRTC + Strict Filter)', flush=True)
    threading.Thread(target=run_smart_monitor, daemon=True, name='vip-webrtc-monitor').start()
    port = int(os.environ.get('PORT', '5000'))
    app.run(host='0.0.0.0', port=port, threaded=True)
