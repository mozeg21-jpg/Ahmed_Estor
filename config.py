import os
import secrets
from datetime import timedelta
from dotenv import load_dotenv
load_dotenv()  # Load .env file if it exists


class Config:
    # ── Secret key ──────────────────────────────────────────────────────────
    # MUST be set via environment variable in production.
    SECRET_KEY = os.environ.get('SECRET_KEY') or "dreemsms_stable_secret_key"

    # ── Database ─────────────────────────────────────────────────────────────
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get('DATABASE_URL') or 
        ('sqlite:////tmp/dreem_sms.db' if (os.environ.get('VERCEL') == '1' or os.environ.get('VERCEL_ENV')) else 'sqlite:///dreem_sms.db')
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ── Session & Cookies ────────────────────────────────────────────────────
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_COOKIE_SECURE   = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'None'

    # ── CSRF ────────────────────────────────────────────────────────────────
    WTF_CSRF_ENABLED    = True
    WTF_CSRF_TIME_LIMIT = 3600

    # ── Rate limiting ────────────────────────────────────────────────────────
    LOGIN_ATTEMPT_LIMIT  = 5
    LOGIN_ATTEMPT_WINDOW = 300

    # ── Registration ─────────────────────────────────────────────────────────
    # Set REGISTRATION_ENABLED=true in env to allow public self-registration.
    REGISTRATION_ENABLED = os.environ.get('REGISTRATION_ENABLED', 'true').lower() == 'true'

    # ── Webhook secret ───────────────────────────────────────────────────────
    # The SMS gateway must send this as X-Webhook-Secret header.
    WEBHOOK_SECRET = os.environ.get('WEBHOOK_SECRET', '')

    # ── Telegram Bot API Secret ─────────────────────────────────────────────
    # Secret for Telegram bot to access admin API endpoints
    BOT_API_SECRET = os.environ.get('BOT_API_SECRET', 'bot_secret_key_12345')

    # ── Bulk SMS cap ─────────────────────────────────────────────────────────
    BULK_SMS_MAX_DESTINATIONS = int(os.environ.get('BULK_SMS_MAX_DESTINATIONS', '500'))

    # ── CORS whitelist ───────────────────────────────────────────────────────
    CORS_ORIGINS = [
        o.strip()
        for o in os.environ.get('CORS_ORIGINS', '').split(',')
        if o.strip()
    ]


class DevelopmentConfig(Config):
    DEBUG = True
    # We need Secure cookies for SameSite=None to work in AI Studio

class ProductionConfig(Config):
    DEBUG = False
    # For production, set to True and configure HTTPS
    # SESSION_COOKIE_SECURE is True in base Config

class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


config = {
    'development': DevelopmentConfig,
    'production':  ProductionConfig,
    'testing':     TestingConfig,
    'default':     DevelopmentConfig,
}
