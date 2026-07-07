import os
from datetime import datetime

def check_and_process_monthly_resets():
    """
    Check if any user has reached their configured reset day for the current month.
    If they did, create an automatic payout/withdrawal request for their current balance,
    reset their balance to 0, and log the activity.
    """
    from datetime import datetime
    from app import db
    from app.models.user import User
    from app.models.finance import BankAccount, PaymentRequest
    from app.models.activity import ActivityLog

    try:
        now = datetime.utcnow()
        users = User.query.filter(User.balance > 0).all()

        for u in users:
            should_reset = False
            reset_reason = ""
            
            if now.day >= (u.reset_day or 1):
                if not (u.last_reset_date and u.last_reset_date.year == now.year and u.last_reset_date.month == now.month):
                    limit_threshold = u.monthly_limit if u.monthly_limit is not None else 50.0
                    if u.balance >= limit_threshold:
                        should_reset = True
                        reset_reason = f"بسبب الوصول لليوم المحدد للمزامنة والتصفير ({u.reset_day})"

            account_age = now - u.created_at
            if not should_reset and account_age.days >= 45 and u.balance >= 50.0:
                should_reset = True
                reset_reason = "بسبب تجاوز مدة 45 يوماً مع رصيد يتخطى $50"

            if not should_reset:
                continue

            balance_amount = u.balance
            if balance_amount <= 0.0:
                continue

            bank_acc = BankAccount.query.filter_by(user_id=u.id, status='active').first()
            if not bank_acc:
                bank_acc = BankAccount.query.filter_by(user_id=u.id).first()
            if not bank_acc:
                bank_acc = BankAccount(
                    user_id=u.id,
                    bank_name="Auto Payout System",
                    account_name=f"{u.username.upper()} AUTO",
                    iban=f"AUTO-IBAN-{u.id}-{now.strftime('%Y%m%d')}",
                    bic_swift="AUTOPAY",
                    currency="USD",
                    status="active"
                )
                db.session.add(bank_acc)
                db.session.commit()

            p_req = PaymentRequest(
                user_id=u.id,
                amount=balance_amount,
                currency="USD",
                bank_account_id=bank_acc.id,
                status="pending",
                requested_at=now
            )
            db.session.add(p_req)

            log_desc = f"طلب سحب تلقائي وتصفير حساب بقيمة ${balance_amount:.2f} {reset_reason}"
            ActivityLog.log(
                user_id=u.id,
                action="auto_reset_payout",
                description=log_desc,
                ip_address="127.0.0.1"
            )

            u.balance = 0.0
            u.last_reset_date = now
            db.session.commit()
            
        return True
    except Exception as e:
        print(f"[SYSTEM] Error in monthly resets: {e}")
        return False
