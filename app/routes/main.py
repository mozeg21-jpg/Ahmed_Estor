from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.user import User
from app.models.sms import SMSCDR, SMSNumber, SMDRange
from app.models.activity import ActivityLog, News
from datetime import datetime, timedelta
from sqlalchemy import func, or_

main_bp = Blueprint('main', __name__)


# ── Dashboard ──────────────────────────────────────────────────────────────────

@main_bp.route('/agent/')
@main_bp.route('/agent/dashboard')
@login_required
def dashboard():
    # Get SMS stats
    today = datetime.utcnow().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    # Today's SMS
    today_sms = SMSCDR.query.filter(
        SMSCDR.user_id == current_user.id,
        func.date(SMSCDR.created_at) == today
    ).count()

    # Last 7 days SMS
    week_sms = SMSCDR.query.filter(
        SMSCDR.user_id == current_user.id,
        SMSCDR.created_at >= week_ago
    ).count()

    # Last 30 days SMS
    month_sms = SMSCDR.query.filter(
        SMSCDR.user_id == current_user.id,
        SMSCDR.created_at >= month_ago
    ).count()

    # Total SMS this month
    first_of_month = today.replace(day=1)
    month_total = SMSCDR.query.filter(
        SMSCDR.user_id == current_user.id,
        SMSCDR.created_at >= first_of_month
    ).count()

    # Get ranges count
    ranges_count = SMDRange.query.filter_by(is_active=True).count()

    # Get numbers count
    numbers_count = SMSNumber.query.filter_by(agent_id=current_user.id).count()

    # Get clients count
    clients_count = User.query.filter_by(agent_id=current_user.id).count()

    # Get recent news
    news = News.query.filter_by(is_active=True).order_by(News.created_at.desc()).limit(5).all()

    # Get recent clients
    recent_clients = User.query.filter_by(agent_id=current_user.id).order_by(User.created_at.desc()).limit(5).all()

    # Chart data - Last 7 days
    chart_data = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        count = SMSCDR.query.filter(
            SMSCDR.user_id == current_user.id,
            func.date(SMSCDR.created_at) == day
        ).count()
        chart_data.append({
            'date': day.strftime('%Y-%m-%d'),
            'count': count
        })

    return render_template('main/dashboard.html',
        today_sms=today_sms,
        week_sms=week_sms,
        month_sms=month_sms,
        month_total=month_total,
        ranges_count=ranges_count,
        numbers_count=numbers_count,
        clients_count=clients_count,
        news=news,
        recent_clients=recent_clients,
        chart_data=chart_data
    )


# ── Profile (Hidden for test123) ─────────────────────────────────────────────

@main_bp.route('/agent/Profile', methods=['GET', 'POST'])
@login_required
def profile():
    # test123 account cannot modify its own profile
    if current_user.is_test_account():
        flash('Profile modification is disabled for this account.', 'warning')
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        current_user.name = request.form.get('name')
        current_user.company = request.form.get('company')
        current_user.email = request.form.get('email')
        current_user.skype = request.form.get('skype')
        current_user.contact = request.form.get('contact')
        current_user.country = request.form.get('country')
        current_user.address = request.form.get('address')

        new_password = request.form.get('new_password', '')
        if new_password and len(new_password) >= 6:
            current_user.set_password(new_password)
            flash('Password updated successfully.', 'success')

        db.session.commit()
        flash('Profile updated successfully.', 'success')
        return redirect(url_for('main.profile'))

    return render_template('main/profile.html')


# ── Inbox with masking ─────────────────────────────────────────────────────────

@main_bp.route('/agent/Inbox')
@login_required
def inbox():
    """User inbox - shows received SMS with masking for test123."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)

    # Get user's numbers
    user_numbers = SMSNumber.query.filter_by(agent_id=current_user.id).all()
    number_ids = [n.id for n in user_numbers]

    # Query CDR records for user's numbers (received SMS)
    cdr_query = SMSCDR.query.filter(
        SMSCDR.number_id.in_(number_ids),
        SMSCDR.sms_type == 'received'
    )

    # Date filter
    fdate1 = request.args.get('fdate1', '')
    fdate2 = request.args.get('fdate2', '')
    if fdate1 and fdate2:
        try:
            date1 = datetime.strptime(fdate1, '%Y-%m-%d')
            date2 = datetime.strptime(fdate2, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            cdr_query = cdr_query.filter(
                SMSCDR.created_at >= date1,
                SMSCDR.created_at <= date2
            )
        except ValueError:
            pass

    # Search by CLI (sender)
    fcli = request.args.get('fcli', '')
    if fcli:
        cdr_query = cdr_query.filter(SMSCDR.cli.ilike(f'%{fcli}%'))

    cdr_records = cdr_query.order_by(SMSCDR.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Apply masking for test123 account
    apply_masking = current_user.is_test_account()

    # Totals
    totals = db.session.query(
        func.sum(SMSCDR.agent_payout).label('total_payout'),
        func.count(SMSCDR.id).label('total_sms')
    ).filter(
        SMSCDR.number_id.in_(number_ids),
        SMSCDR.sms_type == 'received'
    ).first()

    return render_template('main/inbox.html',
        cdr_records=cdr_records,
        totals=totals,
        fdate1=fdate1,
        fdate2=fdate2,
        fcli=fcli,
        apply_masking=apply_masking
    )


# ── SMS Ranges ─────────────────────────────────────────────────────────────────

@main_bp.route('/agent/SMSRanges')
@login_required
def sms_ranges():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)

    ranges_query = SMDRange.query.filter_by(is_active=True)

    search = request.args.get('search', '')
    if search:
        ranges_query = ranges_query.filter(
            db.or_(
                SMDRange.country.like(f'%{search}%'),
                SMDRange.name.like(f'%{search}%')
            )
        )

    ranges = ranges_query.order_by(SMDRange.country).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template('main/sms_ranges.html', ranges=ranges)


# ── My Numbers ────────────────────────────────────────────────────────────────

@main_bp.route('/agent/MySMSNumbers')
@login_required
def my_sms_numbers():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)

    numbers_query = SMSNumber.query.filter_by(agent_id=current_user.id)

    range_filter = request.args.get('frange', '')
    if range_filter:
        numbers_query = numbers_query.filter_by(range_id=range_filter)

    client_filter = request.args.get('fclient', '')
    if client_filter:
        numbers_query = numbers_query.filter_by(client_id=client_filter)

    numbers = numbers_query.order_by(SMSNumber.number).paginate(
        page=page, per_page=per_page, error_out=False
    )

    ranges = SMDRange.query.filter_by(is_active=True).all()
    clients = User.query.filter_by(agent_id=current_user.id).all()

    return render_template('main/my_sms_numbers.html',
        numbers=numbers,
        ranges=ranges,
        clients=clients
    )


# ── SMS CDR Reports ────────────────────────────────────────────────────────────

@main_bp.route('/agent/SMSCDRReports')
@login_required
def sms_cdr_reports():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)

    fdate1 = request.args.get('fdate1', datetime.utcnow().strftime('%Y-%m-%d'))
    fdate2 = request.args.get('fdate2', datetime.utcnow().strftime('%Y-%m-%d'))

    def parse_date(date_str):
        try:
            return datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            try:
                return datetime.strptime(date_str, '%Y-%m-%d')
            except (ValueError, TypeError):
                return datetime.utcnow()

    date1 = parse_date(fdate1)
    date2 = parse_date(fdate2)
    date2 = date2.replace(hour=23, minute=59, second=59)

    cdr_query = SMSCDR.query.filter(
        SMSCDR.user_id == current_user.id,
        SMSCDR.created_at >= date1,
        SMSCDR.created_at <= date2
    )

    frange = request.args.get('frange', '')
    if frange:
        cdr_query = cdr_query.filter_by(range_id=frange)

    fclient = request.args.get('fclient', '')
    if fclient:
        cdr_query = cdr_query.filter_by(client_id=fclient)

    fnum = request.args.get('fnum', '')
    if fnum:
        cdr_query = cdr_query.join(SMSNumber).filter(SMSNumber.number.like(f'%{fnum}%'))

    fcli = request.args.get('fcli', '')
    if fcli:
        cdr_query = cdr_query.filter(SMSCDR.cli.like(f'%{fcli}%'))

    cdr_records = cdr_query.order_by(SMSCDR.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    totals = db.session.query(
        func.sum(SMSCDR.agent_payout).label('total_payout'),
        func.sum(SMSCDR.client_payout).label('total_client'),
        func.sum(SMSCDR.profit).label('total_profit'),
        func.count(SMSCDR.id).label('total_sms')
    ).filter(
        SMSCDR.user_id == current_user.id,
        SMSCDR.created_at >= date1,
        SMSCDR.created_at <= date2
    ).first()

    ranges = SMDRange.query.filter_by(is_active=True).all()
    clients = User.query.filter_by(agent_id=current_user.id).all()

    return render_template('main/sms_cdr_reports.html',
        cdr_records=cdr_records,
        totals=totals,
        ranges=ranges,
        clients=clients,
        fdate1=fdate1,
        fdate2=fdate2
    )


# ── Clients Management ─────────────────────────────────────────────────────────

@main_bp.route('/agent/Clients')
@login_required
def clients():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)

    search = request.args.get('search', '')
    clients_query = User.query.filter_by(agent_id=current_user.id)

    if search:
        clients_query = clients_query.filter(
            db.or_(
                User.username.like(f'%{search}%'),
                User.email.like(f'%{search}%')
            )
        )

    clients_list = clients_query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template('main/clients.html', clients=clients_list, search=search)


@main_bp.route('/agent/ClientSettings/<int:client_id>', methods=['GET', 'POST'])
@login_required
def client_settings(client_id):
    client = User.query.filter_by(id=client_id, agent_id=current_user.id).first()
    if not client:
        flash('Client not found or access denied.', 'danger')
        return redirect(url_for('main.clients'))

    if request.method == 'POST':
        client.name = request.form.get('name')
        client.company = request.form.get('company')
        client.country = request.form.get('country')
        client.sms_limit = request.form.get('sms_limit', 0, type=int)

        delete_mode = request.form.get('delete_mode', 'never')
        delete_value = request.form.get('delete_value', 0, type=int)
        if delete_mode == 'never':
            client.delete_messages_after = 0
        elif delete_mode == 'minutes':
            client.delete_messages_after = delete_value
        elif delete_mode == 'hours':
            client.delete_messages_after = delete_value * 60

        db.session.commit()
        flash(f'Settings updated for client {client.username}.', 'success')
        return redirect(url_for('main.client_settings', client_id=client_id))

    client_numbers = SMSNumber.query.filter_by(client_id=client_id).all()
    available_numbers = SMSNumber.query.filter_by(
        agent_id=current_user.id,
        client_id=None,
        is_active=True
    ).count()

    return render_template('main/client_settings.html',
        client=client,
        client_numbers=client_numbers,
        available_numbers=available_numbers
    )


@main_bp.route('/agent/AddNumbersToClient/<int:client_id>', methods=['POST'])
@login_required
def add_numbers_to_client(client_id):
    client = User.query.filter_by(id=client_id, agent_id=current_user.id).first()
    if not client:
        flash('Client not found or access denied.', 'danger')
        return redirect(url_for('main.clients'))

    numbers_count = request.form.get('numbers_count', 0, type=int)
    if numbers_count <= 0:
        flash('Please enter a valid number.', 'danger')
        return redirect(url_for('main.client_settings', client_id=client_id))

    available_numbers = SMSNumber.query.filter_by(
        agent_id=current_user.id,
        client_id=None,
        is_active=True
    ).limit(numbers_count).all()

    if not available_numbers:
        flash('No available numbers to assign.', 'warning')
        return redirect(url_for('main.client_settings', client_id=client_id))

    added_count = 0
    for num in available_numbers:
        num.client_id = client_id
        num.status = 'activated'
        num.assigned_at = datetime.utcnow()
        added_count += 1

    db.session.commit()
    flash(f'{added_count} numbers assigned to client {client.username}.', 'success')
    return redirect(url_for('main.client_settings', client_id=client_id))


@main_bp.route('/agent/RemoveNumbersFromClient/<int:client_id>', methods=['POST'])
@login_required
def remove_numbers_from_client(client_id):
    client = User.query.filter_by(id=client_id, agent_id=current_user.id).first()
    if not client:
        flash('Client not found or access denied.', 'danger')
        return redirect(url_for('main.clients'))

    numbers_count = request.form.get('numbers_count', 0, type=int)
    if numbers_count <= 0:
        flash('Please enter a valid number.', 'danger')
        return redirect(url_for('main.client_settings', client_id=client_id))

    client_numbers = SMSNumber.query.filter_by(client_id=client_id).limit(numbers_count).all()

    if not client_numbers:
        flash('No numbers to remove from this client.', 'warning')
        return redirect(url_for('main.client_settings', client_id=client_id))

    removed_count = 0
    for num in client_numbers:
        num.client_id = None
        num.status = 'reserved'
        num.assigned_at = None
        removed_count += 1

    db.session.commit()
    flash(f'{removed_count} numbers removed from client {client.username}.', 'success')
    return redirect(url_for('main.client_settings', client_id=client_id))


# ── My Activity ────────────────────────────────────────────────────────────────

@main_bp.route('/agent/MyActivity')
@login_required
def my_activity():
    from app.models.activity import ActivityLog

    page = request.args.get('page', 1, type=int)
    per_page = 50

    activities = ActivityLog.query.filter_by(user_id=current_user.id).order_by(
        ActivityLog.created_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    return render_template('main/my_activity.html', activities=activities)


# ── Notifications ─────────────────────────────────────────────────────────────

@main_bp.route('/agent/Notifications')
@login_required
def notifications():
    return render_template('main/notifications.html')


# ── API Settings (Blocked for test123) ───────────────────────────────────────

@main_bp.route('/agent/api-settings')
@login_required
def agent_api_settings():
    """Agent API settings page"""
    if current_user.is_test_account():
        flash('API settings are disabled for this account.', 'warning')
        return redirect(url_for('main.dashboard'))

    from app.models.activity import News

    bot_token = News.query.filter_by(title=f'agent_bot_token_{current_user.id}').first()
    admin_chat_id = News.query.filter_by(title=f'agent_admin_chat_id_{current_user.id}').first()
    bot_enabled = bot_token.is_active if bot_token and bot_token.is_active is not None else False

    return render_template('main/agent_api_settings.html',
        agent_bot_token=bot_token.content if bot_token else '',
        agent_admin_chat_id=admin_chat_id.content if admin_chat_id else '',
        agent_bot_enabled=bot_enabled
    )


@main_bp.route('/agent/bot-settings', methods=['POST'])
@login_required
def agent_bot_settings():
    """Save agent's Telegram bot settings"""
    if current_user.is_test_account():
        flash('Bot settings are disabled for this account.', 'warning')
        return redirect(url_for('main.dashboard'))

    from app.models.activity import News

    bot_token = request.form.get('bot_token', '').strip()
    admin_chat_id = request.form.get('admin_chat_id', '').strip()
    bot_enabled = request.form.get('bot_enabled') == 'on'

    setting_token = News.query.filter_by(title=f'agent_bot_token_{current_user.id}').first()
    if setting_token:
        setting_token.headline = f'Bot Token for {current_user.username}'
        setting_token.content = bot_token
        setting_token.is_active = bot_enabled
    else:
        setting_token = News(
            title=f'agent_bot_token_{current_user.id}',
            headline=f'Bot Token for {current_user.username}',
            content=bot_token,
            is_active=bot_enabled
        )
        db.session.add(setting_token)

    setting_chat = News.query.filter_by(title=f'agent_admin_chat_id_{current_user.id}').first()
    if setting_chat:
        setting_chat.headline = f'Admin Chat ID for {current_user.username}'
        setting_chat.content = admin_chat_id
    else:
        setting_chat = News(
            title=f'agent_admin_chat_id_{current_user.id}',
            headline=f'Admin Chat ID for {current_user.username}',
            content=admin_chat_id,
            is_active=True
        )
        db.session.add(setting_chat)

    db.session.commit()
    flash('Bot settings saved successfully.', 'success')
    return redirect(url_for('main.agent_api_settings'))


@main_bp.route('/agent/regenerate-token', methods=['POST'])
@login_required
def agent_regenerate_token():
    """Regenerate agent's API token"""
    if current_user.is_test_account():
        return jsonify({'error': 'Cannot regenerate token for this account'}), 403

    current_user.generate_api_token()
    db.session.commit()

    return jsonify({
        'success': True,
        'token': current_user.api_token
    })


@main_bp.route('/agent/test-bot', methods=['POST'])
@login_required
def agent_test_bot():
    """Test agent's Telegram bot connection"""
    import requests

    bot_token = request.form.get('bot_token', '').strip()
    chat_id = request.form.get('chat_id', '').strip()

    if not bot_token or not chat_id:
        return jsonify({'success': False, 'error': 'Bot token and chat ID are required'})

    try:
        url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
        response = requests.post(url, json={
            'chat_id': chat_id,
            'text': 'Test message from SMS Platform - Bot connection successful!'
        }, timeout=10)

        if response.status_code == 200:
            return jsonify({'success': True, 'message': 'Test message sent'})
        else:
            return jsonify({'success': False, 'error': 'Failed to send message'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
