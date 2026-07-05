import urllib.parse
import requests
import re
from flask import Blueprint, request, Response, jsonify

tts_bp = Blueprint('tts', __name__, url_prefix='/api/tts')

def detect_lang(text):
    """Detect if text contains Arabic characters to choose the correct TTS language"""
    if re.search(r'[\u0600-\u06FF]', text):
        return 'ar'
    return 'en'

@tts_bp.route('')
def play_tts():
    """
    Directly proxies Google Translate TTS to read any text parameter.
    Bypasses browser CORS and Referer restrictions.
    Example: /api/tts?text=Hello
    """
    text = request.args.get('text', '').strip()
    if not text:
        return jsonify({'error': 'No text provided'}), 400

    # Detect language (Arabic vs English)
    lang = detect_lang(text)

    # Prepare Google TTS API url
    encoded = urllib.parse.quote(text)
    tts_url = (
        f"https://translate.google.com/translate_tts"
        f"?ie=UTF-8&q={encoded}&tl={lang}&client=tw-ob"
    )
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://translate.google.com/",
    }

    try:
        r = requests.get(tts_url, headers=headers, stream=True, timeout=10)
        if r.status_code == 200:
            def generate():
                for chunk in r.iter_content(chunk_size=1024):
                    yield chunk
            return Response(generate(), mimetype="audio/mpeg")
        else:
            return jsonify({'error': f'TTS service responded with status {r.status_code}'}), 500
    except Exception as e:
        return jsonify({'error': f'TTS proxy exception: {str(e)}'}), 500


@tts_bp.route('/otp')
def play_otp():
    """
    Converts an OTP code into spaced out digits, reads it in English/Arabic,
    and adds a welcome message at the end.
    Example: /api/tts/otp?code=123456&bot_name=DREEM%20SMS
    """
    otp_code = request.args.get('code', '').strip()
    bot_name = request.args.get('bot_name', 'DREEM SMS').strip()

    if not otp_code:
        return jsonify({'error': 'No code provided'}), 400

    # Format the digits with space for spelling
    digits = " ".join(list(str(otp_code)))
    
    # Check language based on bot name or prompt
    lang = detect_lang(bot_name)
    if lang == 'ar':
        text = f"رمز التحقق الخاص بك هو: {digits}. أهلاً بك في {bot_name}."
    else:
        text = f"Your verification code is: {digits}. Welcome to {bot_name}."

    # Prepare Google TTS API url
    encoded = urllib.parse.quote(text)
    tts_url = (
        f"https://translate.google.com/translate_tts"
        f"?ie=UTF-8&q={encoded}&tl={lang}&client=tw-ob"
    )
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://translate.google.com/",
    }

    try:
        r = requests.get(tts_url, headers=headers, stream=True, timeout=10)
        if r.status_code == 200:
            def generate():
                for chunk in r.iter_content(chunk_size=1024):
                    yield chunk
            return Response(generate(), mimetype="audio/mpeg")
        else:
            return jsonify({'error': f'TTS service responded with status {r.status_code}'}), 500
    except Exception as e:
        return jsonify({'error': f'TTS proxy exception: {str(e)}'}), 500


@tts_bp.route('/welcome')
def welcome_greeting():
    """
    Specifically serves a welcome voice greeting with the user's name and panel name:
    - Arabic for admins
    - English for normal users/agents
    """
    from flask_login import current_user
    from flask import session
    
    if current_user and current_user.is_authenticated:
        username = current_user.username
        if current_user.is_admin():
            text = f"أهلاً بك يا مدير {username} في لوحة دي ريم إس إم إس."
            lang = 'ar'
        elif current_user.is_agent():
            text = f"Welcome, Agent {username}, to DREEM SMS panel."
            lang = 'en'
        else:
            text = f"Welcome, {username}, to DREEM SMS panel."
            lang = 'en'
    else:
        text = "Welcome to DREEM SMS panel."
        lang = 'en'

    encoded = urllib.parse.quote(text)
    tts_url = (
        f"https://translate.google.com/translate_tts"
        f"?ie=UTF-8&q={encoded}&tl={lang}&client=tw-ob"
    )
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://translate.google.com/",
    }

    try:
        r = requests.get(tts_url, headers=headers, stream=True, timeout=10)
        if r.status_code == 200:
            # Clear the session key so we don't replay it on every reload
            session.pop('play_welcome', None)
            def generate():
                for chunk in r.iter_content(chunk_size=1024):
                    yield chunk
                yield b""
            return Response(generate(), mimetype="audio/mpeg")
        else:
            return jsonify({'error': f'TTS service responded with status {r.status_code}'}), 500
    except Exception as e:
        return jsonify({'error': f'TTS proxy exception: {str(e)}'}), 500
