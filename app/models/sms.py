from app import db
from datetime import datetime


class SMDRange(db.Model):
    __tablename__ = 'sms_ranges'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    # Prefix removed - auto-detected from numbers
    country = db.Column(db.String(100), nullable=False)
    operator = db.Column(db.String(100))
    network_type = db.Column(db.String(20))
    mcc = db.Column(db.String(10))
    mnc = db.Column(db.String(10))
    hlr_lookup = db.Column(db.Boolean, default=False)
    max_numbers = db.Column(db.Integer, default=100000)

    # Billing cycle: 'monthly' or 'weekly'
    billing_cycle = db.Column(db.String(20), default='monthly')

    currency = db.Column(db.String(3), default='USD')
    # Manual price - admin sets this instead of auto calculation
    manual_price = db.Column(db.Float, default=0.0)
    rate = db.Column(db.Float, default=0.0)
    payout = db.Column(db.Float, default=0.0)
    cost_per_sms = db.Column(db.Float, default=0.005)

    application = db.Column(db.String(50))   # e.g. 'facebook', 'whatsapp'
    test_number = db.Column(db.String(50))
    memo = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    numbers = db.relationship('SMSNumber', backref='sms_range', lazy='dynamic')

    def __repr__(self):
        return f'<SMDRange {self.name} - {self.country}>'

    def get_reserved_count(self):
        return SMSNumber.query.filter_by(range_id=self.id).filter(
            SMSNumber.agent_id.isnot(None)
        ).count()

    def get_available_count(self):
        reserved = self.get_reserved_count()
        return max(0, (self.max_numbers or 100000) - reserved)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'country': self.country,
            'operator': self.operator,
            'network_type': self.network_type,
            'mcc': self.mcc,
            'mnc': self.mnc,
            'hlr_lookup': self.hlr_lookup,
            'max_numbers': self.max_numbers,
            'reserved_count': self.get_reserved_count(),
            'available_count': self.get_available_count(),
            'billing_cycle': self.billing_cycle,
            'currency': self.currency,
            'manual_price': self.manual_price,
            'rate': self.rate,
            'payout': self.payout,
            'cost_per_sms': self.cost_per_sms,
            'application': self.application,
            'test_number': self.test_number,
            'memo': self.memo,
            'is_active': self.is_active,
            'number_count': self.numbers.count()
        }


class SMSNumber(db.Model):
    __tablename__ = 'sms_numbers'

    id = db.Column(db.Integer, primary_key=True)
    range_id = db.Column(db.Integer, db.ForeignKey('sms_ranges.id'), nullable=False)
    number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    prefix = db.Column(db.String(20))
    agent_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    client_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    operator = db.Column(db.String(100))
    network_type = db.Column(db.String(20))
    mcc = db.Column(db.String(10))
    mnc = db.Column(db.String(10))
    short_number = db.Column(db.String(20))
    status = db.Column(db.String(20), default='available')
    reserved_at = db.Column(db.DateTime)
    activated_at = db.Column(db.DateTime)

    agent_payout = db.Column(db.Float, default=0.0)
    client_payout = db.Column(db.Float, default=0.0)

    daily_limit = db.Column(db.Integer, default=0)
    weekly_limit = db.Column(db.Integer, default=0)

    is_active = db.Column(db.Boolean, default=True)
    assigned_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    agent = db.relationship('User', foreign_keys=[agent_id], backref='assigned_numbers')
    client = db.relationship('User', foreign_keys=[client_id], backref='purchased_numbers')

    def __repr__(self):
        return f'<SMSNumber {self.number}>'

    def is_reserved(self):
        return self.agent_id is not None

    def to_dict(self):
        return {
            'id': self.id,
            'number': self.number,
            'prefix': self.prefix,
            'range_id': self.range_id,
            'range': self.sms_range.country if self.sms_range else None,
            'range_name': self.sms_range.name if self.sms_range else None,
            'agent_id': self.agent_id,
            'client_id': self.client_id,
            'client_name': self.client.username if self.client else None,
            'agent_payout': self.agent_payout,
            'client_payout': self.client_payout,
            'daily_limit': self.daily_limit,
            'weekly_limit': self.weekly_limit,
            'is_active': self.is_active,
            'is_reserved': self.is_reserved(),
            'assigned_at': self.assigned_at.isoformat() if self.assigned_at else None
        }


class SMSCDR(db.Model):
    __tablename__ = 'sms_cdr'

    id = db.Column(db.Integer, primary_key=True)
    number_id = db.Column(db.Integer, db.ForeignKey('sms_numbers.id'))
    range_id = db.Column(db.Integer, db.ForeignKey('sms_ranges.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    client_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    caller_id = db.Column(db.String(50))
    destination = db.Column(db.String(50))
    cli = db.Column(db.String(50))
    message = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    duration = db.Column(db.Integer, default=0)

    currency = db.Column(db.String(3), default='USD')
    rate = db.Column(db.Float, default=0.0)
    agent_payout = db.Column(db.Float, default=0.0)
    client_payout = db.Column(db.Float, default=0.0)
    profit = db.Column(db.Float, default=0.0)
    sms_type = db.Column(db.String(20), default='sent')  # 'sent' or 'received'
    status = db.Column(db.String(20), default='completed')

    # Relationships — backref names must not conflict with SMDRange.numbers
    sms_number = db.relationship('SMSNumber', foreign_keys=[number_id], backref='cdrs')
    range_info = db.relationship('SMDRange', foreign_keys=[range_id], backref='cdrs')

    def __repr__(self):
        return f'<SMSCDR {self.id} - {self.created_at}>'

    def to_dict(self):
        return {
            'id': self.id,
            'number_id': self.number_id,
            'number': self.sms_number.number if self.sms_number else None,
            'range_id': self.range_id,
            'range': self.range_info.country if self.range_info else None,
            'caller_id': self.caller_id,
            'cli': self.cli,
            'message': self.message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'duration': self.duration,
            'currency': self.currency,
            'rate': self.rate,
            'agent_payout': self.agent_payout,
            'client_payout': self.client_payout,
            'profit': self.profit,
            'sms_type': self.sms_type,
            'status': self.status
        }


class SMPPMessage(db.Model):
    __tablename__ = 'smpp_messages'

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(100))
    connection_id = db.Column(db.String(100))
    sender = db.Column(db.String(50))
    receiver = db.Column(db.String(50))
    message = db.Column(db.Text)
    message_id = db.Column(db.String(100))
    receive_time = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    status = db.Column(db.String(50))
    raw_pdu = db.Column(db.Text)
    encoding = db.Column(db.String(50))
    ton = db.Column(db.Integer)
    npi = db.Column(db.Integer)

    def to_dict(self):
        return {
            'id': self.id,
            'provider': self.provider,
            'connection_id': self.connection_id,
            'sender': self.sender,
            'receiver': self.receiver,
            'message': self.message,
            'message_id': self.message_id,
            'receive_time': self.receive_time.isoformat() if self.receive_time else None,
            'status': self.status,
            'raw_pdu': self.raw_pdu,
            'encoding': self.encoding,
            'ton': self.ton,
            'npi': self.npi
        }
