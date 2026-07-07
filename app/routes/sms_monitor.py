"""
sms_monitor.py  —  Volt SMS Monitor (FIXED V2)
======================================
Fetches messages from external sources (5 sources)
and automatically forwards them to reserved numbers.

FIX LIST:
  1. FIX: Date vs Number Confusion — Modified _detect_abyss_indexes to identify date first and exclude it from the phone number search.
  2. FIX: Number format in Volt — Ensured retrieving the complete number from the correct index.
"""
import os, re, json, time, requests, threading, hashlib

# Resolve local port robustly matching run.py
_sys_server_port = os.environ.get('SERVER_PORT')
_sys_port = os.environ.get('PORT')
if os.environ.get('DEFAULT_APP_PORT'):
    local_port = os.environ.get('DEFAULT_APP_PORT')
elif os.environ.get('PORT'):
    local_port = os.environ.get('PORT')
elif os.environ.get('SERVER_PORT'):
    local_port = os.environ.get('SERVER_PORT')
elif _sys_port:
    local_port = _sys_port
elif _sys_server_port:
    local_port = _sys_server_port
else:
    local_port = '5000'
from datetime import datetime, timedelta, date
from urllib.parse import quote_plus
from functools import wraps
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models.sms import SMSNumber, SMSCDR
from app.models.activity import ActivityLog

monitor_bp = Blueprint("monitor", __name__, url_prefix="/monitor")

# ─── helpers ────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10)",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

def _clean_html(t):
    return re.sub(r"<[^>]+>", "", str(t or "")).strip()

def _clean_num(n):
    cleaned = re.sub(r"\D", "", str(n or ""))
    return cleaned

def _extract_service_from_text(text):
    text_lower = str(text or "").lower()
    services = {
        'telegram': 'Telegram',
        'whatsapp': 'WhatsApp',
        'google': 'Google',
        'facebook': 'Facebook',
        'instagram': 'Instagram',
        'tiktok': 'TikTok',
        'twitter': 'Twitter / X',
        'snapchat': 'Snapchat',
        'imo': 'Imo',
        'viber': 'Viber',
        'wechat': 'WeChat',
        'line': 'Line',
        'discord': 'Discord',
        'microsoft': 'Microsoft',
        'apple': 'Apple',
        'netflix': 'Netflix',
        'steam': 'Steam',
        'uber': 'Uber',
        'bolt': 'Bolt',
        'careem': 'Careem',
        'amazon': 'Amazon',
        'paypal': 'PayPal',
        'stripe': 'Stripe',
        'binance': 'Binance',
        'تليجرام': 'Telegram',
        'واتساب': 'WhatsApp',
        'جوجل': 'Google',
        'فيسبوك': 'Facebook',
        'تيك توك': 'TikTok',
        'سناب': 'Snapchat',
        'أمازون': 'Amazon',
        'بايبال': 'PayPal'
    }
    for key, val in services.items():
        if key in text_lower:
            return val
            
    match = re.search(r'([A-Za-z0-9\-\.]+)\s+(?:code|verification|otp|رمز)', text_lower)
    if match:
        service_candidate = match.group(1).capitalize()
        if len(service_candidate) > 2 and service_candidate.lower() not in ['your', 'verification', 'code', 'is', 'for', 'the', 'is:', 'رمز', 'كود']:
            return service_candidate
            
    match_ar = re.search(r'رمز\s+تحقق\s+([^\s]+)', text_lower)
    if match_ar:
        service_candidate = match_ar.group(1)
        if len(service_candidate) > 2 and service_candidate.lower() not in ['كود', 'رمز', 'الخاص', 'بموقع']:
            return service_candidate
            
    return "Unknown Service / خدمة غير معروفة"

def _make_ext_id(prefix, number, date_str, text):
    raw = f"{number}|{date_str}|{text[:40]}"
    h   = hashlib.md5(raw.encode()).hexdigest()[:8]
    return f"{prefix}_{number}_{h}"

def _mask_token(token):
    if not token or len(token) < 10:
        return "****"
    return token[:6] + "****" + token[-4:]


class MockResponse:
    def __init__(self, flask_res):
        self.status_code = flask_res.status_code
        self.text = flask_res.get_data(as_text=True)
        # Handle redirection path or location
        self.url = flask_res.location or ""
        self._json_data = None
        try:
            self._json_data = flask_res.get_json()
        except Exception:
            pass

    def json(self):
        if self._json_data is not None:
            return self._json_data
        import json
        return json.loads(self.text)


class SmartSession(requests.Session):
    def __init__(self):
        super().__init__()
        self._flask_client = None

    def _get_client(self):
        if self._flask_client is None:
            try:
                from flask import current_app
                if current_app:
                    self._flask_client = current_app.test_client()
            except Exception:
                pass
        return self._flask_client

    def request(self, method, url, *args, **kwargs):
        # If url is local (contains 127.0.0.1 or localhost)
        if "127.0.0.1" in url or "localhost" in url:
            client = self._get_client()
            if client:
                from urllib.parse import urlparse, urlencode
                parsed = urlparse(url)
                path = parsed.path
                
                # extract params
                params = kwargs.get('params')
                if params:
                    path += "?" + urlencode(params)
                elif parsed.query:
                    path += "?" + parsed.query
                
                data = kwargs.get('data')
                allow_redirects = kwargs.get('allow_redirects', True)
                
                # Use follow_redirects for Flask test client
                if method.upper() == 'POST':
                    flask_res = client.post(path, data=data, follow_redirects=allow_redirects)
                else:
                    flask_res = client.get(path, follow_redirects=allow_redirects)
                    
                return MockResponse(flask_res)
                
        # Otherwise, fall back to normal requests.Session.request
        return super().request(method, url, *args, **kwargs)

def admin_required(f):
    @wraps(f)
    def d(*a, **kw):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash("Admin access required.", "danger")
            return redirect(url_for("auth.login"))
        return f(*a, **kw)
    return d


# ════════════════════════════════════════════════════════════
# SOURCE A  (Panel 4 — session/captcha)
# ════════════════════════════════════════════════════════════

CFG_P4 = {
    "name":       "Source A",
    "base":       f"http://127.0.0.1:{local_port}",
    "ajax_path":  "/ints/agent/res/data_smscdr.php",
    "login_page": "/ints/login",
    "login_post": "/ints/signin",
    "username":   "GHOST1",
    "password":   "GHOSTSCRIPT",
    "timeout":    5,
    "idx_date": 0, "idx_number": 2, "idx_cli": 3, "idx_sms": 5,
}

_p4_session   = None
_p4_logged_in = False


def _p4_login():
    global _p4_session, _p4_logged_in
    s = SmartSession()
    s.headers.update(HEADERS)
    try:
        r = s.get(CFG_P4["base"] + CFG_P4["login_page"],
                  timeout=CFG_P4["timeout"])
        if any(k in r.text.lower() for k in ("logout", "dashboard", "agent")):
            _p4_session, _p4_logged_in = s, True
            return True
        m = re.search(r"What is (\d+) \+ (\d+)", r.text)
        if not m:
            _p4_logged_in = False
            return False
        payload = {
            "username": CFG_P4["username"],
            "password": CFG_P4["password"],
            "capt":     str(int(m.group(1)) + int(m.group(2))),
        }
        r2 = s.post(CFG_P4["base"] + CFG_P4["login_post"],
                    data=payload, timeout=CFG_P4["timeout"],
                    allow_redirects=True)
        ok = any(k in r2.url.lower()  for k in ("dashboard", "agent")) or \
             any(k in r2.text.lower() for k in ("logout", "dashboard", "agent"))
        _p4_session, _p4_logged_in = s, ok
        return ok
    except Exception as e:
        print(f"[SourceA] login error: {e}")
        _p4_logged_in = False
        return False


def _fetch_panel_session(cfg, sess, is_logged, src_key):
    """Generic session-panel fetcher. Returns (msgs, status_str)."""
    if not is_logged:
        return [], "not_logged_in"

    today = date.today()
    td  = f"{today.strftime('%Y-%m-%d')} 00:00:00"
    td2 = f"{(today + timedelta(days=1)).strftime('%Y-%m-%d')} 23:59:59"
    ts  = int(time.time() * 1000)
    q = (
        f"fdate1={quote_plus(td)}&fdate2={quote_plus(td2)}"
        f"&frange=&fclient=&fnum=&fcli=&fgdate=&fgmonth=&fgrange=&fgclient=&fgnumber=&fgcli="
        f"&fg=0&sEcho=1&iColumns=9&sColumns=%2C%2C%2C%2C%2C%2C%2C%2C"
        f"&iDisplayStart=0&iDisplayLength=5000"
        f"&mDataProp_0=0&mDataProp_1=1&mDataProp_2=2&mDataProp_3=3&mDataProp_4=4"
        f"&mDataProp_5=5&mDataProp_6=6&mDataProp_7=7&mDataProp_8=8"
        f"&sSearch=&bRegex=false&iSortCol_0=0&sSortDir_0=desc&iSortingCols=1&_={ts}"
    )
    url = cfg["base"] + cfg["ajax_path"] + "?" + q
    try:
        r = sess.get(url, timeout=12)
        if r.status_code == 403 or \
           any(k in r.url.lower() for k in ("login", "signin")):
            return [], "session_expired"
        data = r.json()
    except Exception as e:
        return [], str(e)

    rows = []
    for k in ("data", "aaData", "rows"):
        if isinstance(data, dict) and k in data:
            rows = data[k]
            break
    if not rows and isinstance(data, list):
        rows = data

    ix_d = cfg["idx_date"]
    ix_n = cfg["idx_number"]
    ix_c = cfg.get("idx_cli", 3)
    ix_s = cfg["idx_sms"]
    msgs = []

    for row in rows:
        if isinstance(row, (list, tuple)):
            d   = _clean_html(row[ix_d] if len(row) > ix_d else "")
            n   = _clean_num(row[ix_n]  if len(row) > ix_n else "")
            cli = _clean_html(row[ix_c] if len(row) > ix_c else "")
            s   = _clean_html(row[ix_s] if len(row) > ix_s else "")
        elif isinstance(row, dict):
            d   = _clean_html(row.get("date", row.get("dt", "")))
            n   = _clean_num(row.get("number", row.get("msisdn", row.get("num", ""))))
            cli = _clean_html(row.get("cli", ""))
            s   = _clean_html(row.get("sms", row.get("message", row.get("msg", ""))))
        else:
            continue

        if d and n and len(n) >= 8 and s and len(s) > 3:
            msgs.append({
                "id":     _make_ext_id(src_key, n, d, s),
                "number": n, "text": s, "date": d,
                "source": src_key, "cli": cli,
            })

    return msgs, "ok"


def fetch_panel4():
    global _p4_session, _p4_logged_in
    if not _p4_logged_in:
        if not _p4_login():
            return [], "Login failed"
    msgs, st = _fetch_panel_session(CFG_P4, _p4_session, _p4_logged_in, "panel4")
    if st == "session_expired":
        _p4_logged_in = False
        if _p4_login():
            msgs, st = _fetch_panel_session(CFG_P4, _p4_session, _p4_logged_in, "panel4")
        else:
            return [], "Session expired, re-login failed"
    return msgs, st


# ════════════════════════════════════════════════════════════
# SOURCE A 2 (Panel 4 Duplicate — session/captcha)
# ════════════════════════════════════════════════════════════

CFG_P4_2 = {
    "name":       "Source A 2",
    "base":       f"http://127.0.0.1:{local_port}",
    "ajax_path":  "/ints/agent/res/data_smscdr.php",
    "login_page": "/ints/login",
    "login_post": "/ints/signin",
    "username":   "Youssef123X",
    "password":   "Youssef212",
    "timeout":    5,
    "idx_date": 0, "idx_number": 2, "idx_cli": 3, "idx_sms": 5,
}

_p4_2_session   = None
_p4_2_logged_in = False


def _p4_2_login():
    global _p4_2_session, _p4_2_logged_in
    s = SmartSession()
    s.headers.update(HEADERS)
    try:
        r = s.get(CFG_P4_2["base"] + CFG_P4_2["login_page"],
                  timeout=CFG_P4_2["timeout"])
        if any(k in r.text.lower() for k in ("logout", "dashboard", "agent")):
            _p4_2_session, _p4_2_logged_in = s, True
            return True
        m = re.search(r"What is (\d+) \+ (\d+)", r.text)
        if not m:
            _p4_2_logged_in = False
            return False
        payload = {
            "username": CFG_P4_2["username"],
            "password": CFG_P4_2["password"],
            "capt":     str(int(m.group(1)) + int(m.group(2))),
        }
        r2 = s.post(CFG_P4_2["base"] + CFG_P4_2["login_post"],
                    data=payload, timeout=CFG_P4_2["timeout"],
                    allow_redirects=True)
        ok = any(k in r2.url.lower()  for k in ("dashboard", "agent")) or \
             any(k in r2.text.lower() for k in ("logout", "dashboard", "agent"))
        _p4_2_session, _p4_2_logged_in = s, ok
        return ok
    except Exception as e:
        print(f"[SourceA2] login error: {e}")
        _p4_2_logged_in = False
        return False


def fetch_panel4_2():
    global _p4_2_session, _p4_2_logged_in
    if not _p4_2_logged_in:
        if not _p4_2_login():
            return [], "Login failed"
    msgs, st = _fetch_panel_session(CFG_P4_2, _p4_2_session, _p4_2_logged_in, "panel4_2")
    if st == "session_expired":
        _p4_2_logged_in = False
        if _p4_2_login():
            msgs, st = _fetch_panel_session(CFG_P4_2, _p4_2_session, _p4_2_logged_in, "panel4_2")
        else:
            return [], "Session expired, re-login failed"
    return msgs, st


# ════════════════════════════════════════════════════════════
# SOURCE ABYSS (Volt SMS Panel — session/captcha + auto index detection)
# ════════════════════════════════════════════════════════════

CFG_ABYSS = {
    "name":       "Volt SMS",
    "base":       f"http://127.0.0.1:{local_port}",
    "ajax_path":  "/ints/agent/res/data_smscdr.php",
    "login_page": "/ints/login",
    "login_post": "/ints/signin",
    "stats_page": "/ints/agent/SMSCDRStats",
    "username":   "ABYSS_SMS",
    "password":   "ABYSS_SMS",
    "timeout":    15,
}

_abyss_session   = None
_abyss_logged_in = False


def _abyss_login():
    global _abyss_session, _abyss_logged_in
    s = SmartSession()
    s.headers.update(HEADERS)
    try:
        r = s.get(CFG_ABYSS["base"] + CFG_ABYSS["login_page"],
                  timeout=CFG_ABYSS["timeout"])
        if any(k in r.text.lower() for k in ("logout", "dashboard", "agent")):
            _abyss_session, _abyss_logged_in = s, True
            return True
        m = re.search(r"What is (\d+) \+ (\d+)", r.text)
        if not m:
            _abyss_logged_in = False
            return False
        payload = {
            "username": CFG_ABYSS["username"],
            "password": CFG_ABYSS["password"],
            "capt":     str(int(m.group(1)) + int(m.group(2))),
        }
        r2 = s.post(CFG_ABYSS["base"] + CFG_ABYSS["login_post"],
                    data=payload, timeout=CFG_ABYSS["timeout"],
                    allow_redirects=True)
        ok = any(k in r2.url.lower()  for k in ("dashboard", "agent")) or \
             any(k in r2.text.lower() for k in ("logout", "dashboard", "agent"))
        _abyss_session, _abyss_logged_in = s, ok
        return ok
    except Exception as e:
        print(f"[ABYSS] login error: {e}")
        _abyss_logged_in = False
        return False


def _detect_abyss_indexes(rows):
    """Smartly infer index positions for date, number, and message to avoid overlap."""
    if not rows or not isinstance(rows[0], list):
        return 0, 2, 4
    
    sample = rows[0]
    idx_date = -1
    idx_number = -1
    idx_sms = -1
    
    # 1. Search for date first (format YYYY-MM-DD)
    for i, cell in enumerate(sample):
        cell_str = _clean_html(cell)
        if re.search(r"\d{4}-\d{2}-\d{2}", cell_str):
            idx_date = i
            break
    
    # 2. Search for phone number (digits only, not the discovered date, and of appropriate length)
    max_digit_len = 0
    for i, cell in enumerate(sample):
        if i == idx_date: continue # Completely exclude date
        
        cell_str = _clean_html(cell)
        digits = _clean_num(cell_str)
        
        # Exclude digits that look like a date without separators
        # Date is formatted like: 20260418001936 (14 digits) or 20260418 (8 digits - date only)
        if digits.startswith("202") and len(digits) in (8, 14):
            # This looks like a date (202X + 4 digits for month-day or + 6 for time)
            continue
        
        # Ensure the digit length matches a typical phone number (usually 8-15 digits)
        if 8 <= len(digits) <= 15:
            if len(digits) > max_digit_len:
                max_digit_len = len(digits)
                idx_number = i
        elif len(digits) > 15:
            # Might be a very long number (longer than a normal phone number)
            # Check if it contains a date pattern
            if not re.search(r"202[0-9]", digits):
                if len(digits) > max_digit_len:
                    max_digit_len = len(digits)
                    idx_number = i
            
    # 3. Search for the message (longest text, neither date nor number)
    max_text_len = 0
    for i, cell in enumerate(sample):
        if i == idx_date or i == idx_number: continue
        
        cell_str = _clean_html(cell)
        if len(cell_str) > max_text_len:
            max_text_len = len(cell_str)
            idx_sms = i
            
    # Default values in case of failure
    if idx_date == -1: idx_date = 0
    if idx_number == -1: idx_number = 2
    if idx_sms == -1: idx_sms = 4
    
    return idx_date, idx_number, idx_sms

def _abyss_fetch_internal():
    if not _abyss_logged_in:
        return [], "not_logged_in"

    try:
        _abyss_session.get(CFG_ABYSS["base"] + CFG_ABYSS["stats_page"], timeout=CFG_ABYSS["timeout"])
    except: pass

    today = date.today()
    td  = f"{today.strftime('%Y-%m-%d')} 00:00:00"
    td2 = f"{(today + timedelta(days=30)).strftime('%Y-%m-%d')} 23:59:59"
    ts  = int(time.time() * 1000)
    q = (
        f"fdate1={quote_plus(td)}&fdate2={quote_plus(td2)}"
        f"&frange=&fclient=&fnum=&fcli=&fgdate=&fgmonth=&fgrange=&fgclient=&fgnumber=&fgcli="
        f"&fg=0&sEcho=1&iColumns=9&sColumns=%2C%2C%2C%2C%2C%2C%2C%2C"
        f"&iDisplayStart=0&iDisplayLength=500"
        f"&mDataProp_0=0&mDataProp_1=1&mDataProp_2=2&mDataProp_3=3&mDataProp_4=4"
        f"&mDataProp_5=5&mDataProp_6=6&mDataProp_7=7&mDataProp_8=8"
        f"&sSearch=&bRegex=false&iSortCol_0=0&sSortDir_0=desc&iSortingCols=1&_={ts}"
    )
    url = CFG_ABYSS["base"] + CFG_ABYSS["ajax_path"] + "?" + q
    try:
        r = _abyss_session.get(url, timeout=12)
        if r.status_code == 403 or any(k in r.url.lower() for k in ("login", "signin")):
            return [], "session_expired"
        data = r.json()
    except Exception as e:
        return [], str(e)

    rows = []
    for k in ("data", "aaData", "rows"):
        if isinstance(data, dict) and k in data:
            rows = data[k]
            break
    if not rows and isinstance(data, list): rows = data
    if not rows: return [], "no_rows"

    idx_date, idx_number, idx_sms = _detect_abyss_indexes(rows)
    msgs = []
    for row in rows:
        if not isinstance(row, list) or len(row) <= max(idx_date, idx_number, idx_sms):
            continue
        
        n = _clean_num(_clean_html(row[idx_number]))
        d = _clean_html(row[idx_date])
        s = _clean_html(row[idx_sms])
        cli = _clean_html(row[3]) if len(row) > 3 else ""
        
        # Make sure "number" is not just a date format in numbers
        if n.startswith("202") and len(n) > 8: continue 

        if d and n and len(n) >= 7 and s and len(s) > 3:
            msgs.append({
                "id":     _make_ext_id("abyss", n, d, s),
                "number": n, "text": s, "date": d,
                "source": "abyss", "cli": cli,
            })
    return msgs, "ok"

def fetch_abyss():
    global _abyss_session, _abyss_logged_in
    if not _abyss_logged_in:
        if not _abyss_login():
            return [], "Login failed"
    msgs, st = _abyss_fetch_internal()
    if st == "session_expired":
        _abyss_logged_in = False
        if _abyss_login():
            msgs, st = _abyss_fetch_internal()
        else:
            return [], "Session expired, re-login failed"
    return msgs, st


# ════════════════════════════════════════════════════════════
# SOURCE C  (TimeSMS — REST API)
# ════════════════════════════════════════════════════════════

CFG_TS = {
    "name":      "Source C",
    "api_url":   "http://147.135.212.197/crapi/time/viewstats",
    "api_token": "RVRVNEVBmIGEiZZbeIyOZXWFg1l5UYJIeGdpa2d2bmKDZmNcXlU=",
    "timeout":   15,
    "records":   500,
}


def fetch_timesms(days_back=1):
    now = datetime.now()
    params = {
        "token":   CFG_TS["api_token"],
        "dt1":     (now - timedelta(days=days_back)).strftime("%Y-%m-%d %H:%M:%S"),
        "dt2":     now.strftime("%Y-%m-%d %H:%M:%S"),
        "records": CFG_TS["records"],
    }
    try:
        r = requests.get(CFG_TS["api_url"], params=params, timeout=CFG_TS["timeout"])
        data = r.json()
        if data.get("status") != "success":
            return [], data.get("msg", f"API error (HTTP {r.status_code})")
        msgs = []
        for item in data.get("data", []):
            n   = _clean_num(item.get("num", ""))
            s   = str(item.get("message", "")).strip()
            d   = str(item.get("dt", ""))
            cli = str(item.get("cli", "")).strip()
            if n and s:
                msgs.append({
                    "id":     _make_ext_id("ts", n, d, s),
                    "number": n, "text": s, "date": d,
                    "source": "timesms", "cli": cli,
                })
        return msgs, "ok"
    except Exception as e:
        return [], str(e)


# ════════════════════════════════════════════════════════════
# SOURCE D  (Hadi — REST API)
# ════════════════════════════════════════════════════════════

CFG_HADI = {
    "name":      "HADI SMS",
    "api_url":   "http://147.135.212.197/crapi/had/viewstats",
    "api_token": "SFZURzRSQl1mb2FZg2GFfUSVmYFyi3JoimqTfX9hg3xZYI9HVINg",
    "timeout":   15,
    "records":   200,
}


def fetch_hadi(days_back=1):
    now = datetime.now()
    params = {
        "token":   CFG_HADI["api_token"],
        "dt1":     (now - timedelta(days=days_back)).strftime("%Y-%m-%d %H:%M:%S"),
        "dt2":     now.strftime("%Y-%m-%d %H:%M:%S"),
        "records": CFG_HADI["records"],
    }
    try:
        r = requests.get(CFG_HADI["api_url"], params=params, timeout=CFG_HADI["timeout"])
        data = r.json()
        if data.get("status") != "success":
            return [], data.get("msg", "API error")
        msgs = []
        for item in data.get("data", []):
            n   = _clean_num(item.get("num", ""))
            s   = str(item.get("message", "")).strip()
            d   = str(item.get("dt", ""))
            cli = str(item.get("cli", "")).strip()
            if n and s and len(n) >= 8:
                msgs.append({
                    "id":     _make_ext_id("hd", n, d, s),
                    "number": n, "text": s, "date": d,
                    "source": "hadi", "cli": cli,
                })
        return msgs, "ok"
    except Exception as e:
        return [], str(e)


# ════════════════════════════════════════════════════════════
# SOURCE E  (Numper — REST API)
# ════════════════════════════════════════════════════════════

CFG_NUMPER = {
    "name":      "Source E",
    "api_url":   "http://147.135.212.197/crapi/st/viewstats",
    "api_token": "R1FPQUVBUzR9ZldHUoyKX3NUl1V1f2pzeml3X1iEg1d3UYp6RFJ2dw==",
    "timeout":   15,
    "records":   500,
}


def fetch_numper(days_back=1):
    now = datetime.now()
    params = {
        "token":   CFG_NUMPER["api_token"],
        "dt1":     (now - timedelta(days=days_back)).strftime("%Y-%m-%d %H:%M:%S"),
        "dt2":     now.strftime("%Y-%m-%d %H:%M:%S"),
        "records": CFG_NUMPER["records"],
    }
    try:
        r = requests.get(CFG_NUMPER["api_url"], params=params, timeout=CFG_NUMPER["timeout"])
        data = r.json()
        msgs = []
        for item in data:
            if isinstance(item, (list, tuple)) and len(item) >= 4:
                cli = _clean_html(item[0])
                n   = _clean_num(item[1])
                s   = _clean_html(item[2])
                d   = _clean_html(item[3])
                if n and s and len(n) >= 8:
                    msgs.append({
                        "id":     _make_ext_id("np", n, d, s),
                        "number": n, "text": s, "date": d,
                        "source": "numper", "cli": cli,
                    })
        return msgs, "ok"
    except Exception as e:
        return [], str(e)


def fetch_supplier_messages(supplier, days_back=1):
    now = datetime.now()
    params = {
        "token":   supplier.api_token,
        "dt1":     (now - timedelta(days=days_back)).strftime("%Y-%m-%d %H:%M:%S"),
        "dt2":     now.strftime("%Y-%m-%d %H:%M:%S"),
        "records": supplier.records or 500,
    }
    try:
        r = requests.get(supplier.api_url, params=params, timeout=supplier.timeout or 15)
        data = r.json()
        msgs = []
        
        if supplier.parser_type == 'nested_list':
            for item in data:
                if isinstance(item, (list, tuple)) and len(item) >= 4:
                    cli = _clean_html(item[0])
                    n   = _clean_num(item[1])
                    s   = _clean_html(item[2])
                    d   = _clean_html(item[3])
                    if n and s and len(n) >= 8:
                        msgs.append({
                            "id":     _make_ext_id("np", n, d, s),
                            "number": n, "text": s, "date": d,
                            "source": supplier.name, "cli": cli,
                        })
        else: # standard
            items = []
            if isinstance(data, dict):
                items = data.get("data", [])
            elif isinstance(data, list):
                items = data
            for item in items:
                if isinstance(item, dict):
                    n   = _clean_num(item.get("num", ""))
                    s   = str(item.get("message", "")).strip()
                    d   = str(item.get("dt", ""))
                    cli = str(item.get("cli", "")).strip()
                    if n and s:
                        msgs.append({
                            "id":     _make_ext_id("dyn", n, d, s),
                            "number": n, "text": s, "date": d,
                            "source": supplier.name, "cli": cli,
                        })
        return msgs, "ok"
    except Exception as e:
        return [], str(e)


# ════════════════════════════════════════════════════════════
# Background Worker
# ════════════════════════════════════════════════════════════

_bg_thread      = None
_bg_running     = False
_bg_lock        = threading.Lock()
_bg_last_run    = None
_bg_last_result = {}


def _background_worker(app):
    global _bg_running, _bg_last_run, _bg_last_result
    with app.app_context():
        while _bg_running:
            try:
                # Check website status first
                from app.models.activity import News
                try:
                    status_setting = News.query.filter_by(title='website_status').first()
                    if status_setting and status_setting.content == 'offline':
                        # If website is offline, skip background polling to save resources
                        time.sleep(30)
                        continue
                except Exception:
                    pass

                all_msgs = []
                statuses = {}
                
                from app.models.sms import SMSSupplier
                suppliers = SMSSupplier.query.filter_by(is_active=True).all()
                
                if suppliers:
                    for s in suppliers:
                        try:
                            msgs, st = fetch_supplier_messages(s)
                            all_msgs.extend(msgs)
                            statuses[s.name] = {"count": len(msgs), "status": st}
                        except Exception as e:
                            statuses[s.name] = {"count": 0, "status": str(e)}
                else:
                    # Fallback
                    for label, fn in [
                        ("timesms", fetch_timesms),
                        ("hadi",    fetch_hadi),
                        ("numper",  fetch_numper),
                    ]:
                        try:
                            msgs, st = fn()
                            all_msgs.extend(msgs)
                            statuses[label] = {"count": len(msgs), "status": st}
                        except Exception as e:
                            statuses[label] = {"count": 0, "status": str(e)}

                result = forward_to_reserved(all_msgs)
                _bg_last_run    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                _bg_last_result = {
                    "fetched":    len(all_msgs),
                    "forwarded":  result["forwarded"],
                    "skipped":    result["skipped"],
                    "duplicate":  result["duplicate"],
                    "sources":    statuses,
                    "timestamp":  _bg_last_run,
                }
            except Exception as e:
                print(f"[BG Worker] unexpected error: {e}")
            time.sleep(30)


def start_background_worker(app):
    global _bg_thread, _bg_running
    with _bg_lock:
        if _bg_thread is not None and _bg_thread.is_alive():
            return
        _bg_running = True
        _bg_thread  = threading.Thread(
            target=_background_worker, args=(app,), daemon=True, name="sms-monitor-bg"
        )
        _bg_thread.start()
        print("[Monitor] Background worker started ✅")


# ════════════════════════════════════════════════════════════
# Forwarder
# ════════════════════════════════════════════════════════════

def forward_to_reserved(messages):
    if not messages:
        return {"forwarded": 0, "skipped": 0, "duplicate": 0}

    existing = set(
        r[0] for r in db.session.query(SMSCDR.caller_id)
              .filter(SMSCDR.sms_type == "received",
                      SMSCDR.caller_id.isnot(None)).all()
    )

    forwarded = skipped = duplicate = 0
    total_earned = 0.0

    newly_created_cdrs = []

    for msg in messages:
        ext_id = msg.get("id", "")
        if ext_id in existing:
            duplicate += 1
            continue

        raw_num = msg.get("number", "")
        if not raw_num:
            skipped += 1
            continue

        sms_num = SMSNumber.query.filter_by(number=raw_num, is_active=True).first()
        if not sms_num and len(raw_num) >= 9:
            suffix  = raw_num[-9:]
            sms_num = SMSNumber.query.filter(
                SMSNumber.number.like(f"%{suffix}"),
                SMSNumber.is_active == True
            ).first()

        # Requirement: "اللوحه هتسحب الرسائل اللي بتجيلها فقط يعني ما يسحبش اي رسائل بتكون موجوده في الحساب المورد"
        # Skip/discard any incoming messages that are NOT destined for numbers active/registered in our panel.
        if not sms_num:
            skipped += 1
            continue

        # Requirement: "واجل اي رنجات تجريبيه او اي ارقام تجريبيه او اي عمليات تجريبيه تمام"
        # Skip any messages for ranges or numbers that are marked trial, test, or inactive.
        if sms_num.sms_range and (not sms_num.sms_range.is_active or 
                                  any(kw in (sms_num.sms_range.name or "").lower() for kw in ["test", "trial", "sandbox", "fake", "mock", "تجريب", "تجرب"])):
            skipped += 1
            continue

        if any(kw in (sms_num.operator or "").lower() for kw in ["test", "trial", "sandbox", "fake", "mock", "تجريب", "تجرب"]) or \
           any(kw in (sms_num.number or "").lower() for kw in ["test", "trial"]):
            skipped += 1
            continue

        app_cli = (msg.get("cli") or "").strip()

        # Match and route message directly to the account that owns/contains these numbers
        number_id_val     = sms_num.id
        range_id_val      = sms_num.range_id
        user_id_val       = sms_num.agent_id
        client_id_val     = sms_num.client_id
        
        # Pull payouts defined on the number record
        agent_payout_val  = sms_num.agent_payout if sms_num.agent_payout is not None else 0.007
        client_payout_val = sms_num.client_payout if sms_num.client_payout is not None else 0.005

        from app.models.user import User
        
        # Credit the Agent account owning this number
        if user_id_val:
            user = User.query.get(user_id_val)
            if user:
                # Admin and test accounts should not accumulate balance/earnings
                effective_agent_payout = 0.0 if (user.is_admin() or user.is_test_account()) else agent_payout_val
                user.balance = (user.balance or 0.0) + effective_agent_payout
                user.total_earned = (user.total_earned or 0.0) + effective_agent_payout
                total_earned += effective_agent_payout

        # Credit the Client account using this number
        if client_id_val:
            client_user = User.query.get(client_id_val)
            if client_user:
                # Admin and test accounts should not accumulate balance/earnings
                effective_client_payout = 0.0 if (client_user.is_admin() or client_user.is_test_account()) else client_payout_val
                client_user.balance = (client_user.balance or 0.0) + effective_client_payout
                client_user.total_earned = (client_user.total_earned or 0.0) + effective_client_payout

        # Platform/Agent Profit per message
        profit_val = max(0.0, agent_payout_val - client_payout_val) if client_id_val else agent_payout_val

        cdr = SMSCDR(
            number_id     = number_id_val,
            range_id      = range_id_val,
            user_id       = user_id_val,
            client_id     = client_id_val,
            caller_id     = ext_id,
            destination   = raw_num,
            cli           = app_cli,
            message       = msg.get("text", ""),
            sms_type      = "received",
            status        = "completed",
            profit        = profit_val,
            agent_payout  = agent_payout_val,
            client_payout = client_payout_val,
            currency      = "USD",
        )
        db.session.add(cdr)
        newly_created_cdrs.append(cdr)
        existing.add(ext_id)
        forwarded += 1

    if forwarded:
        db.session.commit()
        
        # Sync newly saved CDRs and updated accounts/clients to Firebase Firestore (optional, runs in parallel to SQLite hosting database)
        try:
            from app.firebase_helper import sync_cdr_to_firebase, sync_client_to_firebase
            from app.models.user import User
            for cdr_obj in newly_created_cdrs:
                sync_cdr_to_firebase(cdr_obj)
                if cdr_obj.user_id:
                    u = User.query.get(cdr_obj.user_id)
                    if u:
                        sync_client_to_firebase(u)
                if cdr_obj.client_id:
                    c = User.query.get(cdr_obj.client_id)
                    if c:
                        sync_client_to_firebase(c)
        except Exception as fe:
            print(f"[Firebase Sync] Error syncing message logs to Firebase: {fe}")

        # Forward test123 incoming messages to Telegram group/channel
        try:
            from app.models.user import User
            from app.models.activity import News
            test123_user = User.query.filter_by(username='test123').first()
            if test123_user:
                test123_enabled = News.query.filter_by(title='test123_enabled').first()
                if test123_enabled and test123_enabled.content == 'true':
                    bot_token_setting = News.query.filter_by(title='test123_bot_token').first()
                    channel_id_setting = News.query.filter_by(title='test123_channel_id').first()
                    
                    if bot_token_setting and channel_id_setting and bot_token_setting.content and channel_id_setting.content:
                        bot_token = bot_token_setting.content
                        channel_id = channel_id_setting.content
                        
                        for cdr_obj in newly_created_cdrs:
                            # Only forward if the message belongs to test123_user (as agent) or their client accounts
                            if cdr_obj.user_id == test123_user.id or cdr_obj.client_id == test123_user.id:
                                sms_num = SMSNumber.query.get(cdr_obj.number_id)
                                range_name = sms_num.sms_range.name if (sms_num and sms_num.sms_range) else "رينج_غير_معروف"
                                
                                # Only mask the last 3 digits with XXX as requested
                                dest = str(cdr_obj.destination or "")
                                if len(dest) >= 3:
                                    masked_num = dest[:-3] + "XXX"
                                else:
                                    masked_num = "XXX"
                                
                                # HTML monospaced formatting using <code> makes the range name clickable to copy instantly in Telegram
                                telegram_msg = (
                                    f"<code>{range_name}</code>\n"
                                    f"{masked_num}\n"
                                    f"{cdr_obj.message}"
                                )
                                
                                import requests
                                tel_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                                requests.post(tel_url, json={
                                    "chat_id": channel_id,
                                    "text": telegram_msg,
                                    "parse_mode": "HTML"
                                }, timeout=5)
                                print(f"[TELEGRAM FORWARD] Sent test123/client SMS to Telegram group {channel_id}")
        except Exception as te:
            print(f"[TELEGRAM FORWARD] Error forwarding message to Telegram: {te}")

    return {
        "forwarded": forwarded,
        "skipped": skipped,
        "duplicate": duplicate,
        "total_earned": round(total_earned, 4)
    }



# ════════════════════════════════════════════════════════════
# Routes
# ════════════════════════════════════════════════════════════

@monitor_bp.route("/")
@login_required
@admin_required
def index():
    received = SMSCDR.query.filter_by(sms_type="received") \
                           .order_by(SMSCDR.created_at.desc()).limit(50).all()
    today       = datetime.utcnow().date()
    today_count = SMSCDR.query.filter_by(sms_type="received") \
                              .filter(db.func.date(SMSCDR.created_at) == today).count()
    total_count = SMSCDR.query.filter_by(sms_type="received").count()

    sources_info = [
        {"key": "abyss",   "label": "Volt SMS", "type": "Session"},
        {"key": "panel4",  "label": "Source A", "type": "Session"},
        {"key": "panel4_2", "label": "Source A 2", "type": "Session"},
        {"key": "timesms", "label": "Source C", "type": "API Token",
         "token_masked": _mask_token(CFG_TS["api_token"]),
         "token_full":   CFG_TS["api_token"]},
        {"key": "hadi",    "label": "HADI SMS", "type": "API Token",
         "token_masked": _mask_token(CFG_HADI["api_token"]),
         "token_full":   CFG_HADI["api_token"]},
        {"key": "numper",  "label": "Source E", "type": "API Token",
         "token_masked": _mask_token(CFG_NUMPER["api_token"]),
         "token_full":   CFG_NUMPER["api_token"]},
    ]

    return render_template("admin/sms_monitor.html",
                           received=received,
                           today_count=today_count,
                           total_count=total_count,
                           sources_info=sources_info,
                           bg_last_run=_bg_last_run,
                           bg_last_result=_bg_last_result)


@monitor_bp.route("/run", methods=["POST"])
@login_required
@admin_required
def run_cycle():
    source   = request.form.get("source", "all")
    messages = []
    statuses = {}

    if source in ("all", "abyss"):
        msgs, st = fetch_abyss()
        messages.extend(msgs)
        statuses["abyss"] = {"count": len(msgs), "status": st}

    if source in ("all", "panel4"):
        msgs, st = fetch_panel4()
        messages.extend(msgs)
        statuses["panel4"] = {"count": len(msgs), "status": st}

    if source in ("all", "panel4_2"):
        msgs, st = fetch_panel4_2()
        messages.extend(msgs)
        statuses["panel4_2"] = {"count": len(msgs), "status": st}

    if source in ("all", "timesms"):
        msgs, st = fetch_timesms()
        messages.extend(msgs)
        statuses["timesms"] = {"count": len(msgs), "status": st}

    if source in ("all", "hadi"):
        msgs, st = fetch_hadi()
        messages.extend(msgs)
        statuses["hadi"] = {"count": len(msgs), "status": st}

    if source in ("all", "numper"):
        msgs, st = fetch_numper()
        messages.extend(msgs)
        statuses["numper"] = {"count": len(msgs), "status": st}

    result = forward_to_reserved(messages)
    return jsonify({
        "status": "success",
        "fetched": len(messages),
        "forwarded": result["forwarded"],
        "skipped": result["skipped"],
        "duplicate": result["duplicate"],
        "sources": statuses
    })


@monitor_bp.route("/debug/<source>")
@login_required
@admin_required
def debug_source(source):
    if source == "abyss": msgs, st = fetch_abyss()
    elif source == "panel4": msgs, st = fetch_panel4()
    elif source == "panel4_2": msgs, st = fetch_panel4_2()
    elif source == "timesms": msgs, st = fetch_timesms()
    elif source == "hadi": msgs, st = fetch_hadi()
    elif source == "numper": msgs, st = fetch_numper()
    else: return jsonify({"error": "Unknown source"}), 400
    
    return jsonify({
        "source": source,
        "status": st,
        "count": len(msgs),
        "sample": msgs[:3]
    })


# ════════════════════════════════════════════════════════════
# Additional Routes (MISSING - FIXED)
# ════════════════════════════════════════════════════════════

@monitor_bp.route("/messages")
@login_required
@admin_required
def get_messages():
    """Get recent messages for AJAX refresh"""
    limit = request.args.get('limit', 50, type=int)
    today = datetime.utcnow().date()

    messages = SMSCDR.query.filter_by(sms_type="received") \
                          .order_by(SMSCDR.created_at.desc()) \
                          .limit(limit).all()

    result = []
    for m in messages:
        result.append({
            'id': m.id,
            'date': m.created_at.strftime('%Y-%m-%d %H:%M:%S') if m.created_at else '—',
            'number': m.sms_number.number if m.sms_number else (m.destination or '—'),
            'cli': m.cli or '',
            'message': m.message or '',
            'agent': m.sms_number.agent.username if (m.sms_number and m.sms_number.agent) else '—'
        })

    today_count = SMSCDR.query.filter_by(sms_type="received") \
                              .filter(db.func.date(SMSCDR.created_at) == today).count()
    total_count = SMSCDR.query.filter_by(sms_type="received").count()

    return jsonify({
        'success': True,
        'messages': result,
        'today_count': today_count,
        'total_count': total_count
    })


@monitor_bp.route("/status")
@login_required
@admin_required
def get_status():
    """Get connection status for all sources"""
    global _abyss_logged_in, _p4_logged_in, _p4_2_logged_in

    return jsonify({
        'abyss':    {'type': 'session', 'logged_in': bool(_abyss_logged_in)},
        'panel4':  {'type': 'session', 'logged_in': bool(_p4_logged_in)},
        'panel4_2': {'type': 'session', 'logged_in': bool(_p4_2_logged_in)},
        'timesms': {'type': 'api_token'},
        'hadi':    {'type': 'api_token'},
        'numper':  {'type': 'api_token'},
    })
