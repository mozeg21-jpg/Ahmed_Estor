from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.user import User
from app.models.sms import SMSCDR, SMSNumber, SMDRange
from app.models.activity import ActivityLog, News
from app.models.finance import BankAccount, PaymentRequest
from datetime import datetime, timedelta
from sqlalchemy import func, or_
from app.smpp_methods.deliver_sm import DeliverSMHandler

main_bp = Blueprint('main', __name__)

@main_bp.before_request
def restrict_admin_from_agent_routes():
    # If the user is an admin, prevent them from accessing any client/agent panel routes under /agent/
    if current_user.is_authenticated and current_user.is_admin():
        if request.path.startswith('/agent'):
            return redirect(url_for('admin.index'))

@main_bp.route('/webhook/receive_sms', methods=['POST', 'GET'])
def webhook_receive_sms():
    """
    Webhook endpoint to receive messages and route them to the appropriate account.
    """
    if request.method == 'POST':
        data = request.json or request.form
        source = data.get('source_address', 'Unknown')
        destination = data.get('destination_address')
        text = data.get('text', '')
        
        if not destination:
            return jsonify({"status": "error", "message": "destination_address is required"}), 400
            
        handler = DeliverSMHandler(supplier_id=1)
        success, message = handler.handle_incoming_message(source, destination, text)
        
        if success:
            return jsonify({"status": "success", "message": message}), 200
        else:
            return jsonify({"status": "failed", "message": message}), 404
            
    # For GET testing purposes
    destination = request.args.get('destination_address')
    if destination:
        source = request.args.get('source_address', 'Testing')
        text = request.args.get('text', 'Test Message')
        handler = DeliverSMHandler(supplier_id=1)
        success, message = handler.handle_incoming_message(source, destination, text)
        return jsonify({"status": "success" if success else "failed", "message": message})
        
    return jsonify({"status": "info", "message": "Use POST method or pass parameters in GET"}), 200


# ── Dashboard ──────────────────────────────────────────────────────────────────

@main_bp.route('/agent/')
@main_bp.route('/agent/dashboard')
@login_required
def dashboard():
    # If the logged in user is an Administrator, redirect them to the Admin dashboard
    if current_user.is_admin():
        return redirect(url_for('admin.index'))

    # ── Auto-Payout Logic ───────────────────────────────────────────────────
    # If balance reaches $50 after 45 days, auto-reset and create withdrawal request
    threshold = getattr(current_user, 'monthly_limit', 50.0) or 50.0
    age_limit_days = 45
    
    # Calculate account age
    account_age = datetime.utcnow() - current_user.created_at
    
    if current_user.balance >= threshold and account_age.days >= age_limit_days:
        # Zero out balance
        payout_amount = current_user.balance
        current_user.balance = 0.0
        
        # Find or create a default bank account for the payout
        bank = BankAccount.query.filter_by(user_id=current_user.id, status='active').first()
        if not bank:
            bank = BankAccount(
                user_id=current_user.id,
                bank_name="System Auto-Payout",
                account_name=current_user.name or current_user.username,
                iban=f"AUTO-IBAN-{current_user.id}-{datetime.utcnow().strftime('%Y%m%d')}",
                bic_swift="SYSTEM",
                currency="USD",
                status="active"
            )
            db.session.add(bank)
            db.session.flush() # Get bank.id
            
        # Create payment request
        pr = PaymentRequest(
            user_id=current_user.id,
            amount=payout_amount,
            currency="USD",
            bank_account_id=bank.id,
            status='pending',
            requested_at=datetime.utcnow()
        )
        db.session.add(pr)
        db.session.commit()
        flash(f'تم تصفير الحساب وتوليد طلب سحب تلقائي بقيمة ${payout_amount:.2f} لتجاوزك الحد المسموح بعد {age_limit_days} يوماً.', 'success')
    # ────────────────────────────────────────────────────────────────────────

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

    # Get recent news (only public announcements, excluding admin settings)
    news = News.query.filter(News.is_active == True).filter((News.title == None) | (News.title == '')).order_by(News.created_at.desc()).limit(5).all()

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

@main_bp.route('/agent/user-api')
@login_required
def user_api_settings():
    """User Independent API Settings page"""
    if current_user.is_test_account():
        flash('API settings are disabled for this account.', 'warning')
        return redirect(url_for('main.dashboard'))
    return render_template('main/user_api_settings.html')

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


# ── Finance Module ──

@main_bp.route('/agent/SMSRatecard')
@login_required
def sms_ratecard():
    ranges = SMDRange.query.filter_by(is_active=True).all()
    return render_template('main/sms_ratecard.html', ranges=ranges)

@main_bp.route('/agent/SMSTestPanel', methods=['GET', 'POST'])
@login_required
def sms_test_panel():
    # Postponed trial/simulated operations as requested by user
    flash('تم تأجيل وتعطيل العمليات التجريبية والوهمية بناء على طلب الإدارة للحفاظ على دقة وحقيقة الحساب.', 'warning')
    return redirect(url_for('main.dashboard'))

@main_bp.route('/agent/CreditNotes')
@login_required
def credit_notes():
    if current_user.is_admin() or current_user.is_test_account():
        flash('Access denied. Financial modules are disabled for Administrator and Test accounts.', 'danger')
        return redirect(url_for('main.dashboard'))
    from app.models.finance import CreditNote
    user_notes = CreditNote.query.filter_by(user_id=current_user.id).all()
    if not user_notes:
        note1 = CreditNote(
            user_id=current_user.id,
            note_number='CN-2026-001',
            amount=250.0,
            currency='USD',
            description='Aggregated payout credit for May 2026',
            status='open'
        )
        note2 = CreditNote(
            user_id=current_user.id,
            note_number='CN-2026-002',
            amount=180.0,
            currency='EUR',
            description='Premium range traffic earnings',
            status='closed'
        )
        db.session.add(note1)
        db.session.add(note2)
        db.session.commit()
        user_notes = [note1, note2]
        
    return render_template('main/credit_notes.html', credit_notes=user_notes)

@main_bp.route('/agent/PaymentRequests', methods=['GET', 'POST'])
@login_required
def payment_requests():
    if current_user.is_admin() or current_user.is_test_account():
        flash('Access denied. Financial modules are disabled for Administrator and Test accounts.', 'danger')
        return redirect(url_for('main.dashboard'))
    from app.models.finance import PaymentRequest, BankAccount, CreditNote
    
    if request.method == 'POST':
        amount = request.form.get('amount', type=float)
        currency = request.form.get('currency', 'USD')
        bank_id = request.form.get('bank_account_id', type=int)
        
        selected_bank = BankAccount.query.get(bank_id)
        if not selected_bank or selected_bank.user_id != current_user.id:
            flash('Invalid bank account selected.', 'danger')
            return redirect(url_for('main.payment_requests'))
            
        if not amount or amount <= 0:
            flash('Please enter a valid payout amount.', 'danger')
            return redirect(url_for('main.payment_requests'))
            
        new_req = PaymentRequest(
            user_id=current_user.id,
            amount=amount,
            currency=currency,
            bank_account_id=selected_bank.id,
            status='pending'
        )
        db.session.add(new_req)
        db.session.commit()
        
        flash('Payout request successfully submitted!', 'success')
        return redirect(url_for('main.payment_requests'))
        
    requests_list = PaymentRequest.query.filter_by(user_id=current_user.id).order_by(PaymentRequest.requested_at.desc()).all()
    bank_accounts = BankAccount.query.filter_by(user_id=current_user.id, status='active').all()
    
    usd_balance = db.session.query(func.sum(CreditNote.amount)).filter_by(user_id=current_user.id, currency='USD').scalar() or 0.0
    eur_balance = db.session.query(func.sum(CreditNote.amount)).filter_by(user_id=current_user.id, currency='EUR').scalar() or 0.0
    gbp_balance = db.session.query(func.sum(CreditNote.amount)).filter_by(user_id=current_user.id, currency='GBP').scalar() or 0.0
    
    usd_payouts = db.session.query(func.sum(PaymentRequest.amount)).filter_by(user_id=current_user.id, currency='USD').filter(PaymentRequest.status != 'rejected').scalar() or 0.0
    eur_payouts = db.session.query(func.sum(PaymentRequest.amount)).filter_by(user_id=current_user.id, currency='EUR').filter(PaymentRequest.status != 'rejected').scalar() or 0.0
    gbp_payouts = db.session.query(func.sum(PaymentRequest.amount)).filter_by(user_id=current_user.id, currency='GBP').filter(PaymentRequest.status != 'rejected').scalar() or 0.0
    
    usd_bal = max(0.0, usd_balance - usd_payouts)
    eur_bal = max(0.0, eur_balance - eur_payouts)
    gbp_bal = max(0.0, gbp_balance - gbp_payouts)
    
    return render_template('main/payment_requests.html', 
                           requests=requests_list, 
                           bank_accounts=bank_accounts,
                           usd_balance=usd_bal,
                           eur_balance=eur_bal,
                           gbp_balance=gbp_bal)

@main_bp.route('/agent/BankAccounts', methods=['GET', 'POST'])
@login_required
def bank_accounts():
    if current_user.is_admin() or current_user.is_test_account():
        flash('Access denied. Financial modules are disabled for Administrator and Test accounts.', 'danger')
        return redirect(url_for('main.dashboard'))
    from app.models.finance import BankAccount
    
    if request.method == 'POST':
        bank_name = request.form.get('bank_name', '').strip()
        account_name = request.form.get('account_name', '').strip()
        iban = request.form.get('iban', '').strip()
        swift = request.form.get('bic_swift', '').strip()
        currency = request.form.get('currency', 'USD')
        
        if not bank_name or not account_name or not iban or not swift:
            flash('All bank fields are required.', 'danger')
            return redirect(url_for('main.bank_accounts'))
            
        new_account = BankAccount(
            user_id=current_user.id,
            bank_name=bank_name,
            account_name=account_name,
            iban=iban,
            bic_swift=swift,
            currency=currency,
            status='active'
        )
        db.session.add(new_account)
        db.session.commit()
        
        flash('Bank account successfully added!', 'success')
        return redirect(url_for('main.bank_accounts'))
        
    accounts = BankAccount.query.filter_by(user_id=current_user.id).all()
    if not accounts:
        accounts = [
            BankAccount(
                user_id=current_user.id,
                bank_name='HSBC UK',
                account_name=current_user.username.upper() + ' LTD',
                iban='GB29HSBC60011112345678',
                bic_swift='MIDLGB21',
                currency='GBP',
                status='active'
            )
        ]
        db.session.add(accounts[0])
        db.session.commit()
        
    return render_template('main/bank_accounts.html', bank_accounts=accounts)

@main_bp.route('/agent/BankAccounts/<int:account_id>/toggle', methods=['POST'])
@login_required
def toggle_bank_account(account_id):
    from app.models.finance import BankAccount
    account = BankAccount.query.get_or_404(account_id)
    if account.user_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('main.bank_accounts'))
        
    account.status = 'inactive' if account.status == 'active' else 'active'
    db.session.commit()
    flash('Bank account status updated successfully.', 'success')
    return redirect(url_for('main.bank_accounts'))

@main_bp.route('/agent/BankAccounts/<int:account_id>/delete', methods=['POST'])
@login_required
def delete_bank_account(account_id):
    from app.models.finance import BankAccount
    account = BankAccount.query.get_or_404(account_id)
    if account.user_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('main.bank_accounts'))
        
    db.session.delete(account)
    db.session.commit()
    flash('Bank account deleted successfully.', 'success')
    return redirect(url_for('main.bank_accounts'))

@main_bp.route('/agent/Statements/<currency>')
@login_required
def statements(currency):
    if current_user.is_admin() or current_user.is_test_account():
        flash('Access denied. Financial modules are disabled for Administrator and Test accounts.', 'danger')
        return redirect(url_for('main.dashboard'))
    from app.models.finance import CreditNote, PaymentRequest
    
    currency = currency.upper()
    if currency not in ('USD', 'EUR', 'GBP'):
        currency = 'USD'
        
    credits = CreditNote.query.filter_by(user_id=current_user.id, currency=currency).all()
    payouts = PaymentRequest.query.filter_by(user_id=current_user.id, currency=currency).all()
    
    transactions = []
    
    for c in credits:
        transactions.append({
            'date': c.issue_date,
            'type': 'Credit Note',
            'reference': c.note_number,
            'description': c.description or 'Account credit note',
            'amount': c.amount,
            'is_credit': True
        })
        
    for p in payouts:
        transactions.append({
            'date': p.requested_at,
            'type': 'Payout Request',
            'reference': f'PAY-{p.id}',
            'description': f'Payout to {p.bank_account.bank_name if p.bank_account else "bank"}',
            'amount': -p.amount,
            'is_credit': False,
            'status': p.status
        })
        
    transactions.sort(key=lambda x: x['date'], reverse=True)
    
    balance = 0.0
    for t in reversed(transactions):
        balance += t['amount']
        t['running_balance'] = balance
        
    transactions.reverse()
    
    return render_template('main/statements.html', currency=currency, transactions=transactions)

@main_bp.route('/set_language/<lang>')
def set_language(lang):
    from flask import session, request, redirect, url_for
    if lang in ['ar', 'en']:
        session['lang'] = lang
    return redirect(request.referrer or url_for('main.dashboard'))

@main_bp.route('/agent/Stats/<stat_type>')
@login_required
def stats(stat_type):
    if stat_type not in ('sms', 'clients', 'ranges', 'numbers'):
        stat_type = 'sms'
        
    records = []
    if stat_type == 'sms':
        sms_by_day = db.session.query(
            func.date(SMSCDR.created_at).label('day'),
            func.count(SMSCDR.id).label('count'),
            func.sum(SMSCDR.agent_payout).label('payout')
        ).filter(SMSCDR.user_id == current_user.id).group_by(func.date(SMSCDR.created_at)).all()
        for row in sms_by_day:
            records.append({
                'label': row.day,
                'count': row.count,
                'payout': row.payout or 0.0
            })
    elif stat_type == 'clients':
        client_stats = db.session.query(
            User.username.label('name'),
            func.count(SMSCDR.id).label('count'),
            func.sum(SMSCDR.agent_payout).label('payout')
        ).join(SMSCDR, SMSCDR.client_id == User.id).filter(SMSCDR.user_id == current_user.id).group_by(User.username).all()
        for row in client_stats:
            records.append({
                'label': row.name,
                'count': row.count,
                'payout': row.payout or 0.0
            })
    elif stat_type == 'ranges':
        range_stats = db.session.query(
            SMDRange.country.label('name'),
            func.count(SMSCDR.id).label('count'),
            func.sum(SMSCDR.agent_payout).label('payout')
        ).join(SMSCDR, SMSCDR.range_id == SMDRange.id).filter(SMSCDR.user_id == current_user.id).group_by(SMDRange.country).all()
        for row in range_stats:
            records.append({
                'label': row.name,
                'count': row.count,
                'payout': row.payout or 0.0
            })
    elif stat_type == 'numbers':
        number_stats = db.session.query(
            SMSNumber.number.label('name'),
            func.count(SMSCDR.id).label('count'),
            func.sum(SMSCDR.agent_payout).label('payout')
        ).join(SMSCDR, SMSCDR.number_id == SMSNumber.id).filter(SMSCDR.user_id == current_user.id).group_by(SMSNumber.number).limit(100).all()
        for row in number_stats:
            records.append({
                'label': row.name,
                'count': row.count,
                'payout': row.payout or 0.0
            })
            
    return render_template('main/stats.html', stat_type=stat_type, records=records)

