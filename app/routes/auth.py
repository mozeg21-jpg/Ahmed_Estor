from flask import Blueprint, render_template, redirect, url_for, request, flash, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models.user import User
from app.models.activity import ActivityLog
from datetime import datetime, timedelta
from functools import wraps
import re
import random
from itsdangerous import Signer, BadSignature

auth_bp = Blueprint('auth', __name__)


# ── Rate limiting (in-memory, per IP) ────────────────────────────────────────
_rate_limit_store: dict = {}   # { key: (attempts, first_attempt) }


def _check_rate_limit(ip: str, window: int = 300, max_attempts: int = 5) -> bool:
    """Return True if the IP is within allowed attempts, False if blocked."""
    key = f'login:{ip}'
    now = datetime.utcnow()

    if key in _rate_limit_store:
        attempts, first = _rate_limit_store[key]
        if now - first < timedelta(seconds=window):
            if attempts >= max_attempts:
                return False
            _rate_limit_store[key] = (attempts + 1, first)
        else:
            _rate_limit_store[key] = (1, now)
    else:
        _rate_limit_store[key] = (1, now)
    return True


def _reset_rate_limit(ip: str):
    key = f'login:{ip}'
    _rate_limit_store.pop(key, None)


def _generate_captcha_token(num1: int, num2: int) -> str:
    s = Signer(current_app.config['SECRET_KEY'])
    payload = f"{num1}:{num2}:{num1+num2}"
    return s.sign(payload.encode('utf-8')).decode('utf-8')


def _verify_captcha_token(token: str, user_answer: str) -> bool:
    if not token or not user_answer:
        return False
    s = Signer(current_app.config['SECRET_KEY'])
    try:
        unsigned = s.unsign(token.encode('utf-8')).decode('utf-8')
        parts = unsigned.split(':')
        if len(parts) != 3:
            return False
        correct_answer = int(parts[2])
        return int(user_answer) == correct_answer
    except (BadSignature, ValueError, TypeError):
        return False


def _refresh_captcha():
    session['captcha_num1']  = random.randint(1, 9)
    session['captcha_num2']  = random.randint(1, 9)
    session['captcha_answer'] = session['captcha_num1'] + session['captcha_num2']


# ── Routes ────────────────────────────────────────────────────────────────────

@auth_bp.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.is_admin():
            return redirect(url_for('admin.index'))
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.is_admin():
            return redirect(url_for('admin.index'))
        return redirect(url_for('main.dashboard'))

    num1 = random.randint(1, 9)
    num2 = random.randint(1, 9)
    captcha_token = _generate_captcha_token(num1, num2)

    if request.method == 'POST':
        ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()

        # IP-level rate limit
        if not _check_rate_limit(ip):
            flash('Too many login attempts from your IP. Please wait 5 minutes.', 'danger')
            return render_template('auth/login.html', num1=num1, num2=num2, captcha_token=captcha_token)

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        captcha  = request.form.get('capt', '')
        form_token = request.form.get('captcha_token', '')

        if not username or not password:
            flash('Please enter username and password.', 'danger')
            return render_template('auth/login.html', num1=num1, num2=num2, captcha_token=captcha_token)

        # Verify captcha using our signed token
        if not _verify_captcha_token(form_token, captcha):
            flash('Incorrect captcha answer.', 'danger')
            return render_template('auth/login.html', num1=num1, num2=num2, captcha_token=captcha_token)

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            if not user.is_active:
                flash('Your account has been deactivated.', 'warning')
                return render_template('auth/login.html', num1=num1, num2=num2, captcha_token=captcha_token)

            if user.locked_until and user.locked_until > datetime.utcnow():
                remaining = int((user.locked_until - datetime.utcnow()).total_seconds() // 60)
                flash(f'Account locked for {remaining} more minute(s).', 'danger')
                return render_template('auth/login.html', num1=num1, num2=num2, captcha_token=captcha_token)

            if not user.api_token:
                user.generate_api_token()

            user.login_attempts = 0
            user.locked_until   = None
            user.last_login     = datetime.utcnow()
            db.session.commit()

            _reset_rate_limit(ip)

            ActivityLog.log(
                user.id, 'login', 'User logged in',
                ip_address=ip, user_agent=request.user_agent.string
            )

            login_user(user, remember=True)
            session.permanent = True
            session['play_welcome'] = True

            flash(f'Welcome {user.username}!', 'success')

            next_page = request.args.get('next')
            if next_page and next_page.startswith('/') and not next_page.startswith('//'):
                return redirect(next_page)
            if user.is_admin():
                return redirect(url_for('admin.index'))
            return redirect(url_for('main.dashboard'))

        else:
            # Failed login — per-user lockout
            if user:
                user.login_attempts += 1
                if user.login_attempts >= 5:
                    user.locked_until = datetime.utcnow() + timedelta(minutes=15)
                    flash('Too many failed attempts. Account locked for 15 minutes.', 'danger')
                else:
                    remaining = 5 - user.login_attempts
                    flash(f'Invalid credentials. {remaining} attempt(s) remaining.', 'danger')
                db.session.commit()
            else:
                # Constant-time: same message whether user exists or not (no user enumeration)
                flash('Invalid username or password.', 'danger')

    return render_template('auth/login.html', num1=num1, num2=num2, captcha_token=captcha_token)


@auth_bp.route('/logout')
@login_required
def logout():
    ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
    ActivityLog.log(current_user.id, 'logout', 'User logged out', ip_address=ip)
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """
    Registration page - only allows Agent or Client roles.
    Admin cannot be created through registration.
    """
    if not current_app.config.get('REGISTRATION_ENABLED', False):
        flash('Public registration is disabled. Contact an administrator.', 'warning')
        return redirect(url_for('auth.login'))

    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        username         = request.form.get('username', '').strip()
        email            = request.form.get('email', '').strip()
        password         = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')
        account_type     = request.form.get('account_type', 'client')  # 'agent' or 'client'

        errors = []

        if len(username) < 4:
            errors.append('Username must be at least 4 characters.')
        if len(username) > 80:
            errors.append('Username must be less than 80 characters.')
        if not re.match(r'^[A-Za-z0-9_]+$', username):
            errors.append('Username can only contain letters, numbers, and underscores.')

        if not re.match(r'^[\w\.\-]+@[\w\.\-]+\.\w+$', email):
            errors.append('Please enter a valid email address.')

        if len(password) < 6:
            errors.append('Password must be at least 6 characters.')

        if password != password_confirm:
            errors.append('Passwords do not match.')

        # Only allow agent or client roles
        if account_type not in ['agent', 'client']:
            errors.append('Invalid account type. Please select Agent or Client.')

        if User.query.filter_by(username=username).first():
            errors.append('Username already exists.')
        if User.query.filter_by(email=email).first():
            errors.append('Email already registered.')

        # Block test123 registration
        if username.lower() == 'test123':
            errors.append('This username is reserved.')

        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('auth/register.html')

        from app.models.user import Role
        role = Role.query.filter_by(name=account_type).first()
        if not role:
            role = Role(name=account_type, display_name=account_type.capitalize(), permissions='[]')
            db.session.add(role)
            db.session.commit()

        user = User(
            username=username,
            email=email,
            role=role,
            is_active=True
        )
        user.set_password(password)
        user.generate_api_token()

        db.session.add(user)
        db.session.commit()

        ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        ActivityLog.log(user.id, 'register', f'New {account_type} account registered', ip_address=ip)

        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html')


# ── Error handlers ────────────────────────────────────────────────────────────

@auth_bp.app_errorhandler(401)
def unauthorized(e):
    flash('Please log in to access this page.', 'warning')
    return redirect(url_for('auth.login', next=request.path))


@auth_bp.app_errorhandler(403)
def forbidden(e):
    flash('You do not have permission to access this page.', 'danger')
    return redirect(url_for('main.dashboard'))


@auth_bp.app_errorhandler(404)
def not_found(e):
    return render_template('errors/404.html'), 404


@auth_bp.app_errorhandler(500)
def server_error(e):
    db.session.rollback()
    return render_template('errors/500.html'), 500
