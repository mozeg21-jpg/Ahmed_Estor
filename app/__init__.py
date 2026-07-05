import os
import secrets
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from config import config

from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
login_manager = LoginManager()
bcrypt = Bcrypt()

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    # Enable WAL mode for SQLite to prevent locking issues under concurrent serverless requests
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
    except Exception:
        pass

# Security headers added to every response
SECURITY_HEADERS = {
    'X-Content-Type-Options':  'nosniff',
    'X-Frame-Options':         'ALLOWALL',
    'X-XSS-Protection':        '1; mode=block',
    'Referrer-Policy':         'strict-origin-when-cross-origin',
    'Permissions-Policy':      'geolocation=(), microphone=()',
    'Content-Security-Policy': (
        "default-src 'self' https:; "
        "script-src 'self' 'unsafe-inline' https:; "
        "style-src 'self' 'unsafe-inline' https:; "
        "img-src 'self' data: https:; "
        "font-src 'self' data: https:; "
        "media-src 'self' https: data:; "
        "frame-ancestors *;"
    ),
}


def create_app(config_name='default'):
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    db.init_app(app)
    login_manager.init_app(app)
    bcrypt.init_app(app)

    # ── CORS: only allow explicitly configured origins ──────────────────────
    allowed_origins = app.config.get('CORS_ORIGINS') or []
    if allowed_origins:
        CORS(app, origins=allowed_origins, supports_credentials=True)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.session_protection = 'basic'

    @login_manager.user_loader
    def load_user(user_id):
        from app.models.user import User
        return User.query.get(int(user_id))

    @app.context_processor
    def inject_now():
        from datetime import datetime
        return {'datetime': datetime}

    # ── Jinja2 Filters ──────────────────────────────────────────────────────────
    @app.template_filter('mask_last_7')
    def mask_last_7(value):
        """Mask last 7 digits of phone number with X"""
        if not value:
            return ''
        value = str(value)
        if len(value) >= 7:
            return value[:-7] + 'X' * 7
        return 'X' * len(value)

    @app.template_filter('mask_last_6')
    def mask_last_6(value):
        """Mask last 6 characters with X"""
        if not value:
            return ''
        value = str(value)
        if len(value) >= 6:
            return value[:-6] + 'X' * 6
        return 'X' * len(value)

    # ── Security headers on every response ──────────────────────────────────
    @app.after_request
    def add_security_headers(response):
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value
        return response



    @app.before_request
    def check_maintenance_mode():
        from app.models.activity import News
        from flask_login import current_user
        from flask import request, render_template
        try:
            status_setting = News.query.filter_by(title='website_status').first()
            if status_setting and status_setting.content == 'offline':
                path = request.path
                if (path.startswith('/admin') or 
                    path.startswith('/static') or 
                    path.startswith('/login') or 
                    path.startswith('/logout') or
                    path == '/ints/agent/res/data_smscdr.php' or
                    (current_user.is_authenticated and current_user.is_admin())):
                    return None
                
                maintenance_msg = "الموقع تحت الصيانة حالياً. يرجى المحاولة لاحقاً."
                msg_setting = News.query.filter_by(title='maintenance_message').first()
                if msg_setting and msg_setting.content:
                    maintenance_msg = msg_setting.content
                    
                return render_template('main/maintenance.html', message=maintenance_msg), 503
        except Exception:
            pass

    from app.routes.auth import auth_bp
    from app.routes.main import main_bp
    from app.routes.admin import admin_bp
    from app.routes.sms_monitor import monitor_bp
    from app.routes.developer import dev_bp
    from app.routes.honeypot import honeypot_bp
    from app.routes.tts import tts_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(monitor_bp)
    app.register_blueprint(dev_bp)
    app.register_blueprint(honeypot_bp)
    app.register_blueprint(tts_bp)

    # Background worker moved to the very end of create_app to ensure database is fully ready

    with app.app_context():
        from app.models.finance import BankAccount, PaymentRequest, CreditNote
        db.create_all()

        # ── Auto-migrate ────────────────────────────────────────────────────
        try:
            from sqlalchemy import text, inspect as sa_inspect
            inspector = sa_inspect(db.engine)
            tables = inspector.get_table_names()

            if 'sms_ranges' in tables:
                try:
                    range_cols = [c['name'] for c in inspector.get_columns('sms_ranges')]
                    if 'application' not in range_cols:
                        db.session.execute(text("ALTER TABLE sms_ranges ADD COLUMN application VARCHAR(50)"))
                        db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    print(f"[MIGRATION] Bypassed sms_ranges application column: {e}")

            if 'sms_cdr' in tables:
                try:
                    cdr_cols = [c['name'] for c in inspector.get_columns('sms_cdr')]
                    if 'caller_id' not in cdr_cols:
                        db.session.execute(text("ALTER TABLE sms_cdr ADD COLUMN caller_id VARCHAR(50)"))
                        db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    print(f"[MIGRATION] Bypassed sms_cdr caller_id column: {e}")

            # ── Honeypot log table ──────────────────────────────────────────
            if 'honeypot_logs' not in tables:
                try:
                    id_type = "id INTEGER PRIMARY KEY AUTOINCREMENT"
                    if db.engine.name == 'postgresql':
                        id_type = "id SERIAL PRIMARY KEY"
                    elif db.engine.name == 'mysql':
                        id_type = "id INT AUTO_INCREMENT PRIMARY KEY"
                    
                    db.session.execute(text(f"""
                        CREATE TABLE honeypot_logs (
                            {id_type},
                            ip TEXT NOT NULL,
                            path TEXT NOT NULL,
                            method TEXT NOT NULL,
                            user_agent TEXT,
                            body TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """))
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    print(f"[MIGRATION] Bypassed honeypot_logs creation: {e}")

            # ── Add title column to news table ──────────────────────────────
            if 'news' in tables:
                try:
                    news_cols = [c['name'] for c in inspector.get_columns('news')]
                    if 'title' not in news_cols:
                        db.session.execute(text("ALTER TABLE news ADD COLUMN title VARCHAR(200)"))
                        db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    print(f"[MIGRATION] Bypassed news title column: {e}")

            # ── Add telegram columns to users table ─────────────────────────
            if 'users' in tables:
                try:
                    user_cols = [c['name'] for c in inspector.get_columns('users')]
                    
                    if 'telegram_bot_token' not in user_cols:
                        try:
                            db.session.execute(text("ALTER TABLE users ADD COLUMN telegram_bot_token VARCHAR(255)"))
                            db.session.commit()
                        except Exception as ex:
                            db.session.rollback()
                            print(f"[MIGRATION] Failed adding telegram_bot_token: {ex}")

                    if 'telegram_chat_id' not in user_cols:
                        try:
                            db.session.execute(text("ALTER TABLE users ADD COLUMN telegram_chat_id VARCHAR(100)"))
                            db.session.commit()
                        except Exception as ex:
                            db.session.rollback()
                            print(f"[MIGRATION] Failed adding telegram_chat_id: {ex}")

                    if 'telegram_enabled' not in user_cols:
                        try:
                            # Use BOOLEAN DEFAULT FALSE (works for Postgres, SQLite, and MySQL)
                            db.session.execute(text("ALTER TABLE users ADD COLUMN telegram_enabled BOOLEAN DEFAULT FALSE"))
                            db.session.commit()
                        except Exception as ex:
                            db.session.rollback()
                            try:
                                # Fallback to generic representation
                                db.session.execute(text("ALTER TABLE users ADD COLUMN telegram_enabled BOOLEAN DEFAULT '0'"))
                                db.session.commit()
                            except Exception as ex2:
                                db.session.rollback()
                                print(f"[MIGRATION] Failed adding telegram_enabled: {ex2}")
                except Exception as e:
                    print(f"[MIGRATION] Bypassed users telegram column checks: {e}")

        except Exception as e:
            print(f"[MIGRATION] Bypassed auto-migrate: {e}")

        from app.models.user import User, Role
        from app.models.sms import SMDRange
        from app.models.developer import StaticAsset

        # ── Create Roles & Seeding (Wrapped to prevent concurrent execution crashes) ─────────────────
        try:
            for role_name, display in [('admin', 'Administrator'), ('agent', 'Agent'),
                                        ('client', 'Client'), ('developer', 'Developer')]:
                if not Role.query.filter_by(name=role_name).first():
                    db.session.add(Role(name=role_name, display_name=display))
            db.session.commit()

            admin_role = Role.query.filter_by(name='admin').first()
            client_role = Role.query.filter_by(name='client').first()

            # ── Admin account ────────────────────────────────────────────────────
            # Default password is "admin123" (can be changed via ADMIN_PASSWORD env var)
            admin = User.query.filter_by(username='admin').first()
            if not admin:
                admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
                admin = User(
                    username='admin',
                    email='admin@system.local',
                    role=admin_role,
                    is_active=True,
                )
                admin.set_password(admin_password)
                admin.generate_api_token()
                db.session.add(admin)
                db.session.commit()
                print("=" * 60)
                print("[SYSTEM] Admin account created.")
                print(f"  Username: admin")
                print(f"  Password: {admin_password}")
                print("=" * 60)

            # ── Test123 account (special account for OTP masking) ────────────────
            test123 = User.query.filter_by(username='test123').first()
            if not test123:
                test123 = User(
                    username='test123',
                    email='test123@system.local',
                    role=client_role,
                    is_active=True,
                )
                test123.set_password('test123')
                test123.generate_api_token()
                db.session.add(test123)
                db.session.commit()
                print("[SYSTEM] Test account created: test123 / test123")

            # ── Create default SMS ranges with price 0.007 ──────────────────────
            if SMDRange.query.count() == 0:
                sample_ranges = [
                    SMDRange(name='United States', country='United States', operator='AT&T',
                             network_type='GSM', mcc='310', mnc='410',
                             currency='USD', rate=0.007, cost_per_sms=0.007,
                             memo='United States SMS', test_number='12025551234', is_active=True,
                             billing_cycle='monthly', manual_price=5.0),
                    SMDRange(name='United Kingdom', country='United Kingdom', operator='Vodafone',
                             network_type='GSM', mcc='234', mnc='15',
                             currency='GBP', rate=0.007, cost_per_sms=0.007,
                             memo='UK SMS', test_number='447911123456', is_active=True,
                             billing_cycle='monthly', manual_price=4.0),
                    SMDRange(name='Germany', country='Germany', operator='Deutsche Telekom',
                             network_type='GSM', mcc='262', mnc='1',
                             currency='EUR', rate=0.007, cost_per_sms=0.007,
                             memo='Germany SMS', test_number='4915112345678', is_active=True,
                             billing_cycle='monthly', manual_price=4.0),
                ]
                for r in sample_ranges:
                    db.session.add(r)
                db.session.commit()

            # ── Create default SMS suppliers ────────────────────────────────────
            from app.models.sms import SMSSupplier
            if SMSSupplier.query.count() == 0:
                sample_suppliers = [
                    SMSSupplier(name='Timesms',
                                api_url='http://147.135.212.197/crapi/ts/viewstats',
                                api_token='RVRVNEVBmIGEiZZbeIyOZXWFg1l5UYJIeGdpa2d2bmKDZmNcXlU=',
                                parser_type='standard', timeout=15, records=500, is_active=True),
                    SMSSupplier(name='HADI SMS',
                                api_url='http://147.135.212.197/crapi/had/viewstats',
                                api_token='SFZURzRSQl1mb2FZg2GFfUSVmYFyi3JoimqTfX9hg3xZYI9HVINg',
                                parser_type='standard', timeout=15, records=200, is_active=True),
                    SMSSupplier(name='Source E',
                                api_url='http://147.135.212.197/crapi/st/viewstats',
                                api_token='R1FPQUVBUzR9ZldHUoyKX3NUl1V1f2pzeml3X1iEg1d3UYp6RFJ2dw==',
                                parser_type='nested_list', timeout=15, records=500, is_active=True),
                ]
                for s in sample_suppliers:
                    db.session.add(s)
                db.session.commit()
                print("[SYSTEM] Default SMS suppliers seeded.")
        except Exception as e:
            db.session.rollback()
            print(f"[SYSTEM] Seeding bypassed or concurrent execution detected: {e}")

    # ── Safe background worker start ─────────────────────────────────────────
    # We trigger the background worker thread ONLY after the app context and DB are fully ready
    if not (os.environ.get('VERCEL') == '1' or os.environ.get('VERCEL_ENV')):
        try:
            from app.routes.sms_monitor import start_background_worker
            start_background_worker(app)
        except Exception as e:
            print(f"[SYSTEM] Failed to start background worker: {e}")

    return app
