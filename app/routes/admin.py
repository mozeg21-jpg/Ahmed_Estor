from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, make_response
from flask_login import login_required, current_user
from app import db
from app.models.sms import SMDRange, SMSNumber, SMSCDR
from app.models.user import User, Role
from app.models.activity import ActivityLog, News
from datetime import datetime, timedelta
from functools import wraps

admin_bp = Blueprint('admin', __name__)

# Admin required decorator
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login'))
        # Check both is_admin column and is_admin() method
        is_admin = current_user.is_admin()
        if not is_admin:
            flash('Admin access required.', 'danger')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated

# Primary admin required decorator
def primary_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login'))
        if not current_user.is_admin() or current_user.username != 'admin':
            flash('عذراً، هذه الصفحة مخصصة فقط للمدير الأساسي للنظام (admin).', 'danger')
            return redirect(url_for('admin.index'))
        return f(*args, **kwargs)
    return decorated

# ============ ADMIN DASHBOARD ============

@admin_bp.route('/')
@admin_required
def index():
    total_users = User.query.count()
    active_users = User.query.filter_by(is_active=True).count()
    total_numbers = SMSNumber.query.count()
    total_ranges = SMDRange.query.count()
    total_cdr = SMSCDR.query.count()

    # Recent activity
    recent_activity = ActivityLog.query.order_by(
        ActivityLog.created_at.desc()
    ).limit(10).all()

    # Stats
    today = datetime.utcnow().date()
    today_sms = SMSCDR.query.filter(
        db.func.date(SMSCDR.created_at) == today
    ).count()

    # Recent news
    recent_news = News.query.filter_by(is_active=True).order_by(
        News.created_at.desc()
    ).limit(5).all()

    return render_template('admin/index.html',
        stats={
            'total_users': total_users,
            'active_users': active_users,
            'total_numbers': total_numbers,
            'total_ranges': total_ranges,
            'total_cdr': total_cdr,
            'today_sms': today_sms
        },
        recent_news=recent_news
    )

# ============ USER MANAGEMENT ============

@admin_bp.route('/users/view/<int:user_id>')
@admin_required
def view_user(user_id):
    user = User.query.get_or_404(user_id)
    return render_template('admin/user_view.html', user=user)

@admin_bp.route('/users/toggle_api/<int:user_id>', methods=['POST'])
@admin_required
def toggle_user_api(user_id):
    from datetime import datetime
    user = User.query.get_or_404(user_id)
    user.api_enabled = not user.api_enabled
    user.api_updated_at = datetime.utcnow()
    db.session.commit()
    status_str = "Enabled" if user.api_enabled else "Disabled"
    flash(f"User API status has been updated to {status_str} for {user.username}.", "success")
    return redirect(url_for('admin.view_user', user_id=user.id))

@admin_bp.route('/users/regenerate_api/<int:user_id>', methods=['POST'])
@admin_required
def regenerate_user_api(user_id):
    from datetime import datetime
    import secrets
    user = User.query.get_or_404(user_id)
    new_key = "vlt_" + secrets.token_hex(24)
    user.api_key = new_key
    user.api_created_at = datetime.utcnow()
    user.api_updated_at = datetime.utcnow()
    db.session.commit()
    flash(f"A new API key has been generated for {user.username}.", "success")
    return redirect(url_for('admin.view_user', user_id=user.id))

@admin_bp.route('/users/delete_api/<int:user_id>', methods=['POST'])
@admin_required
def delete_user_api(user_id):
    from datetime import datetime
    user = User.query.get_or_404(user_id)
    user.api_key = None
    user.api_enabled = False
    user.api_updated_at = datetime.utcnow()
    db.session.commit()
    flash(f"API key for {user.username} has been deleted and API was disabled.", "success")
    return redirect(url_for('admin.view_user', user_id=user.id))

@admin_bp.route('/users')
@admin_required
def users():
    page = request.args.get('page', 1, type=int)
    per_page = 25
    search = request.args.get('search', '')
    role_filter = request.args.get('role', '')

    query = User.query

    if search:
        query = query.filter(
            db.or_(
                User.username.like(f'%{search}%'),
                User.email.like(f'%{search}%'),
                User.name.like(f'%{search}%')
            )
        )

    if role_filter:
        query = query.filter_by(role_id=Role.query.filter_by(name=role_filter).first().id if Role.query.filter_by(name=role_filter).first() else None)

    users_list = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    roles = Role.query.all()
    agents = User.query.filter(User.role.has(name='agent')).all()

    return render_template('admin/users.html',
        users=users_list,
        roles=roles,
        agents=agents
    )

@admin_bp.route('/users/create', methods=['GET', 'POST'])
@admin_required
def create_user():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role_id = request.form.get('role_id', type=int)
        agent_id = request.form.get('agent_id', type=int)
        name = request.form.get('name')
        company = request.form.get('company')
        country = request.form.get('country')
        sms_limit = request.form.get('sms_limit', 0, type=int)
        monthly_limit = request.form.get('monthly_limit', 50.0, type=float)
        reset_day = request.form.get('reset_day', 1, type=int)

        if not username or not email or not password:
            flash('Username, email, and password are required.', 'danger')
            return redirect(url_for('admin.create_user'))

        from sqlalchemy import func
        existing_user = User.query.filter(func.lower(User.username) == func.lower(username)).first()
        if existing_user:
            flash('Username already exists.', 'danger')
            return redirect(url_for('admin.create_user'))

        role = Role.query.get(role_id)
        if not role:
            flash('Invalid role selected.', 'danger')
            return redirect(url_for('admin.create_user'))

        api_enabled = request.form.get('api_enabled') == '1'
        user = User(
            username=username,
            email=email,
            role=role,
            name=name,
            company=company,
            country=country,
            agent_id=agent_id if agent_id else None,
            sms_limit=sms_limit,
            monthly_limit=monthly_limit,
            reset_day=reset_day,
            is_active=True,
            api_enabled=api_enabled
        )
        if api_enabled:
            import secrets
            user.api_key = "vlt_" + secrets.token_hex(24)
            user.api_created_at = datetime.utcnow()
            user.api_updated_at = datetime.utcnow()
        user.set_password(password)
        user.generate_api_token()

        db.session.add(user)
        db.session.commit()

        ActivityLog.log(
            current_user.id,
            'admin_create_user',
            f'Created user {username} with role {role.display_name}',
            ip_address=request.remote_addr
        )

        flash(f'User {username} created successfully.', 'success')
        return redirect(url_for('admin.users'))

    roles = Role.query.all()
    agents = User.query.filter(User.role.has(name='agent')).all()
    return render_template('admin/user_form.html', roles=roles, agents=agents, user=None)

@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)

    if request.method == 'POST':
        user.email = request.form.get('email')
        user.name = request.form.get('name')
        user.company = request.form.get('company')
        user.country = request.form.get('country')
        user.skype = request.form.get('skype')
        user.contact = request.form.get('contact')
        user.sms_limit = request.form.get('sms_limit', 0, type=int)
        user.monthly_limit = request.form.get('monthly_limit', 50.0, type=float)
        user.reset_day = request.form.get('reset_day', 1, type=int)
        user.agent_id = request.form.get('agent_id', type=int)
        if not user.agent_id:
            user.agent_id = None

        role_id = request.form.get('role_id', type=int)
        if role_id:
            role = Role.query.get(role_id)
            if role:
                user.role_id = role.id

        # Update API key preferences
        api_enabled = request.form.get('api_enabled') == '1'
        if api_enabled:
            user.api_enabled = True
            if not user.api_key:
                import secrets
                user.api_key = "vlt_" + secrets.token_hex(24)
                user.api_created_at = datetime.utcnow()
                user.api_updated_at = datetime.utcnow()
        else:
            user.api_enabled = False

        is_active = request.form.get('is_active') == '1'
        user.is_active = is_active

        new_password = request.form.get('password')
        if new_password and len(new_password) >= 6:
            user.set_password(new_password)

        db.session.commit()

        ActivityLog.log(
            current_user.id,
            'admin_edit_user',
            f'Edited user {user.username}',
            ip_address=request.remote_addr
        )

        flash(f'User {user.username} updated successfully.', 'success')
        return redirect(url_for('admin.users'))

    roles = Role.query.all()
    agents = User.query.filter(User.role.has(name='agent')).all()
    return render_template('admin/user_form.html', roles=roles, agents=agents, user=user)

@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash('Cannot delete your own account.', 'danger')
        return redirect(url_for('admin.users'))

    username = user.username
    user_id_val = user.id

    # Perform thorough cleanup of all related entities to prevent foreign key constraint violations
    try:
        # Nullify sub-users' agent references
        User.query.filter_by(agent_id=user_id_val).update({'agent_id': None})

        # Nullify creator references in News and Ranges
        from app.models.activity import News
        from app.models.sms import SMDRange
        News.query.filter_by(created_by=user_id_val).update({'created_by': None})
        SMDRange.query.filter_by(created_by=user_id_val).update({'created_by': None})

        # Delete ActivityLogs
        from app.models.activity import ActivityLog
        ActivityLog.query.filter_by(user_id=user_id_val).delete()

        # Delete BankAccounts, CreditNotes, and PaymentRequests
        from app.models.finance import BankAccount, CreditNote, PaymentRequest
        BankAccount.query.filter_by(user_id=user_id_val).delete()
        CreditNote.query.filter_by(user_id=user_id_val).delete()
        PaymentRequest.query.filter_by(user_id=user_id_val).delete()

        # Delete Developer static assets
        from app.models.developer import StaticAsset
        StaticAsset.query.filter_by(uploader_id=user_id_val).delete()

        # Delete SMSNumbers and SMSCDRs linked to user to prevent FK violations
        from app.models.sms import SMSNumber, SMSCDR
        SMSCDR.query.filter_by(user_id=user_id_val).delete()
        SMSCDR.query.filter_by(client_id=user_id_val).delete()
        
        # Unassign numbers instead of deleting them if they are still in the system
        SMSNumber.query.filter_by(agent_id=user_id_val).update({'agent_id': None})
        SMSNumber.query.filter_by(client_id=user_id_val).update({'client_id': None})

        db.session.delete(user)
        db.session.commit()
        print(f"[ADMIN] User {username} (ID: {user_id_val}) deleted successfully.")
    except Exception as e:
        db.session.rollback()
        print(f"[ADMIN ERROR] Failed to delete user {username}: {str(e)}")
        flash(f'Failed to delete user: {str(e)}', 'danger')
        return redirect(url_for('admin.users'))

    ActivityLog.log(
        current_user.id,
        'admin_delete_user',
        f'Deleted user {username}',
        ip_address=request.remote_addr
    )

    flash(f'User {username} deleted.', 'success')
    return redirect(url_for('admin.users'))

@admin_bp.route('/users/<int:user_id>/toggle-status', methods=['POST'])
@admin_required
def toggle_user_status(user_id):
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({'error': 'Cannot toggle own status'}), 400
        flash('Cannot toggle your own status.', 'danger')
        return redirect(url_for('admin.users'))

    user.is_active = not user.is_active
    db.session.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        return jsonify({
            'success': True,
            'is_active': user.is_active
        })
    
    flash(f"تم تحديث حالة المستخدم {user.username} بنجاح.", 'success')
    return redirect(url_for('admin.users'))

@admin_bp.route('/users/<int:user_id>/reset-payout', methods=['POST'])
@admin_required
def reset_user_payout(user_id):
    """Reset user's sms_count to 0"""
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash('Cannot reset your own payout.', 'danger')
        return redirect(url_for('admin.users'))

    old_count = user.sms_count
    user.sms_count = 0
    db.session.commit()

    ActivityLog.log(
        current_user.id,
        'admin_reset_payout',
        f'Reset payout for user {user.username} from {old_count} to 0',
        ip_address=request.remote_addr
    )

    flash(f'Payout reset for {user.username} (was: {old_count})', 'success')
    return redirect(url_for('admin.users'))

# ============ SMS RANGES MANAGEMENT ============

@admin_bp.route('/ranges')
@primary_admin_required
def sms_ranges():
    page = request.args.get('page', 1, type=int)
    per_page = 25
    search = request.args.get('search', '')

    query = SMDRange.query

    if search:
        query = query.filter(
            db.or_(
                SMDRange.country.like(f'%{search}%'),
                SMDRange.name.like(f'%{search}%')
            )
        )

    ranges_list = query.order_by(SMDRange.country).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template('admin/sms_ranges.html', ranges=ranges_list)

def generate_150_test_numbers(range_id, base_number=None):
    from app.models.sms import SMSNumber
    from app import db
    import re
    
    if not base_number:
        first_num = SMSNumber.query.filter_by(range_id=range_id).first()
        if first_num:
            base_number = first_num.number
        else:
            base_number = "+447123456789"

    is_plus = base_number.startswith('+')
    digits_only = re.sub(r'\D', '', base_number)
    
    if len(digits_only) < 5:
        digits_only = "447123456789"
        is_plus = True

    prefix_digits = digits_only[:-3] if len(digits_only) > 3 else digits_only
    start_suffix = 100
    
    added_count = 0
    existing_numbers = set(num[0] for num in db.session.query(SMSNumber.number).all())
    
    for i in range(150):
        suffix = start_suffix + i
        candidate = f"{'+' if is_plus else ''}{prefix_digits}{suffix}"
        
        while candidate in existing_numbers:
            suffix += 1
            candidate = f"{'+' if is_plus else ''}{prefix_digits}{suffix}"
            
        test_num = SMSNumber(
            range_id=range_id,
            number=candidate,
            status='test',
            is_active=True
        )
        db.session.add(test_num)
        existing_numbers.add(candidate)
        added_count += 1
        
    db.session.commit()
    return added_count

@admin_bp.route('/ranges/create', methods=['GET', 'POST'])
@primary_admin_required
def create_sms_range():
    """Create single SMS range with file upload"""
    if request.method == 'POST':
        name = request.form.get('name')
        country = request.form.get('country')
        test_number = request.form.get('test_number')
        application = request.form.get('application', '')
        billing_cycle = request.form.get('billing_cycle', 'monthly')
        manual_price = request.form.get('manual_price', 0.0, type=float)

        # Verify TXT or CSV file
        csv_file = request.files.get('csv_file')
        csv_numbers = []
        raw = None
        if csv_file and csv_file.filename:
            try:
                raw = csv_file.read()
                try:
                    content = raw.decode('utf-8')
                except UnicodeDecodeError:
                    content = raw.decode('latin-1')
                lines = content.strip().split('\n')
                for line in lines:
                    cell = line.split(',')[0].strip()
                    if cell:
                        csv_numbers.append(cell)
            except Exception as e:
                flash(f'Error reading file: {str(e)}', 'danger')
                return redirect(url_for('admin.create_sms_range'))

        # Create range
        sms_range = SMDRange(
            name=name,
            country=country,
            test_number=test_number,
            application=application if application else None,
            billing_cycle=billing_cycle,
            manual_price=manual_price,
            cost_per_sms=0.005,
            is_active=True
        )
        db.session.add(sms_range)
        db.session.commit()

        # Store range file content in local database.
        if raw:
            try:
                sms_range.file_content = raw.decode('utf-8', errors='ignore')
                sms_range.file_url = url_for('admin.download_range_file', range_id=sms_range.id)
                db.session.commit()
                print(f"[LOCAL STORAGE] Saved range file content locally, download URL set to: {sms_range.file_url}")
            except Exception as fe:
                print(f"[LOCAL STORAGE] Failed saving range file content: {fe}")

        # Add numbers from CSV only
        created_count = 0
        skip_count = 0
        if csv_numbers:
            existing_numbers = set(
                num[0] for num in db.session.query(SMSNumber.number).all()
            )

            for num_str in csv_numbers:
                num_clean = num_str.strip()
                if not num_clean:
                    continue

                if num_clean in existing_numbers:
                    skip_count += 1
                    continue

                num = SMSNumber(
                    range_id=sms_range.id,
                    number=num_clean,
                    status='available',
                    is_active=True
                )
                db.session.add(num)
                created_count += 1
                existing_numbers.add(num_clean)

            db.session.commit()

            # Automatically generate 150 test numbers for this range
            try:
                generate_150_test_numbers(sms_range.id, test_number or (csv_numbers[0] if csv_numbers else None))
            except Exception as e:
                print(f"Error generating test numbers: {e}")

        ActivityLog.log(
            current_user.id,
            'admin_create_range',
            f'Created range {name} and added {created_count} numbers',
            ip_address=request.remote_addr
        )

        result_msg = f'Range {name} created with {created_count} numbers.'
        if skip_count > 0:
            result_msg += f' ({skip_count} numbers skipped - already exist)'
        flash(result_msg, 'success')
        return redirect(url_for('admin.sms_ranges'))

    return render_template('admin/range_form.html', range_obj=None)


@admin_bp.route('/ranges/create-multiple', methods=['GET', 'POST'])
@primary_admin_required
def create_sms_ranges_multiple():
    """Create multiple SMS ranges at once with separate files and prices"""
    if request.method == 'POST':
        # Get form data
        ranges_data = request.form.getlist('range_data')

        created_ranges = []
        total_numbers = 0

        for i, range_json in enumerate(ranges_data):
            if not range_json:
                continue

            try:
                import json
                data = json.loads(range_json)

                name = data.get('name', f'Range {i+1}')
                country = data.get('country', 'Unknown')
                application = data.get('application', '')
                billing_cycle = data.get('billing_cycle', 'monthly')
                manual_price = data.get('manual_price', 0.0)
                file_index = data.get('file_index', i)

                # Get the file for this range
                file_key = f'multi_csv_file_{file_index}'
                csv_file = request.files.get(file_key)

                csv_numbers = []
                if csv_file and csv_file.filename:
                    try:
                        raw = csv_file.read()
                        try:
                            content = raw.decode('utf-8')
                        except UnicodeDecodeError:
                            content = raw.decode('latin-1')
                        lines = content.strip().split('\n')
                        for line in lines:
                            cell = line.split(',')[0].strip()
                            if cell:
                                csv_numbers.append(cell)
                    except Exception:
                        continue

                # Create range
                sms_range = SMDRange(
                    name=name,
                    country=country,
                    application=application if application else None,
                    billing_cycle=billing_cycle,
                    manual_price=float(manual_price) if manual_price else 0.0,
                    cost_per_sms=0.005,
                    is_active=True
                )
                db.session.add(sms_range)
                db.session.commit()

                # Store range file content locally
                if csv_file and csv_file.filename and raw:
                    try:
                        sms_range.file_content = raw.decode('utf-8', errors='ignore')
                        sms_range.file_url = url_for('admin.download_range_file', range_id=sms_range.id)
                        db.session.commit()
                    except Exception as fe:
                        print(f"[LOCAL MULTI STORAGE] Failed saving multi range file content: {fe}")

                # Add numbers
                created_count = 0
                existing_numbers = set(
                    num[0] for num in db.session.query(SMSNumber.number).all()
                )

                for num_str in csv_numbers:
                    num_clean = num_str.strip()
                    if not num_clean or num_clean in existing_numbers:
                        continue

                    num = SMSNumber(
                        range_id=sms_range.id,
                        number=num_clean,
                        status='available',
                        is_active=True
                    )
                    db.session.add(num)
                    created_count += 1
                    existing_numbers.add(num_clean)

                db.session.commit()

                # Automatically generate 150 test numbers for this range
                try:
                    generate_150_test_numbers(sms_range.id, csv_numbers[0] if csv_numbers else None)
                except Exception as e:
                    print(f"Error generating test numbers for multiple ranges: {e}")

                created_ranges.append({'name': name, 'count': created_count})
                total_numbers += created_count

            except Exception as e:
                flash(f'Error creating range {i+1}: {str(e)}', 'warning')
                continue

        if created_ranges:
            ActivityLog.log(
                current_user.id,
                'admin_create_ranges_multiple',
                f'Created {len(created_ranges)} ranges with {total_numbers} numbers',
                ip_address=request.remote_addr
            )

            ranges_info = ', '.join([f"{r['name']} ({r['count']} numbers)" for r in created_ranges])
            flash(f'Successfully created {len(created_ranges)} ranges: {ranges_info}', 'success')
        else:
            flash('No ranges were created.', 'warning')

        return redirect(url_for('admin.sms_ranges'))

    return render_template('admin/range_form_multiple.html')

@admin_bp.route('/ranges/<int:range_id>/edit', methods=['GET', 'POST'])
@primary_admin_required
def edit_sms_range(range_id):
    range_obj = SMDRange.query.get_or_404(range_id)

    if request.method == 'POST':
        range_obj.name = request.form.get('name')
        range_obj.country = request.form.get('country')
        range_obj.application = request.form.get('application') or None
        range_obj.operator = request.form.get('operator')
        range_obj.network_type = request.form.get('network_type')
        range_obj.mcc = request.form.get('mcc')
        range_obj.mnc = request.form.get('mnc')
        range_obj.hlr_lookup = bool(request.form.get('hlr_lookup'))
        range_obj.cost_per_sms = request.form.get('cost_per_sms', 0.005, type=float)
        range_obj.currency = request.form.get('currency', 'USD')
        range_obj.rate = request.form.get('rate', 0.0, type=float)
        range_obj.payout = request.form.get('payout', 0.0, type=float)
        range_obj.test_number = request.form.get('test_number')
        range_obj.memo = request.form.get('memo')

        # New fields
        range_obj.billing_cycle = request.form.get('billing_cycle', 'monthly')
        range_obj.manual_price = request.form.get('manual_price', 0.0, type=float)

        is_active = request.form.get('is_active')
        range_obj.is_active = bool(is_active)

        db.session.commit()

        ActivityLog.log(
            current_user.id,
            'admin_edit_range',
            f'Edited range {range_obj.name}',
            ip_address=request.remote_addr
        )

        flash(f'Range {range_obj.name} updated.', 'success')
        return redirect(url_for('admin.sms_ranges'))

    return render_template('admin/range_form.html', range_obj=range_obj)

@admin_bp.route('/ranges/<int:range_id>/delete', methods=['GET', 'POST'])
@primary_admin_required
def delete_sms_range(range_id):
    range_obj = SMDRange.query.get_or_404(range_id)
    
    # Delete all numbers associated with this range (including assigned ones)
    SMSNumber.query.filter_by(range_id=range_id).delete()
    
    range_info = f'{range_obj.name or range_obj.country}'
    db.session.delete(range_obj)
    db.session.commit()

    ActivityLog.log(
        current_user.id,
        'admin_delete_range',
        f'Deleted range {range_info}',
        ip_address=request.remote_addr
    )

    flash(f'Range deleted successfully.', 'success')
    return redirect(url_for('admin.sms_ranges'))


@admin_bp.route('/ranges/<int:range_id>/download-file')
@login_required
def download_range_file(range_id):
    """Serve the raw file content directly from the database."""
    from flask import Response
    range_obj = SMDRange.query.get_or_404(range_id)
    if not range_obj.file_content:
        flash('No file content stored in database for this range.', 'warning')
        return redirect(request.referrer or url_for('admin.sms_ranges'))
    
    # Generate the download response
    response = Response(range_obj.file_content, mimetype='text/plain')
    safe_name = "".join(c for c in range_obj.name if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
    filename = f"range_{range_obj.id}_{safe_name if safe_name else 'file'}.txt"
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ============ SMS MANAGEMENT ============

@admin_bp.route('/sms/numbers')
@primary_admin_required
def sms_numbers():
    page = request.args.get('page', 1, type=int)
    per_page = 50
    search = request.args.get('search', '')
    agent_filter = request.args.get('agent', '')

    query = SMSNumber.query

    if search:
        query = query.filter(SMSNumber.number.like(f'%{search}%'))

    if agent_filter:
        query = query.filter_by(agent_id=agent_filter)

    numbers = query.order_by(SMSNumber.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    agents = User.query.filter(User.role.has(name='agent')).all()

    return render_template('admin/sms_numbers.html', numbers=numbers, agents=agents)

@admin_bp.route('/sms/send', methods=['GET', 'POST'])
@primary_admin_required
def sms_send():
    if request.method == 'POST':
        number = request.form.get('number')
        cli = request.form.get('cli')
        message = request.form.get('message')

        if not number or not cli or not message:
            flash('Number, CLI, and message are required.', 'danger')
            return redirect(url_for('admin.sms_send'))

        # Find the SMS number
        sms_number = SMSNumber.query.filter_by(number=number).first()
        if not sms_number:
            flash('SMS number not found.', 'danger')
            return redirect(url_for('admin.sms_send'))

        # Check if user has this number in their account
        # For admin, we allow sending from any number

        # Create CDR record
        cdr = SMSCDR(
            number_id=sms_number.id,
            range_id=sms_number.range_id,
            user_id=sms_number.agent_id,
            client_id=sms_number.client_id,
            cli=cli,
            destination=number,
            message=message,
            sms_type='sent',
            status='completed',
            profit=0.005, agent_payout=0.005  # Admin profit per SMS
        )

        db.session.add(cdr)
        db.session.commit()

        ActivityLog.log(
            current_user.id,
            'admin_send_sms',
            f'Sent SMS from {cli} to {number}',
            ip_address=request.remote_addr
        )

        flash('SMS sent successfully.', 'success')
        return redirect(url_for('admin.sms_send'))

    # Get all SMS numbers for the dropdown
    sms_numbers = SMSNumber.query.filter_by(is_active=True).all()
    return render_template('admin/sms_send.html', sms_numbers=sms_numbers)

@admin_bp.route('/sms/cdr')
@primary_admin_required
def sms_cdr():
    page = request.args.get('page', 1, type=int)
    per_page = 50

    # Date range - try to parse date with time first, then without time
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
    # Add time to end date to include the whole day
    date2 = date2.replace(hour=23, minute=59, second=59)

    query = SMSCDR.query.filter(
        SMSCDR.created_at >= date1,
        SMSCDR.created_at <= date2
    )

    cdr_records = query.order_by(SMSCDR.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Totals
    totals = db.session.query(
        db.func.count(SMSCDR.id).label('total'),
        db.func.sum(SMSCDR.profit).label('total_profit')
    ).filter(
        SMSCDR.created_at >= date1,
        SMSCDR.created_at <= date2
    ).first()

    return render_template('admin/sms_cdr.html',
        cdr_records=cdr_records,
        totals=totals,
        fdate1=fdate1,
        fdate2=fdate2
    )

# ============ ACTIVITY LOGS ============

@admin_bp.route('/activity')
@primary_admin_required
def activity_logs():
    page = request.args.get('page', 1, type=int)
    per_page = 50
    user_filter = request.args.get('user', '')
    action_filter = request.args.get('action', '')

    query = ActivityLog.query

    if user_filter:
        query = query.filter_by(user_id=user_filter)

    if action_filter:
        query = query.filter_by(action=action_filter)

    activities = query.order_by(ActivityLog.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    users = User.query.all()

    return render_template('admin/activity.html', activities=activities, users=users)

# ============ NEWS MANAGEMENT ============

@admin_bp.route('/news')
@primary_admin_required
def news():
    page = request.args.get('page', 1, type=int)
    per_page = 20

    news_list = News.query.order_by(News.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template('admin/news.html', news_list=news_list)

@admin_bp.route('/news/create', methods=['GET', 'POST'])
@primary_admin_required
def create_news():
    if request.method == 'POST':
        headline = request.form.get('headline')
        content = request.form.get('content')

        if not headline:
            flash('Headline is required.', 'danger')
            return redirect(url_for('admin.create_news'))

        news = News(
            headline=headline,
            content=content,
            created_by=current_user.id,
            is_active=True
        )

        db.session.add(news)
        db.session.commit()

        flash('News created successfully.', 'success')
        return redirect(url_for('admin.news'))

    return render_template('admin/news_form.html', news=None)

@admin_bp.route('/news/<int:news_id>/edit', methods=['GET', 'POST'])
@primary_admin_required
def edit_news(news_id):
    news = News.query.get_or_404(news_id)

    if request.method == 'POST':
        news.headline = request.form.get('headline')
        news.content = request.form.get('content')

        is_active = request.form.get('is_active')
        news.is_active = bool(is_active)

        db.session.commit()

        flash('News updated successfully.', 'success')
        return redirect(url_for('admin.news'))

    return render_template('admin/news_form.html', news=news)

@admin_bp.route('/news/<int:news_id>/delete', methods=['GET', 'POST'])
@primary_admin_required
def delete_news(news_id):
    news = News.query.get_or_404(news_id)
    db.session.delete(news)
    db.session.commit()

    flash('News deleted successfully.', 'success')
    return redirect(url_for('admin.news'))

# ============ SETTINGS ============

@admin_bp.route('/settings')
@primary_admin_required
def settings():
    return render_template('admin/settings.html')

@admin_bp.route('/settings/global-reset', methods=['GET', 'POST'])
@primary_admin_required
def global_reset_settings():
    from app.models.user import User
    
    if request.method == 'POST':
        reset_day = request.form.get('reset_day', type=int)
        monthly_limit = request.form.get('monthly_limit', type=float)
        
        if not reset_day or reset_day < 1 or reset_day > 28:
            flash('اليوم المحدد للتصفير يجب أن يكون بين 1 و 28.', 'danger')
            return redirect(url_for('admin.global_reset_settings'))
            
        if monthly_limit is None or monthly_limit < 0:
            flash('الحد الأدنى لطلب السحب التلقائي يجب أن يكون قيمة صحيحة وموجبة.', 'danger')
            return redirect(url_for('admin.global_reset_settings'))
            
        # Bulk update ALL users who are NOT administrators
        non_admins = User.query.filter(User.role_id != 1).all()
        for user in non_admins:
            user.reset_day = reset_day
            user.monthly_limit = monthly_limit
        
        db.session.commit()
        
        # Log the activity
        from app.models.activity import ActivityLog
        ActivityLog.log(
            user_id=current_user.id,
            action="bulk_update_resets",
            details=f"تحديث جماعي لإعدادات التصفير لجميع المستخدمين: اليوم {reset_day}، والحد الأدنى ${monthly_limit:.2f}",
            ip_address=request.remote_addr
        )
        
        flash(f'تم بنجاح تحديث وتطبيق اليوم المحدد ({reset_day}) والحد الأدنى (${monthly_limit:.2f}) على جميع مستخدمي النظام ({len(non_admins)} مستخدم) !', 'success')
        return redirect(url_for('admin.settings'))
        
    # Get current defaults from the first non-admin user
    sample_user = User.query.filter(User.role_id != 1).first()
    default_day = sample_user.reset_day if (sample_user and sample_user.reset_day) else 1
    default_limit = sample_user.monthly_limit if (sample_user and sample_user.monthly_limit is not None) else 50.0
    
    return render_template('admin/global_reset_settings.html', default_day=default_day, default_limit=default_limit)

@admin_bp.route('/settings/website-status', methods=['GET'])
@primary_admin_required
def website_status():
    from app.models.activity import News
    status_setting = News.query.filter_by(title='website_status').first()
    web_status = status_setting.content if status_setting else 'online'
    
    msg_setting = News.query.filter_by(title='maintenance_message').first()
    maintenance_message = msg_setting.content if msg_setting else 'الموقع تحت الصيانة حالياً. يرجى المحاولة لاحقاً.'
    
    return render_template(
        'admin/website_status.html',
        website_status=web_status,
        maintenance_message=maintenance_message
    )

@admin_bp.route('/settings/change-password', methods=['GET', 'POST'])
@primary_admin_required
def change_admin_password():
    if request.method == 'GET':
        return render_template('admin/change_password.html')
        
    current_password = request.form.get('current_password', '').strip()
    new_password = request.form.get('new_password', '').strip()
    confirm_password = request.form.get('confirm_password', '').strip()
    
    if not current_password or not new_password or not confirm_password:
        flash('جميع الحقول مطلوبة لتغيير كلمة المرور.', 'danger')
        return redirect(url_for('admin.change_admin_password'))
        
    if new_password != confirm_password:
        flash('كلمتا المرور الجديدتان غير متطابقتين.', 'danger')
        return redirect(url_for('admin.change_admin_password'))
        
    if not current_user.check_password(current_password):
        flash('كلمة المرور الحالية غير صحيحة.', 'danger')
        return redirect(url_for('admin.change_admin_password'))
        
    current_user.set_password(new_password)
    db.session.commit()
    flash('تم تغيير كلمة المرور للمالك الأساسي بنجاح!', 'success')
    return redirect(url_for('admin.change_admin_password'))

@admin_bp.route('/settings/toggle-website', methods=['POST'])
@primary_admin_required
def toggle_website():
    from app.models.activity import News
    web_status = request.form.get('website_status', 'online').strip()
    maintenance_message = request.form.get('maintenance_message', '').strip()
    
    status_setting = News.query.filter_by(title='website_status').first()
    if not status_setting:
        status_setting = News(title='website_status', headline='System Status', content=web_status)
        db.session.add(status_setting)
    else:
        status_setting.content = web_status
        
    msg_setting = News.query.filter_by(title='maintenance_message').first()
    if not msg_setting:
        msg_setting = News(title='maintenance_message', headline='Maintenance Message', content=maintenance_message)
        db.session.add(msg_setting)
    else:
        msg_setting.content = maintenance_message
        
    db.session.commit()
    
    if web_status == 'offline':
        flash('تم إيقاف الموقع بنجاح وتحويله إلى وضع الصيانة!', 'warning')
    else:
        flash('تم تشغيل الموقع بنجاح وإعادته للعمل على الإنترنت!', 'success')
        
    return redirect(url_for('admin.website_status'))

@admin_bp.route('/settings/sms-limit', methods=['POST'])
@admin_required
def update_sms_limit():
    user_id = request.form.get('user_id', type=int)
    sms_limit = request.form.get('sms_limit', 0, type=int)

    if not user_id:
        return jsonify({'error': 'User ID required'}), 400

    user = User.query.get_or_404(user_id)
    user.sms_limit = sms_limit
    db.session.commit()

    return jsonify({'success': True})

# ============ AGENT MANAGEMENT ============
# These routes are for Agent management of their numbers and clients

@admin_bp.route('/agent/add-numbers', methods=['GET', 'POST'])
@login_required
def agent_add_numbers():
    """Agent adds numbers to their account"""
    # Verify user is an agent
    if not (current_user.is_agent() or current_user.is_admin()):
        flash('Access denied. Agent account required.', 'danger')
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        range_id = request.form.get('range_id', type=int)
        numbers_count = request.form.get('numbers_count', 0, type=int)

        if not range_id:
            flash('Please select a range.', 'danger')
            return redirect(url_for('admin.agent_add_numbers'))

        # Calculate current count of agent's numbers and verify against limit
        current_count = SMSNumber.query.filter_by(agent_id=current_user.id).count()
        max_total = current_user.sms_limit if current_user.sms_limit > 0 else 1
        remaining = max_total - current_count

        if remaining <= 0:
            flash(f'You have reached the maximum limit of {max_total} numbers.', 'warning')
            return redirect(url_for('admin.agent_add_numbers'))

        if numbers_count > remaining:
            flash(f'You can only add {remaining} more numbers. Adjusting to {remaining}.', 'warning')
            numbers_count = remaining

        # Get range
        sms_range = SMDRange.query.get(range_id)
        if not sms_range:
            flash('Invalid range selected.', 'danger')
            return redirect(url_for('admin.agent_add_numbers'))

        # Get available numbers from range
        available_numbers = SMSNumber.query.filter_by(
            range_id=range_id,
            agent_id=None,
            is_active=True
        ).limit(numbers_count).all()

        if not available_numbers:
            flash('No available numbers in this range.', 'warning')
            return redirect(url_for('admin.agent_add_numbers'))

        # Reserve numbers for the agent
        numbers_added = 0
        for num in available_numbers:
            num.agent_id = current_user.id
            num.status = 'reserved'
            num.assigned_at = datetime.utcnow()
            numbers_added += 1

        db.session.commit()

        # Log activity
        ActivityLog.log(
            current_user.id,
            'agent_add_numbers',
            f'Added {numbers_added} numbers from range {sms_range.name}',
            ip_address=request.remote_addr
        )

        flash(f'{numbers_added} numbers added to your account successfully!', 'success')
        return redirect(url_for('admin.sms_numbers'))

    # Get available ranges
    ranges = SMDRange.query.filter_by(is_active=True).all()

    # Calculate current numbers count
    current_numbers = SMSNumber.query.filter_by(agent_id=current_user.id).count()

    return render_template('admin/agent_add_numbers.html',
        ranges=ranges,
        current_numbers=current_numbers,
        max_numbers=current_user.sms_limit if current_user.sms_limit > 0 else 1
    )

@admin_bp.route('/agent/create-client', methods=['GET', 'POST'])
@login_required
def agent_create_client():
    """Agent creates a new client"""
    # Verify user is an agent
    if not (current_user.is_agent() or current_user.is_admin()):
        flash('Access denied. Agent account required.', 'danger')
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        name = request.form.get('name')
        company = request.form.get('company')
        country = request.form.get('country')
        numbers_count = request.form.get('numbers_count', 0, type=int)
        
        # Limit settings
        sms_limit = request.form.get('sms_limit', 0, type=int)
        monthly_limit = request.form.get('monthly_limit', 50.0, type=float)
        reset_day = request.form.get('reset_day', 1, type=int)

        if not username or not email or not password:
            flash('Username, email, and password are required.', 'danger')
            return redirect(url_for('admin.agent_create_client'))

        # Check that username and email do not already exist
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return redirect(url_for('admin.agent_create_client'))

        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
            return redirect(url_for('admin.agent_create_client'))

        # Get client role
        client_role = Role.query.filter_by(name='client').first()
        if not client_role:
            flash('Client role not found. Please contact admin.', 'danger')
            return redirect(url_for('admin.agent_create_client'))

        # Create client
        client = User(
            username=username,
            email=email,
            role_id=client_role.id,
            name=name,
            company=company,
            country=country,
            agent_id=current_user.id,  # Associate client with agent
            is_active=True,
            sms_limit=sms_limit,
            monthly_limit=monthly_limit,
            reset_day=reset_day
        )
        client.set_password(password)
        client.generate_api_token()

        db.session.add(client)
        db.session.commit()

        # Assign numbers to client if requested
        if numbers_count > 0:
            # Get agent's numbers
            agent_numbers = SMSNumber.query.filter_by(
                agent_id=current_user.id,
                client_id=None,
                is_active=True
            ).limit(numbers_count).all()

            for num in agent_numbers:
                num.client_id = client.id
                num.status = 'activated'

            db.session.commit()
            flash(f'{len(agent_numbers)} numbers assigned to client.', 'success')

        # Log activity
        ActivityLog.log(
            current_user.id,
            'agent_create_client',
            f'Created client {username}',
            ip_address=request.remote_addr
        )

        flash(f'Client {username} created successfully!', 'success')
        return redirect(url_for('main.clients'))

    return render_template('admin/agent_create_client.html')

@admin_bp.route('/agent/clients')
@login_required
def agent_clients():
    """Display agent's clients"""
    # Verify user is an agent
    if not (current_user.is_agent() or current_user.is_admin()):
        flash('Access denied. Agent account required.', 'danger')
        return redirect(url_for('main.dashboard'))

    page = request.args.get('page', 1, type=int)
    per_page = 25
    search = request.args.get('search', '')

    query = User.query.filter_by(agent_id=current_user.id)

    if search:
        query = query.filter(
            db.or_(
                User.username.like(f'%{search}%'),
                User.email.like(f'%{search}%'),
                User.name.like(f'%{search}%')
            )
        )

    clients = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template('admin/agent_clients.html', clients=clients)

@admin_bp.route('/agent/clients/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def agent_edit_client(user_id):
    if not (current_user.is_agent() or current_user.is_admin()):
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))

    client = User.query.get_or_404(user_id)
    if client.agent_id != current_user.id and not current_user.is_admin():
        flash('Access denied. This is not your client.', 'danger')
        return redirect(url_for('admin.agent_clients'))

    if request.method == 'POST':
        client.email = request.form.get('email')
        client.name = request.form.get('name')
        client.company = request.form.get('company')
        client.country = request.form.get('country')
        
        # Limit settings
        client.sms_limit = request.form.get('sms_limit', 0, type=int)
        client.monthly_limit = request.form.get('monthly_limit', 50.0, type=float)
        client.reset_day = request.form.get('reset_day', 1, type=int)
        
        is_active = request.form.get('is_active')
        client.is_active = bool(int(is_active) if is_active.isdigit() else is_active)

        new_password = request.form.get('password')
        if new_password and len(new_password) >= 6:
            client.set_password(new_password)

        db.session.commit()

        ActivityLog.log(current_user.id, 'agent_edit_client', f'Edited client {client.username}', ip_address=request.remote_addr)
        flash(f'Client {client.username} updated successfully.', 'success')
        return redirect(url_for('main.clients'))

    return render_template('admin/agent_edit_client.html', client=client)

@admin_bp.route('/agent/clients/<int:user_id>/delete', methods=['POST'])
@login_required
def agent_delete_client(user_id):
    if not (current_user.is_agent() or current_user.is_admin()):
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))

    client = User.query.get_or_404(user_id)
    if client.agent_id != current_user.id and not current_user.is_admin():
        flash('Access denied. This is not your client.', 'danger')
        return redirect(url_for('main.clients'))

    SMSNumber.query.filter_by(client_id=client.id).update({'client_id': None})
    username = client.username
    db.session.delete(client)
    db.session.commit()

    ActivityLog.log(current_user.id, 'agent_delete_client', f'Deleted client {username}', ip_address=request.remote_addr)
    flash(f'Client {username} deleted.', 'success')
    return redirect(url_for('main.clients'))

@admin_bp.route('/agent/clients/<int:user_id>/toggle-status', methods=['POST'])
@login_required
def agent_toggle_client_status(user_id):
    if not (current_user.is_agent() or current_user.is_admin()):
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))

    client = User.query.get_or_404(user_id)
    if client.agent_id != current_user.id and not current_user.is_admin():
        flash('Access denied. This is not your client.', 'danger')
        return redirect(url_for('main.clients'))

    client.is_active = not client.is_active
    db.session.commit()

    ActivityLog.log(current_user.id, 'agent_toggle_client_status', f'Toggled status of client {client.username} to {client.is_active}', ip_address=request.remote_addr)
    flash(f'Client {client.username} status updated.', 'success')
    return redirect(url_for('main.clients'))

@admin_bp.route('/agent/clients/<int:user_id>/manage-numbers', methods=['GET', 'POST'])
@login_required
def agent_manage_client_numbers(user_id):
    if not (current_user.is_agent() or current_user.is_admin()):
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))

    client = User.query.get_or_404(user_id)
    if client.agent_id != current_user.id and not current_user.is_admin():
        flash('Access denied. This is not your client.', 'danger')
        return redirect(url_for('admin.agent_clients'))

    # Available unassigned numbers for this agent
    available_numbers = SMSNumber.query.filter_by(
        agent_id=current_user.id if not current_user.is_admin() else client.agent_id,
        client_id=None
    ).count()

    # Numbers currently assigned to this client
    client_numbers = SMSNumber.query.filter_by(client_id=client.id).count()

    if request.method == 'POST':
        action = request.form.get('action')
        count = request.form.get('count', 0, type=int)

        if action == 'add':
            if count <= 0 or count > available_numbers:
                flash(f'Invalid count. You have {available_numbers} available.', 'danger')
            else:
                numbers_to_assign = SMSNumber.query.filter_by(
                    agent_id=current_user.id if not current_user.is_admin() else client.agent_id,
                    client_id=None
                ).limit(count).all()
                for num in numbers_to_assign:
                    num.client_id = client.id
                db.session.commit()
                flash(f'{len(numbers_to_assign)} numbers assigned to {client.username}.', 'success')
                ActivityLog.log(current_user.id, 'agent_assign_numbers', f'Assigned {len(numbers_to_assign)} to {client.username}', ip_address=request.remote_addr)

        elif action == 'remove':
            if count <= 0 or count > client_numbers:
                flash(f'Invalid count. Client has {client_numbers} numbers.', 'danger')
            else:
                numbers_to_remove = SMSNumber.query.filter_by(
                    client_id=client.id
                ).limit(count).all()
                for num in numbers_to_remove:
                    num.client_id = None
                db.session.commit()
                flash(f'{len(numbers_to_remove)} numbers removed from {client.username}.', 'success')
                ActivityLog.log(current_user.id, 'agent_remove_numbers', f'Removed {len(numbers_to_remove)} from {client.username}', ip_address=request.remote_addr)
        
        return redirect(url_for('admin.agent_manage_client_numbers', user_id=client.id))

    return render_template('admin/agent_manage_client_numbers.html', 
        client=client, 
        available_numbers=available_numbers,
        client_numbers=client_numbers)

@admin_bp.route('/agent/my-numbers')
@login_required
def agent_my_numbers():
    """Display agent's numbers"""
    # Verify user is an agent
    if not (current_user.is_agent() or current_user.is_admin()):
        flash('Access denied. Agent account required.', 'danger')
        return redirect(url_for('main.dashboard'))

    page = request.args.get('page', 1, type=int)
    per_page = 50
    search = request.args.get('search', '')

    query = SMSNumber.query.filter_by(agent_id=current_user.id)

    if search:
        query = query.filter(SMSNumber.number.like(f'%{search}%'))

    numbers = query.order_by(SMSNumber.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Calculate statistics
    total_numbers = SMSNumber.query.filter_by(agent_id=current_user.id).count()
    assigned_to_clients = SMSNumber.query.filter(
        SMSNumber.agent_id == current_user.id,
        SMSNumber.client_id.isnot(None)
    ).count()
    available = total_numbers - assigned_to_clients

    return render_template('admin/agent_my_numbers.html',
        numbers=numbers,
        total_numbers=total_numbers,
        assigned_to_clients=assigned_to_clients,
        available=available
    )

@admin_bp.route('/sms/numbers/<int:number_id>/unassign', methods=['POST'])
@primary_admin_required
def unassign_number(number_id):
    """Unassign a number from its agent and client without deleting it from the system."""
    number = SMSNumber.query.get_or_404(number_id)
    
    number.agent_id = None
    number.client_id = None
    number.status = 'available'
    number.assigned_at = None
    
    db.session.commit()
    
    ActivityLog.log(
        current_user.id,
        'admin_unassign_number',
        f'Unassigned number {number.number}',
        ip_address=request.remote_addr
    )
    
    flash(f'Number {number.number} has been unassigned and is now available.', 'success')
    return redirect(url_for('admin.sms_numbers'))

@admin_bp.route('/sms/numbers/<int:number_id>/delete', methods=['POST'])
@primary_admin_required
def delete_number(number_id):
    """Delete a number from the system even if it's assigned to a user."""
    number = SMSNumber.query.get_or_404(number_id)
    
    num_str = number.number
    db.session.delete(number)
    db.session.commit()
    
    ActivityLog.log(
        current_user.id,
        'admin_delete_number',
        f'Deleted number {num_str}',
        ip_address=request.remote_addr
    )
    
    flash(f'Number {num_str} has been deleted from the system.', 'success')
    return redirect(url_for('admin.sms_numbers'))

# ============ ADMIN ADD NUMBERS TO AGENT ============

@admin_bp.route('/admin/add-numbers-to-agent', methods=['GET', 'POST'])
@admin_required
def admin_add_numbers_to_agent():
    """Admin adds numbers to a specific agent"""
    if request.method == 'POST':
        # Search for agent by username
        agent_username = request.form.get('agent_username', '').strip()
        range_id = request.form.get('range_id', type=int)
        numbers_count = request.form.get('numbers_count', 0, type=int)

        if not agent_username:
            flash('Please enter agent username.', 'danger')
            return redirect(url_for('admin.admin_add_numbers_to_agent'))

        if not range_id:
            flash('Please select a range.', 'danger')
            return redirect(url_for('admin.admin_add_numbers_to_agent'))

        if numbers_count <= 0:
            flash('Please enter a valid number of numbers.', 'danger')
            return redirect(url_for('admin.admin_add_numbers_to_agent'))

        # Search for agent by username
        agent = User.query.filter_by(username=agent_username).first()
        if not agent:
            flash(f'Agent "{agent_username}" not found.', 'danger')
            return redirect(url_for('admin.admin_add_numbers_to_agent'))

        # Check if user is an agent
        if not agent.is_agent():
            flash('Selected user is not an agent.', 'danger')
            return redirect(url_for('admin.admin_add_numbers_to_agent'))

        # Get the range
        sms_range = SMDRange.query.get(range_id)
        if not sms_range:
            flash('Invalid range selected.', 'danger')
            return redirect(url_for('admin.admin_add_numbers_to_agent'))

        # Get available numbers from the range
        available_numbers = SMSNumber.query.filter_by(
            range_id=range_id,
            agent_id=None,
            is_active=True
        ).limit(numbers_count).all()

        if not available_numbers:
            flash('No available numbers in this range.', 'warning')
            return redirect(url_for('admin.admin_add_numbers_to_agent'))

        # Assign numbers to agent
        numbers_added = 0
        added_numbers = []
        for num in available_numbers:
            num.agent_id = agent.id
            num.status = 'reserved'
            num.assigned_at = datetime.utcnow()
            added_numbers.append(f"{num.number} | {sms_range.name} | ${sms_range.cost_per_sms if sms_range.cost_per_sms else 0.0}")
            numbers_added += 1

        db.session.commit()

        # Log activity
        ActivityLog.log(
            current_user.id,
            'admin_add_numbers_to_agent',
            f'Added {numbers_added} numbers from range {sms_range.name} to agent {agent.username}',
            ip_address=request.remote_addr
        )

        flash(f'{numbers_added} numbers added to agent {agent.username} successfully!', 'success')

        # Download the added numbers file
        return download_added_numbers(added_numbers, agent.username)

    # Get all active ranges
    ranges = SMDRange.query.filter_by(is_active=True).all()

    return render_template('admin/admin_add_numbers_to_agent.html',
        ranges=ranges
    )


@admin_bp.route('/admin/ranges/allocate', methods=['GET', 'POST'])
@admin_required
def admin_allocate_range_numbers():
    """Admin allocates a specific number of numbers from a range to any User (Agent or Client)"""
    if request.method == 'POST':
        range_id = request.form.get('range_id', type=int)
        target_username = request.form.get('target_username', '').strip()
        numbers_count = request.form.get('numbers_count', 0, type=int)

        if not range_id:
            flash('الرجاء اختيار رينج.', 'danger')
            return redirect(url_for('admin.admin_allocate_range_numbers'))

        if not target_username:
            flash('الرجاء إدخال اسم المستخدم المستهدف.', 'danger')
            return redirect(url_for('admin.admin_allocate_range_numbers'))

        if numbers_count <= 0:
            flash('الرجاء إدخال عدد صالح من الأرقام.', 'danger')
            return redirect(url_for('admin.admin_allocate_range_numbers'))

        # Search for user
        target_user = User.query.filter_by(username=target_username).first()
        if not target_user:
            flash(f'المستخدم "{target_username}" غير موجود.', 'danger')
            return redirect(url_for('admin.admin_allocate_range_numbers'))

        # Get range
        sms_range = SMDRange.query.get(range_id)
        if not sms_range:
            flash('الرينج المحدد غير صالح.', 'danger')
            return redirect(url_for('admin.admin_allocate_range_numbers'))

        # Find available numbers in this range (agent_id is None, client_id is None, is_active is True)
        available_numbers = SMSNumber.query.filter_by(
            range_id=range_id,
            agent_id=None,
            client_id=None,
            is_active=True
        ).limit(numbers_count).all()

        if len(available_numbers) < numbers_count:
            flash(f'عذراً، الأرقام المتاحة غير كافية. المتبقي في هذا الرينج هو {len(available_numbers)} رقم فقط.', 'warning')
            return redirect(url_for('admin.admin_allocate_range_numbers', range_id=range_id, target_username=target_username))

        # Perform allocation
        assigned_numbers = []
        for num in available_numbers:
            if target_user.is_agent():
                num.agent_id = target_user.id
                num.client_id = None
                num.status = 'reserved'
            elif target_user.is_client():
                num.client_id = target_user.id
                # If client has a parent agent, set agent_id as well
                if target_user.agent_id:
                    num.agent_id = target_user.agent_id
                num.status = 'activated'
            else:
                # Other roles (admin/developer)
                num.agent_id = target_user.id
                num.status = 'reserved'
            
            num.assigned_at = datetime.utcnow()
            assigned_numbers.append(f"{num.number} | {sms_range.name} | ${sms_range.cost_per_sms if sms_range.cost_per_sms else 0.0}")

        db.session.commit()

        # Log activity
        ActivityLog.log(
            current_user.id,
            'admin_allocate_range_numbers',
            f'Allocated {len(assigned_numbers)} numbers from range {sms_range.name} to {target_user.username}',
            ip_address=request.remote_addr
        )

        flash(f'✅ تم تخصيص {len(assigned_numbers)} رقم من الرينج {sms_range.name} للمستخدم {target_user.username} بنجاح!', 'success')
        
        # Download numbers file as a receipt
        return download_added_numbers(assigned_numbers, target_user.username)

    # GET request
    ranges = SMDRange.query.filter_by(is_active=True).all()
    selected_range_id = request.args.get('range_id', type=int)
    target_username = request.args.get('target_username', '').strip()

    return render_template(
        'admin/admin_allocate_range_numbers.html',
        ranges=ranges,
        selected_range_id=selected_range_id,
        target_username=target_username
    )


def download_added_numbers(numbers_list, agent_username):
    """Download text file with added numbers"""
    content = "\n".join(numbers_list)

    response = make_response(content)
    response.headers['Content-Type'] = 'text/plain'
    response.headers['Content-Disposition'] = f'attachment; filename=numbers_added_to_{agent_username}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.txt'

    return response

# ============ AGENT DOWNLOAD NUMBERS ============

@admin_bp.route('/agent/download-numbers', methods=['GET', 'POST'])
@login_required
def agent_download_numbers():
    """Download agent's numbers as text file"""
    # Check if user is agent
    if not (current_user.is_agent() or current_user.is_admin()):
        flash('Access denied. Agent account required.', 'danger')
        return redirect(url_for('main.dashboard'))

    numbers_query = SMSNumber.query.filter_by(agent_id=current_user.id)

    # Handle selected IDs from POST
    if request.method == 'POST':
        selected_ids = request.form.get('selected_ids', '')
        if selected_ids:
            ids_list = [int(x.strip()) for x in selected_ids.split(',') if x.strip().isdigit()]
            numbers_query = numbers_query.filter(SMSNumber.id.in_(ids_list))

    numbers = numbers_query.all()

    if not numbers:
        flash('No numbers found to download.', 'warning')
        return redirect(url_for('admin.agent_my_numbers'))

    # Generate text content
    content = ""
    for num in numbers:
        range_name = num.sms_range.name if num.sms_range else 'Unknown'
        price = num.sms_range.cost_per_sms if num.sms_range and num.sms_range.cost_per_sms else 0.0
        content += f"{num.number} | {range_name} | ${price}\n"

    # Create response
    response = make_response(content)
    response.headers['Content-Type'] = 'text/plain'
    response.headers['Content-Disposition'] = f'attachment; filename=numbers_{current_user.username}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.txt'

    return response

# ============ ADMIN DELETE NUMBERS FROM AGENT ============

@admin_bp.route('/admin/delete-numbers-from-agent', methods=['GET', 'POST'])
@admin_required
def admin_delete_numbers_from_agent():
    """Admin deletes numbers from a specific agent"""
    if request.method == 'POST':
        agent_username = request.form.get('agent_username', '').strip()
        range_id = request.form.get('range_id', type=int)

        if not agent_username:
            flash('Please enter agent username.', 'danger')
            return redirect(url_for('admin.admin_delete_numbers_from_agent'))

        if not range_id:
            flash('Please select a range.', 'danger')
            return redirect(url_for('admin.admin_delete_numbers_from_agent'))

        # Get the agent by username
        agent = User.query.filter_by(username=agent_username).first()
        if not agent:
            flash(f'Agent "{agent_username}" not found.', 'danger')
            return redirect(url_for('admin.admin_delete_numbers_from_agent'))

        # Get the range
        sms_range = SMDRange.query.get(range_id)
        if not sms_range:
            flash('Range not found.', 'danger')
            return redirect(url_for('admin.admin_delete_numbers_from_agent'))

        # Get numbers to delete (only those assigned to this agent)
        numbers_to_delete = SMSNumber.query.filter_by(
            agent_id=agent.id,
            range_id=range_id
        ).all()

        if not numbers_to_delete:
            flash('No numbers found for this agent in the selected range.', 'warning')
            return redirect(url_for('admin.admin_delete_numbers_from_agent'))

        # Get count before deletion for logging
        numbers_count = len(numbers_to_delete)

        # Permanently delete the numbers
        for num in numbers_to_delete:
            db.session.delete(num)

        db.session.commit()

        # Log activity
        ActivityLog.log(
            current_user.id,
            'admin_delete_numbers_from_agent',
            f'Deleted {numbers_count} numbers from range {sms_range.name} of agent {agent.username}',
            ip_address=request.remote_addr
        )

        flash(f'{numbers_count} numbers permanently deleted from agent {agent.username}!', 'success')
        return redirect(url_for('admin.admin_delete_numbers_from_agent'))

    return render_template('admin/admin_delete_numbers_from_agent.html')

# ============ GET AGENT RANGES (API) ============

@admin_bp.route('/admin/get-agent-ranges/<int:agent_id>')
@admin_required
def get_agent_ranges(agent_id):
    """Get ranges that have numbers assigned to a specific agent"""
    # Get distinct ranges with numbers for this agent
    ranges_data = db.session.query(
        SMDRange.id,
        SMDRange.country,
        db.func.count(SMSNumber.id).label('count')
    ).join(SMSNumber, SMSNumber.range_id == SMDRange.id
    ).filter(
        SMSNumber.agent_id == agent_id
    ).group_by(SMDRange.id).all()

    ranges = [{'id': r.id, 'country': r.country, 'count': r.count} for r in ranges_data]

    return jsonify({'ranges': ranges})

@admin_bp.route('/admin/get-agent-range-count/<int:agent_id>/<int:range_id>')
@admin_required
def get_agent_range_count(agent_id, range_id):
    """Get count of numbers for a specific agent and range"""
    count = SMSNumber.query.filter_by(
        agent_id=agent_id,
        range_id=range_id
    ).count()

    return jsonify({'count': count})

# ============ SEARCH USER API ============

@admin_bp.route('/admin/search-user')
@admin_required
def search_user():
    """Search for user by username"""
    username = request.args.get('username', '').strip()

    if not username:
        return jsonify({'found': False, 'message': 'Username is required'})

    user = User.query.filter_by(username=username).first()

    if not user:
        return jsonify({'found': False})

    return jsonify({
        'found': True,
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'role': user.role.name if user.role else 'unknown',
        'is_active': user.is_active
    })

# ============ SEARCH RANGE API ============

@admin_bp.route('/admin/search-range')
@admin_required
def search_range():
    """Search for range by name"""
    name = request.args.get('name', '').strip()

    if not name:
        return jsonify({'found': False, 'message': 'Range name is required'})

    # Try searching for exact or partial match
    smd_range = SMDRange.query.filter(SMDRange.name.ilike(f'%{name}%')).first()

    if not smd_range:
        return jsonify({'found': False})

    # Count of unallocated active numbers
    available_count = SMSNumber.query.filter_by(
        range_id=smd_range.id,
        agent_id=None,
        client_id=None,
        is_active=True
    ).count()

    return jsonify({
        'found': True,
        'id': smd_range.id,
        'name': smd_range.name,
        'country': smd_range.country,
        'cost_per_sms': float(smd_range.cost_per_sms) if smd_range.cost_per_sms else 0.0,
        'available_count': available_count
    })

# ============ CLIENT MANAGEMENT (ADMIN) ============

@admin_bp.route('/admin/clients')
@admin_required
def admin_clients():
    """Admin manages all clients and their numbers"""
    page = request.args.get('page', 1, type=int)
    per_page = 25
    search = request.args.get('search', '')
    agent_filter = request.args.get('agent', '')

    query = User.query.filter(User.role.has(name='client'))

    if search:
        query = query.filter(
            db.or_(
                User.username.like(f'%{search}%'),
                User.email.like(f'%{search}%'),
                User.name.like(f'%{search}%')
            )
        )

    if agent_filter:
        query = query.filter_by(agent_id=agent_filter)

    clients = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    agents = User.query.filter(User.role.has(name='agent')).all()

    return render_template('admin/admin_clients.html',
        clients=clients,
        agents=agents
    )

@admin_bp.route('/admin/add-numbers-to-client', methods=['GET', 'POST'])
@admin_required
def admin_add_numbers_to_client():
    """Admin adds numbers to a specific client"""
    if request.method == 'POST':
        client_username = request.form.get('client_username', '').strip()
        numbers_count = request.form.get('numbers_count', 0, type=int)

        if not client_username:
            flash('Please enter client username.', 'danger')
            return redirect(url_for('admin.admin_add_numbers_to_client'))

        if numbers_count <= 0:
            flash('Please enter a valid number of numbers.', 'danger')
            return redirect(url_for('admin.admin_add_numbers_to_client'))

        client = User.query.filter_by(username=client_username).first()
        if not client:
            flash(f'Client "{client_username}" not found.', 'danger')
            return redirect(url_for('admin.admin_add_numbers_to_client'))

        if not client.is_client():
            flash('Selected user is not a client.', 'danger')
            return redirect(url_for('admin.admin_add_numbers_to_client'))

        # Get available numbers from the parent agent
        if client.agent_id:
            available_numbers = SMSNumber.query.filter_by(
                agent_id=client.agent_id,
                client_id=None,
                is_active=True
            ).limit(numbers_count).all()
        else:
            flash('Client has no agent assigned.', 'danger')
            return redirect(url_for('admin.admin_add_numbers_to_client'))

        if not available_numbers:
            flash('No available numbers for this client.', 'warning')
            return redirect(url_for('admin.admin_add_numbers_to_client'))

        # Assign numbers to client
        numbers_added = []
        for num in available_numbers:
            num.client_id = client.id
            num.status = 'activated'
            range_name = num.sms_range.name if num.sms_range else 'Unknown'
            price = num.sms_range.cost_per_sms if num.sms_range and num.sms_range.cost_per_sms else 0.0
            numbers_added.append(f"{num.number} | {range_name} | ${price}")

        db.session.commit()

        # Log activity
        ActivityLog.log(
            current_user.id,
            'admin_add_numbers_to_client',
            f'Added {len(numbers_added)} numbers to client {client.username}',
            ip_address=request.remote_addr
        )

        flash(f'{len(numbers_added)} numbers added to client {client.username}!', 'success')

        # Download file
        return download_client_numbers(numbers_added, client.username)

    return render_template('admin/admin_add_numbers_to_client.html')

@admin_bp.route('/admin/remove-numbers-from-client', methods=['GET', 'POST'])
@admin_required
def admin_remove_numbers_from_client():
    """Admin removes numbers from a specific client"""
    if request.method == 'POST':
        client_username = request.form.get('client_username', '').strip()
        numbers_count = request.form.get('numbers_count', 0, type=int)

        if not client_username:
            flash('Please enter client username.', 'danger')
            return redirect(url_for('admin.admin_remove_numbers_from_client'))

        if numbers_count <= 0:
            flash('Please enter a valid number of numbers.', 'danger')
            return redirect(url_for('admin.admin_remove_numbers_from_client'))

        client = User.query.filter_by(username=client_username).first()
        if not client:
            flash(f'Client "{client_username}" not found.', 'danger')
            return redirect(url_for('admin.admin_remove_numbers_from_client'))

        # Get client's numbers
        client_numbers = SMSNumber.query.filter_by(
            client_id=client.id
        ).limit(numbers_count).all()

        if not client_numbers:
            flash('No numbers found for this client.', 'warning')
            return redirect(url_for('admin.admin_remove_numbers_from_client'))

        removed_count = 0
        for num in client_numbers:
            num.client_id = None
            num.status = 'reserved'
            removed_count += 1

        db.session.commit()

        ActivityLog.log(
            current_user.id,
            'admin_remove_numbers_from_client',
            f'Removed {removed_count} numbers from client {client.username}',
            ip_address=request.remote_addr
        )

        flash(f'{removed_count} numbers removed from client {client.username}!', 'success')
        return redirect(url_for('admin.admin_clients'))

    return render_template('admin/admin_remove_numbers_from_client.html')


def download_client_numbers(numbers_list, client_username):
    """Download text file with client's numbers"""
    content = "\n".join(numbers_list)

    response = make_response(content)
    response.headers['Content-Type'] = 'text/plain'
    response.headers['Content-Disposition'] = f'attachment; filename=numbers_for_client_{client_username}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.txt'

    return response


# ============ MESSAGE DELETION SETTINGS ============

@admin_bp.route('/admin/message-settings', methods=['GET', 'POST'])
@admin_required
def message_settings():
    """Manage message deletion settings per client"""
    if request.method == 'POST':
        client_username = request.form.get('client_username', '').strip()
        delete_mode = request.form.get('delete_mode', 'never')  # never, minutes, hours
        delete_value = request.form.get('delete_value', 0, type=int)

        client = User.query.filter_by(username=client_username).first()
        if not client:
            flash(f'Client "{client_username}" not found.', 'danger')
            return redirect(url_for('admin.message_settings'))

        if not client.is_client():
            flash('Selected user is not a client.', 'danger')
            return redirect(url_for('admin.message_settings'))

        # Update client's message deletion settings
        if delete_mode == 'never':
            client.delete_messages_after = 0
        elif delete_mode == 'minutes':
            client.delete_messages_after = delete_value
        elif delete_mode == 'hours':
            client.delete_messages_after = delete_value * 60

        db.session.commit()

        flash(f'Message settings updated for client {client.username}.', 'success')
        return redirect(url_for('admin.message_settings'))

    # Get all clients
    clients = User.query.filter(User.role.has(name='client')).all()

    return render_template('admin/message_settings.html', clients=clients)

# ============ GET CLIENT NUMBERS API ============

@admin_bp.route('/admin/get-client-numbers')
@admin_required
def get_client_numbers():
    """Get numbers for a specific client"""
    username = request.args.get('username', '').strip()

    if not username:
        return jsonify({'error': 'Username is required', 'numbers': []})

    client = User.query.filter_by(username=username).first()

    if not client:
        return jsonify({'error': 'Client not found', 'numbers': []})

    numbers = SMSNumber.query.filter_by(client_id=client.id).all()

    return jsonify({
        'count': len(numbers),
        'numbers': [{
            'number': num.number,
            'range': num.sms_range.country if num.sms_range else '-',
            'status': num.status
        } for num in numbers]
    })


# ============ TELEGRAM BOT SETTINGS ============

@admin_bp.route('/telegram-settings', methods=['GET', 'POST'])
@primary_admin_required
def telegram_settings():
    """Configure Telegram bot connection for OTP delivery"""
    from flask import current_app

    if request.method == 'POST':
        bot_token = request.form.get('bot_token', '').strip()
        admin_chat_id = request.form.get('admin_chat_id', '').strip()
        enabled = request.form.get('enabled') == 'on'

        current_app.config['TELEGRAM_BOT_TOKEN'] = bot_token
        current_app.config['TELEGRAM_ADMIN_CHAT_ID'] = admin_chat_id
        current_app.config['TELEGRAM_ENABLED'] = enabled

        # Save to database
        from app.models.activity import News
        setting = News.query.filter_by(title='telegram_bot_token').first()
        if setting:
            setting.headline = 'Telegram Bot Token'
            setting.content = bot_token
            setting.is_active = enabled
        else:
            setting = News(
                title='telegram_bot_token',
                headline='Telegram Bot Token',
                content=bot_token,
                is_active=enabled
            )
            db.session.add(setting)

        setting_chat = News.query.filter_by(title='telegram_admin_chat_id').first()
        if setting_chat:
            setting_chat.headline = 'Telegram Admin Chat ID'
            setting_chat.content = admin_chat_id
        else:
            setting_chat = News(
                title='telegram_admin_chat_id',
                headline='Telegram Admin Chat ID',
                content=admin_chat_id,
                is_active=True
            )
            db.session.add(setting_chat)

        db.session.commit()

        flash('Telegram settings saved successfully.', 'success')
        return redirect(url_for('admin.telegram_settings'))

    from app.models.activity import News
    bot_token = News.query.filter_by(title='telegram_bot_token').first()
    admin_chat_id = News.query.filter_by(title='telegram_admin_chat_id').first()
    enabled = bot_token.is_active if bot_token else False

    return render_template('admin/telegram_settings.html',
        bot_token=bot_token.content if bot_token else '',
        admin_chat_id=admin_chat_id.content if admin_chat_id else '',
        enabled=enabled
    )

@admin_bp.route('/telegram/test', methods=['POST'])
@primary_admin_required
def telegram_test():
    """Test Telegram bot connection"""
    from flask import current_app
    import requests

    bot_token = request.form.get('bot_token', '').strip() or current_app.config.get('TELEGRAM_BOT_TOKEN', '')
    if not bot_token:
        from app.models.activity import News
        bot_token_setting = News.query.filter_by(title='telegram_bot_token').first()
        if bot_token_setting:
            bot_token = bot_token_setting.content
            current_app.config['TELEGRAM_BOT_TOKEN'] = bot_token

    if not bot_token:
        return jsonify({'success': False, 'error': 'Bot token not configured'})

    chat_id = request.form.get('chat_id', '').strip()
    message = request.form.get('message', 'Test message from DREEM SMS').strip()

    try:
        url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
        response = requests.post(url, json={
            'chat_id': chat_id,
            'text': message
        }, timeout=10)

        if response.status_code == 200:
            return jsonify({'success': True, 'message': 'Test message sent successfully'})
        else:
            return jsonify({'success': False, 'error': 'Failed to send message'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@admin_bp.route('/telegram/send-otp', methods=['POST'])
@primary_admin_required
def telegram_send_otp():
    """Send OTP to admin via Telegram"""
    from flask import current_app
    import requests
    import random

    bot_token = current_app.config.get('TELEGRAM_BOT_TOKEN', '')
    admin_chat_id = current_app.config.get('TELEGRAM_ADMIN_CHAT_ID', '')

    if not bot_token or not admin_chat_id:
        from app.models.activity import News
        if not bot_token:
            setting = News.query.filter_by(title='telegram_bot_token').first()
            if setting:
                bot_token = setting.content
                current_app.config['TELEGRAM_BOT_TOKEN'] = bot_token
        if not admin_chat_id:
            setting_chat = News.query.filter_by(title='telegram_admin_chat_id').first()
            if setting_chat:
                admin_chat_id = setting_chat.content
                current_app.config['TELEGRAM_ADMIN_CHAT_ID'] = admin_chat_id

    if not bot_token or not admin_chat_id:
        return jsonify({'success': False, 'error': 'Telegram not configured'})

    code = ''.join([str(random.randint(0, 9)) for _ in range(6)])

    try:
        url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
        response = requests.post(url, json={
            'chat_id': admin_chat_id,
            'text': f'Your DREEM SMS OTP Code: {code}'
        }, timeout=10)

        if response.status_code == 200:
            return jsonify({'success': True, 'code': code})
        else:
            return jsonify({'success': False, 'error': 'Failed to send OTP'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# ============ API SETTINGS ============

@admin_bp.route('/api-settings', methods=['GET', 'POST'])
@primary_admin_required
def api_settings():
    """Configure API settings and client tokens"""
    from app.models.activity import News

    if request.method == 'POST':
        webhook_secret = request.form.get('webhook_secret', '').strip()
        api_rate_limit = request.form.get('api_rate_limit', 100, type=int)

        setting_webhook = News.query.filter_by(title='api_webhook_secret').first()
        if setting_webhook:
            setting_webhook.headline = 'API Webhook Secret'
            setting_webhook.content = webhook_secret
        else:
            setting_webhook = News(
                title='api_webhook_secret',
                headline='API Webhook Secret',
                content=webhook_secret,
                is_active=True
            )
            db.session.add(setting_webhook)

        setting_rate = News.query.filter_by(title='api_rate_limit').first()
        if setting_rate:
            setting_rate.headline = 'API Rate Limit'
            setting_rate.content = str(api_rate_limit)
        else:
            setting_rate = News(
                title='api_rate_limit',
                headline='API Rate Limit',
                content=str(api_rate_limit),
                is_active=True
            )
            db.session.add(setting_rate)

        # Telegram OTP to Channel settings
        telegram_otp_enabled = request.form.get('telegram_otp_to_channel') == 'on'
        telegram_dest_type = request.form.get('telegram_destination_type', 'channel')
        telegram_channel_id = request.form.get('telegram_otp_channel_id', '').strip()

        setting_otp_enabled = News.query.filter_by(title='telegram_otp_to_channel').first()
        if setting_otp_enabled:
            setting_otp_enabled.headline = 'Telegram OTP to Channel'
            setting_otp_enabled.content = 'true' if telegram_otp_enabled else 'false'
            setting_otp_enabled.is_active = telegram_otp_enabled
        else:
            setting_otp_enabled = News(
                title='telegram_otp_to_channel',
                headline='Telegram OTP to Channel',
                content='true' if telegram_otp_enabled else 'false',
                is_active=telegram_otp_enabled
            )
            db.session.add(setting_otp_enabled)

        setting_dest_type = News.query.filter_by(title='telegram_destination_type').first()
        if setting_dest_type:
            setting_dest_type.headline = 'Telegram Destination Type'
            setting_dest_type.content = telegram_dest_type
        else:
            setting_dest_type = News(
                title='telegram_destination_type',
                headline='Telegram Destination Type',
                content=telegram_dest_type,
                is_active=True
            )
            db.session.add(setting_dest_type)

        setting_channel_id = News.query.filter_by(title='telegram_otp_channel_id').first()
        if setting_channel_id:
            setting_channel_id.headline = 'Telegram OTP Channel ID'
            setting_channel_id.content = telegram_channel_id
        else:
            setting_channel_id = News(
                title='telegram_otp_channel_id',
                headline='Telegram OTP Channel ID',
                content=telegram_channel_id,
                is_active=True
            )
            db.session.add(setting_channel_id)

        db.session.commit()
        flash('API settings saved successfully.', 'success')
        return redirect(url_for('admin.api_settings'))

    from app.models.activity import News
    webhook_secret = News.query.filter_by(title='api_webhook_secret').first()
    api_rate_limit = News.query.filter_by(title='api_rate_limit').first()

    telegram_otp_to_channel = News.query.filter_by(title='telegram_otp_to_channel').first()
    telegram_destination_type = News.query.filter_by(title='telegram_destination_type').first()
    telegram_otp_channel_id = News.query.filter_by(title='telegram_otp_channel_id').first()

    return render_template('admin/api_settings.html',
        webhook_secret=webhook_secret.content if webhook_secret else '',
        api_rate_limit=int(api_rate_limit.content) if api_rate_limit else 100,
        telegram_otp_to_channel=telegram_otp_to_channel.content == 'true' if telegram_otp_to_channel else False,
        telegram_destination_type=telegram_destination_type.content if telegram_destination_type else 'channel',
        telegram_otp_channel_id=telegram_otp_channel_id.content if telegram_otp_channel_id else ''
    )

@admin_bp.route('/api/regenerate-token', methods=['POST'])
@admin_required
def api_regenerate_token():
    """Regenerate API token for a user"""
    user_id = request.form.get('user_id', type=int)

    user = User.query.get_or_404(user_id)
    user.generate_api_token()
    db.session.commit()

    return jsonify({
        'success': True,
        'token': user.api_token
    })

# ============ SMPP SERVER SETTINGS ============

@admin_bp.route('/smpp-settings', methods=['GET', 'POST'])
@primary_admin_required
def smpp_settings():
    """Configure SMPP server settings for external SMS provider"""
    from app.models.activity import News

    if request.method == 'POST':
        smpp_host = request.form.get('smpp_host', '').strip()
        smpp_port = request.form.get('smpp_port', 2775, type=int)
        smpp_username = request.form.get('smpp_username', '').strip()
        smpp_password = request.form.get('smpp_password', '').strip()
        smpp_system_id = request.form.get('smpp_system_id', '').strip()
        smpp_enabled = request.form.get('smpp_enabled') == 'on'
        smpp_bind_type = request.form.get('smpp_bind_type', 'transceiver').strip()
        smpp_system_type = request.form.get('smpp_system_type', 'SMPP').strip()
        smpp_session_timeout = request.form.get('smpp_session_timeout', 60, type=int)
        smpp_enquire_interval = request.form.get('smpp_enquire_interval', 30, type=int)

        # API settings
        smpp_api_enabled = request.form.get('smpp_api_enabled') == 'on'
        smpp_api_url = request.form.get('smpp_api_url', '').strip()
        smpp_api_username = request.form.get('smpp_api_username', '').strip()
        smpp_api_key = request.form.get('smpp_api_key', '').strip()
        smpp_api_gateway_type = request.form.get('smpp_api_gateway_type', 'JASMIN').strip()

        settings_map = {
            'smpp_host': smpp_host,
            'smpp_port': str(smpp_port),
            'smpp_username': smpp_username,
            'smpp_password': smpp_password,
            'smpp_system_id': smpp_system_id,
            'smpp_enabled': 'true' if smpp_enabled else 'false',
            'smpp_bind_type': smpp_bind_type,
            'smpp_system_type': smpp_system_type,
            'smpp_session_timeout': str(smpp_session_timeout),
            'smpp_enquire_interval': str(smpp_enquire_interval),
            
            # API
            'smpp_api_enabled': 'true' if smpp_api_enabled else 'false',
            'smpp_api_url': smpp_api_url,
            'smpp_api_username': smpp_api_username,
            'smpp_api_key': smpp_api_key,
            'smpp_api_gateway_type': smpp_api_gateway_type
        }

        for key, value in settings_map.items():
            setting = News.query.filter_by(title=key).first()
            if setting:
                setting.headline = key.upper().replace('_', ' ')
                setting.content = value
            else:
                setting = News(
                    title=key,
                    headline=key.upper().replace('_', ' '),
                    content=value,
                    is_active=True
                )
                db.session.add(setting)

        db.session.commit()
        flash('SMPP settings saved successfully.', 'success')
        return redirect(url_for('admin.smpp_settings'))

    smpp_settings = {}
    setting_keys = [
        'smpp_host', 'smpp_port', 'smpp_username', 'smpp_password',
        'smpp_system_id', 'smpp_enabled', 'smpp_bind_type',
        'smpp_system_type', 'smpp_session_timeout', 'smpp_enquire_interval',
        'smpp_api_enabled', 'smpp_api_url', 'smpp_api_username',
        'smpp_api_key', 'smpp_api_gateway_type'
    ]
    for key in setting_keys:
        setting = News.query.filter_by(title=key).first()
        default_values = {
            'smpp_port': '2775',
            'smpp_bind_type': 'transceiver',
            'smpp_system_type': 'SMPP',
            'smpp_session_timeout': '60',
            'smpp_enquire_interval': '30',
            'smpp_api_gateway_type': 'JASMIN',
            'smpp_api_url': 'http://localhost:1401/send'
        }
        smpp_settings[key] = setting.content if setting else default_values.get(key, '')

    smpp_settings['smpp_enabled'] = smpp_settings.get('smpp_enabled', 'false') == 'true'
    smpp_settings['smpp_api_enabled'] = smpp_settings.get('smpp_api_enabled', 'false') == 'true'

    from smpp.providers import load_providers
    from dataclasses import asdict
    providers_dicts = []
    try:
        providers_dicts = [asdict(p) for p in load_providers()]
    except Exception as e:
        print(f"Error loading suppliers: {e}")

    return render_template('admin/smpp_settings.html', providers=providers_dicts, **smpp_settings)

@admin_bp.route('/smpp/test', methods=['POST'])
@primary_admin_required
def smpp_test():
    """Test SMPP connection"""
    from app.models.activity import News
    import socket

    host = News.query.filter_by(title='smpp_host').first()
    port = News.query.filter_by(title='smpp_port').first()

    if not host or not port:
        return jsonify({'success': False, 'error': 'SMPP host not configured'})

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((host.content, int(port.content)))
        sock.close()

        if result == 0:
            return jsonify({'success': True, 'message': 'Connection successful'})
        else:
            return jsonify({'success': False, 'error': 'Connection refused'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# ============ SUPPLIER MANAGEMENT ENDPOINTS ============

def _get_providers_yaml_data():
    from smpp.config import PROVIDERS_FILE
    from smpp.yaml_helper import parse_yaml_file
    if not os.path.exists(PROVIDERS_FILE):
        return {'providers': []}
    try:
        data = parse_yaml_file(PROVIDERS_FILE)
        if not data or 'providers' not in data:
            return {'providers': []}
        return data
    except Exception as e:
        print(f"Error reading YAML: {e}")
        return {'providers': []}

def _save_providers_yaml_data(data):
    from smpp.config import PROVIDERS_FILE
    from smpp.yaml_helper import dump_yaml_file
    try:
        return dump_yaml_file(PROVIDERS_FILE, data)
    except Exception as e:
        print(f"Error saving YAML: {e}")
        return False

@admin_bp.route('/smpp-settings/add-supplier', methods=['POST'])
@primary_admin_required
def add_supplier():
    name = request.form.get('name', '').strip()
    host = request.form.get('host', '').strip()
    port = request.form.get('port', 2775, type=int)
    system_id = request.form.get('system_id', '').strip()
    password = request.form.get('password', '').strip()
    system_type = request.form.get('system_type', 'SMPP').strip()
    mode = request.form.get('mode', 'receiver').strip()
    ton = request.form.get('ton', 0, type=int)
    npi = request.form.get('npi', 0, type=int)
    address_range = request.form.get('address_range', '').strip()
    enabled = request.form.get('enabled') == 'on'
    auto_reconnect = request.form.get('auto_reconnect') == 'on'

    if not name or not host:
        flash('Supplier Name and Host are required.', 'danger')
        return redirect(request.referrer or url_for('admin.smpp_settings'))

    data = _get_providers_yaml_data()
    # Check if name already exists
    for p in data['providers']:
        if p.get('name') == name:
            flash(f'Supplier name "{name}" already exists.', 'danger')
            return redirect(request.referrer or url_for('admin.smpp_settings'))

    new_p = {
        'name': name,
        'host': host,
        'port': port,
        'system_id': system_id,
        'password': password,
        'system_type': system_type,
        'mode': mode,
        'interface_version': 34,
        'ton': ton,
        'npi': npi,
        'address_range': address_range,
        'heartbeat_interval': 30,
        'auto_reconnect': auto_reconnect,
        'reconnect_delay': 5,
        'connection_timeout': 10,
        'read_timeout': 60,
        'enabled': enabled
    }
    data['providers'].append(new_p)
    if _save_providers_yaml_data(data):
        flash(f'Supplier "{name}" added successfully.', 'success')
    else:
        flash('Failed to save supplier to configuration.', 'danger')
    return redirect(request.referrer or url_for('admin.smpp_settings'))

@admin_bp.route('/smpp-settings/edit-supplier', methods=['POST'])
@primary_admin_required
def edit_supplier():
    name = request.form.get('name', '').strip()
    host = request.form.get('host', '').strip()
    port = request.form.get('port', 2775, type=int)
    system_id = request.form.get('system_id', '').strip()
    password = request.form.get('password', '').strip()
    system_type = request.form.get('system_type', 'SMPP').strip()
    mode = request.form.get('mode', 'receiver').strip()
    ton = request.form.get('ton', 0, type=int)
    npi = request.form.get('npi', 0, type=int)
    address_range = request.form.get('address_range', '').strip()
    enabled = request.form.get('enabled') == 'on'
    auto_reconnect = request.form.get('auto_reconnect') == 'on'

    if not name or not host:
        flash('Supplier Name and Host are required.', 'danger')
        return redirect(request.referrer or url_for('admin.smpp_settings'))

    data = _get_providers_yaml_data()
    found = False
    for p in data['providers']:
        if p.get('name') == name:
            p['host'] = host
            p['port'] = port
            p['system_id'] = system_id
            p['password'] = password
            p['system_type'] = system_type
            p['mode'] = mode
            p['ton'] = ton
            p['npi'] = npi
            p['address_range'] = address_range
            p['enabled'] = enabled
            p['auto_reconnect'] = auto_reconnect
            found = True
            break

    if not found:
        flash(f'Supplier "{name}" not found.', 'danger')
        return redirect(request.referrer or url_for('admin.smpp_settings'))

    if _save_providers_yaml_data(data):
        flash(f'Supplier "{name}" updated successfully.', 'success')
    else:
        flash('Failed to save supplier to configuration.', 'danger')
    return redirect(request.referrer or url_for('admin.smpp_settings'))

@admin_bp.route('/smpp-settings/toggle-supplier/<name>', methods=['POST'])
@primary_admin_required
def toggle_supplier(name):
    data = _get_providers_yaml_data()
    found = False
    for p in data['providers']:
        if p.get('name') == name:
            p['enabled'] = not p.get('enabled', False)
            found = True
            break

    if not found:
        flash(f'Supplier "{name}" not found.', 'danger')
        return redirect(request.referrer or url_for('admin.smpp_settings'))

    if _save_providers_yaml_data(data):
        flash(f'Supplier state toggled successfully.', 'success')
    else:
        flash('Failed to update supplier state.', 'danger')
    return redirect(request.referrer or url_for('admin.smpp_settings'))

@admin_bp.route('/smpp-settings/delete-supplier/<name>', methods=['POST'])
@primary_admin_required
def delete_supplier(name):
    data = _get_providers_yaml_data()
    new_providers = [p for p in data['providers'] if p.get('name') != name]
    if len(new_providers) == len(data['providers']):
        flash(f'Supplier "{name}" not found.', 'danger')
        return redirect(url_for('admin.smpp_settings'))

    data['providers'] = new_providers
    if _save_providers_yaml_data(data):
        flash(f'Supplier "{name}" deleted successfully.', 'success')
    else:
        flash('Failed to delete supplier.', 'danger')
    return redirect(request.referrer or url_for('admin.smpp_settings'))

@admin_bp.route('/smpp/messages')
@primary_admin_required
def smpp_messages():
    """View SMPP Messages"""
    from app.models.sms import SMPPMessage
    page = request.args.get('page', 1, type=int)
    per_page = 50
    messages = SMPPMessage.query.order_by(SMPPMessage.receive_time.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return render_template('admin/smpp_messages.html', messages=messages)

@admin_bp.route('/smpp/status')
@primary_admin_required
def smpp_status():
    """Get SMPP connection status"""
    from app.models.activity import News
    from flask import current_app

    enabled = current_app.config.get('SMPP_ENABLED', False)
    host = News.query.filter_by(title='smpp_host').first()

    return jsonify({
        'enabled': enabled,
        'host': host.content if host else None,
        'status': 'connected' if enabled else 'disabled'
    })

# ============ TEST123 BOT SETTINGS ============

@admin_bp.route('/test123-bot-settings', methods=['GET', 'POST'])
@primary_admin_required
def test123_bot_settings():
    """
    Admin section to configure Telegram bot for test123 account.
    Settings include:
    - Channel ID for forwarding OTPs from test123
    - Bot Token for the bot that manages test123 numbers
    - Admin Chat ID for bot access
    """
    from app.models.activity import News

    if request.method == 'POST':
        channel_id = request.form.get('channel_id', '').strip()
        bot_token = request.form.get('bot_token', '').strip()
        admin_chat_id = request.form.get('admin_chat_id', '').strip()
        enabled = request.form.get('enabled') == 'on'

        # Save to news table (key-value store)
        settings = [
            ('test123_channel_id', channel_id),
            ('test123_bot_token', bot_token),
            ('test123_admin_chat_id', admin_chat_id),
            ('test123_enabled', 'true' if enabled else 'false')
        ]

        for title, content in settings:
            existing = News.query.filter_by(title=title).first()
            if existing:
                existing.content = content
            else:
                news = News(title=title, headline=title.replace('_', ' ').title(),
                           content=content, is_active=1)
                db.session.add(news)

        db.session.commit()
        flash('Test123 Bot settings updated.', 'success')
        return redirect(url_for('admin.test123_bot_settings'))

    # Load current settings
    settings = {}
    news_items = News.query.all()
    for item in news_items:
        if item.title.startswith('test123_'):
            settings[item.title] = item.content

    return render_template('admin/test123_bot_settings.html', settings=settings)


@admin_bp.route('/test123-bot/test', methods=['POST'])
@primary_admin_required
def test123_bot_test():
    """Test Telegram bot connection for test123"""
    import requests
    from app.models.activity import News

    bot_token = request.form.get('bot_token', '').strip()
    if not bot_token:
        return jsonify({'success': False, 'error': 'Bot token is required'})

    try:
        url = f'https://api.telegram.org/bot{bot_token}/getMe'
        response = requests.get(url, timeout=10)

        if response.status_code == 200:
            data = response.json()
            if data.get('ok'):
                return jsonify({
                    'success': True,
                    'bot_name': data['result'].get('first_name', 'Unknown'),
                    'username': data['result'].get('username', 'Unknown')
                })
            else:
                return jsonify({'success': False, 'error': 'Invalid bot token'})
        else:
            return jsonify({'success': False, 'error': 'Failed to connect to Telegram'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@admin_bp.route('/test123-bot/send-test-message', methods=['POST'])
@primary_admin_required
def test123_send_test_message():
    """Send a test message to the channel"""
    import requests
    from app.models.activity import News

    bot_token = request.form.get('bot_token', '').strip()
    channel_id = request.form.get('channel_id', '').strip()

    if not bot_token or not channel_id:
        return jsonify({'success': False, 'error': 'Bot token and channel ID are required'})

    try:
        url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
        response = requests.post(url, json={
            'chat_id': channel_id,
            'text': 'Test message from SMS Platform - Test123 Bot\nIf you see this, the bot is working correctly!'
        }, timeout=10)

        if response.status_code == 200:
            return jsonify({'success': True, 'message': 'Test message sent successfully'})
        else:
            return jsonify({'success': False, 'error': 'Failed to send message'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ============ DATABASE & SUPABASE SETTINGS ============

@admin_bp.route('/database-settings', methods=['GET', 'POST'])
@primary_admin_required
def database_settings():
    from flask import current_app
    env_path = os.path.abspath(os.path.join(current_app.root_path, '..', '.env'))
    h_env_path = os.path.abspath(os.path.join(current_app.root_path, '..', 'h.env'))
    
    if request.method == 'POST':
        db_url = request.form.get('database_url', '').strip()
        config_mode = request.form.get('config_mode', 'uri').strip()
        
        if config_mode == 'fields':
            host = request.form.get('db_host', '').strip()
            port = request.form.get('db_port', '5432').strip() or '5432'
            name = request.form.get('db_name', '').strip()
            user = request.form.get('db_user', '').strip()
            pass_val = request.form.get('db_password', '').strip()
            
            if host and name and user:
                db_url = f"postgresql://{user}:{pass_val}@{host}:{port}/{name}"
                
        if not db_url:
            flash('❌ عذراً، لم يتم إدخال رابط قاعدة البيانات بالكامل.', 'danger')
            return redirect(url_for('admin.database_settings'))
            
        # Clean up database URL
        clean_db_url = db_url
        if clean_db_url.startswith('postgres://'):
            clean_db_url = clean_db_url.replace('postgres://', 'postgresql://', 1)

        # Let's perform auto-migration and copy data from current SQLite to new Supabase database!
        migration_error = None
        try:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            from app import db
            from app.models.user import User, Role
            from app.models.sms import SMSSupplier, SMDRange, SMSNumber
            from app.models.activity import News
            from app.models.finance import BankAccount, PaymentRequest, CreditNote
            from app.models.developer import StaticAsset

            # 1. Create engine and tables on Supabase
            temp_engine = create_engine(clean_db_url)
            db.metadata.create_all(bind=temp_engine)

            # 2. Open Session
            TempSession = sessionmaker(bind=temp_engine)
            session = TempSession()

            # 3. Helper to copy tables from SQLite to PostgreSQL
            def migrate_table(model_class, source_query):
                try:
                    if session.query(model_class).count() == 0:
                        for item in source_query.all():
                            kwargs = {c.name: getattr(item, c.name) for c in model_class.__table__.columns}
                            session.add(model_class(**kwargs))
                        session.commit()
                        print(f"[MIGRATION] Migrated table {model_class.__tablename__} successfully.")
                except Exception as e:
                    session.rollback()
                    print(f"[MIGRATION] Failed to migrate table {model_class.__tablename__}: {e}")

            # 4. Perform migration
            migrate_table(Role, Role.query)
            migrate_table(User, User.query)
            migrate_table(SMSSupplier, SMSSupplier.query)
            migrate_table(SMDRange, SMDRange.query)
            migrate_table(SMSNumber, SMSNumber.query)
            migrate_table(News, News.query)
            migrate_table(BankAccount, BankAccount.query)
            migrate_table(PaymentRequest, PaymentRequest.query)
            migrate_table(CreditNote, CreditNote.query)
            migrate_table(StaticAsset, StaticAsset.query)

            # 5. Ensure at least default values exist if source was empty
            # Seed Roles
            for role_name, display in [('admin', 'Administrator'), ('agent', 'Agent'),
                                       ('client', 'Client'), ('developer', 'Developer')]:
                if not session.query(Role).filter_by(name=role_name).first():
                    session.add(Role(name=role_name, display_name=display))
            session.commit()

            # Seed Admin
            admin_role = session.query(Role).filter_by(name='admin').first()
            if not session.query(User).filter_by(username='admin').first():
                admin = User(
                    username='admin',
                    email='admin@system.local',
                    role=admin_role,
                    is_active=True,
                )
                admin.set_password('admin123')
                admin.generate_api_token()
                session.add(admin)
                session.commit()

            session.close()
            print("[SYSTEM] Successfully migrated and seeded Supabase database.")
        except Exception as e:
            migration_error = str(e)
            print(f"[SYSTEM] Error during Supabase migration: {e}")

        # Ensure .env exists by copying h.env if not present
        if not os.path.exists(env_path) and os.path.exists(h_env_path):
            import shutil
            shutil.copy(h_env_path, env_path)
            
        # Update .env
        lines = []
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                lines = f.readlines()
                
        new_lines = []
        found = False
        for line in lines:
            if line.strip().startswith('DATABASE_URL='):
                new_lines.append(f'DATABASE_URL={db_url}\n')
                found = True
            else:
                new_lines.append(line)
                
        if not found:
            new_lines.append(f'DATABASE_URL={db_url}\n')
            
        with open(env_path, 'w') as f:
            f.writelines(new_lines)
            
        # Also update os.environ so that the current session or a reload can reflect it
        os.environ['DATABASE_URL'] = db_url
        
        if migration_error:
            flash(f'⚠️ تم حفظ رابط الاتصال بـ .env، ولكن فشل إنشاء الجداول/المزامنة على سوبابيس: {migration_error}', 'warning')
        else:
            flash('✅ تم ربط قاعدة بيانات Supabase، وإنشاء الجداول، ومزامنة كافة السجلات والبيانات بنجاح تام! سيعمل الموقع على سوبابيس فور إعادة التشغيل.', 'success')
            
        return redirect(url_for('admin.database_settings'))
        
    # GET request
    # Read DATABASE_URL from .env or os.environ
    current_db_url = os.environ.get('DATABASE_URL', '')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if line.strip().startswith('DATABASE_URL='):
                    current_db_url = line.strip().split('=', 1)[1]
                    break
                    
    is_using_postgres = current_db_url and ('postgres://' in current_db_url or 'postgresql://' in current_db_url)
    
    return render_template(
        'admin/database_settings.html',
        current_db_url=current_db_url,
        is_using_postgres=is_using_postgres
    )


@admin_bp.route('/database/test-connection', methods=['POST'])
@primary_admin_required
def database_test_connection():
    db_url = request.form.get('database_url', '').strip()
    if not db_url:
        return jsonify({'success': False, 'message': 'رابط الاتصال فارغ'})
        
    # Replace postgres:// with postgresql:// if needed for compatibility
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
        
    try:
        from sqlalchemy import create_engine, text
        # Create a temporary engine and test connection with short timeout
        engine = create_engine(db_url, connect_args={'connect_timeout': 5})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
