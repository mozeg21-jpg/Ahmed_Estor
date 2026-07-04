from app import db
from datetime import datetime

class BankAccount(db.Model):
    __tablename__ = 'bank_accounts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    bank_name = db.Column(db.String(150), nullable=False)
    account_name = db.Column(db.String(150), nullable=False)
    iban = db.Column(db.String(50), nullable=False)
    bic_swift = db.Column(db.String(20), nullable=False)
    currency = db.Column(db.String(3), default='USD') # USD, EUR, GBP
    status = db.Column(db.String(20), default='active') # active, inactive
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('bank_accounts', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'bank_name': self.bank_name,
            'account_name': self.account_name,
            'iban': self.iban,
            'bic_swift': self.bic_swift,
            'currency': self.currency,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class PaymentRequest(db.Model):
    __tablename__ = 'payment_requests'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), default='USD')
    bank_account_id = db.Column(db.Integer, db.ForeignKey('bank_accounts.id'), nullable=False)
    status = db.Column(db.String(20), default='pending') # pending, approved, rejected, cancelled
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime, nullable=True)
    attachment_path = db.Column(db.String(255), nullable=True)

    user = db.relationship('User', backref=db.backref('payment_requests', lazy='dynamic'))
    bank_account = db.relationship('BankAccount', backref=db.backref('payment_requests', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'amount': self.amount,
            'currency': self.currency,
            'bank_account_id': self.bank_account_id,
            'bank_name': self.bank_account.bank_name if self.bank_account else 'N/A',
            'status': self.status,
            'requested_at': self.requested_at.isoformat() if self.requested_at else None,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
            'attachment_path': self.attachment_path
        }

class CreditNote(db.Model):
    __tablename__ = 'credit_notes'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    note_number = db.Column(db.String(50), unique=True, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), default='USD')
    issue_date = db.Column(db.DateTime, default=datetime.utcnow)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='open') # open, closed, void
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('credit_notes', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'note_number': self.note_number,
            'amount': self.amount,
            'currency': self.currency,
            'issue_date': self.issue_date.isoformat() if self.issue_date else None,
            'description': self.description,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
