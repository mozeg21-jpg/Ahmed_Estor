from flask import Blueprint, request, jsonify
from app import db
from app.models.user import User
from app.models.sms import SMSCDR, SMSNumber
from datetime import datetime

user_api_bp = Blueprint('user_api', __name__)

@user_api_bp.route('/api/user/messages', methods=['GET'])
@user_api_bp.route('/api/v1/user/messages', methods=['GET'])
def get_user_messages():
    # 1. Read API Key from request (Headers or Query parameters)
    api_key = request.headers.get('X-API-Key')
    if not api_key:
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            api_key = auth_header.split('Bearer ')[1].strip()
    if not api_key:
        api_key = request.args.get('api_key')

    if not api_key:
        return jsonify({
            "status": "error",
            "message": "API Key is missing. Pass it via X-API-Key, Authorization: Bearer <key>, or api_key query param."
        }), 401

    # 2. Search for the API Key inside the database
    user = User.query.filter_by(api_key=api_key).first()

    # 3. Verify user exists
    if not user:
        return jsonify({
            "status": "error",
            "message": "Invalid API Key."
        }), 401

    # 4. Verify API is enabled for this user
    if not user.api_enabled:
        return jsonify({
            "status": "error",
            "message": "الـ API غير مفعل لهذا الحساب"
        }), 403

    # 5. Get user_id and fetch only their messages (no access to other users)
    user_numbers = SMSNumber.query.filter(
        db.or_(
            SMSNumber.agent_id == user.id,
            SMSNumber.client_id == user.id
        )
    ).all()
    number_ids = [n.id for n in user_numbers]

    query = SMSCDR.query.filter(
        db.or_(
            SMSCDR.user_id == user.id,
            SMSCDR.client_id == user.id,
            SMSCDR.number_id.in_(number_ids) if number_ids else False
        )
    )

    # Optional filters to retrieve new messages when added
    since_id = request.args.get('since_id', type=int)
    if since_id is not None:
        query = query.filter(SMSCDR.id > since_id)

    since_date = request.args.get('since_date')
    if since_date:
        try:
            parsed_date = datetime.fromisoformat(since_date)
            query = query.filter(SMSCDR.created_at > parsed_date)
        except ValueError:
            return jsonify({
                "status": "error",
                "message": "Invalid since_date format. Use ISO format (e.g. YYYY-MM-DDTHH:MM:SS)."
            }), 400

    # Sort
    sort_dir = request.args.get('sort', 'desc').lower()
    if sort_dir == 'asc':
        query = query.order_by(SMSCDR.id.asc())
    else:
        query = query.order_by(SMSCDR.id.desc())

    # Limit
    limit = min(request.args.get('limit', 100, type=int), 1000)
    messages = query.limit(limit).all()

    # 6. Build the response containing full messages with sender and recipient info
    result = []
    for msg in messages:
        # Resolve recipient number
        recipient_number = msg.destination
        if not recipient_number and msg.sms_number:
            recipient_number = msg.sms_number.number

        result.append({
            "id": msg.id,
            "sender": msg.cli or msg.caller_id,
            "recipient": recipient_number,
            "message": msg.message,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "sms_type": msg.sms_type,
            "status": msg.status
        })

    return jsonify({
        "status": "success",
        "total_count": len(result),
        "user_id": user.id,
        "username": user.username,
        "messages": result
    }), 200
