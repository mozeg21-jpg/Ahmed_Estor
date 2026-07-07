# Supplier Information - Receive Message (Deliver SM)
# This file is used to receive messages from the supplier (MO) and route them to the appropriate account.

from app.models.sms import SMSNumber, SMSCDR
from app.models.user import User
from app import db

class DeliverSMHandler:
    def __init__(self, supplier_id):
        self.supplier_id = supplier_id

    def handle_incoming_message(self, source_address, destination_address, text):
        """
        Example: Every message that arrives is routed to the account that owns the number.
        """
        # 1. Search for the number in the database
        sms_num = SMSNumber.query.filter_by(number=destination_address, is_active=True).first()
        
        if sms_num and sms_num.agent_id:
            # 2. Retrieve the account associated with the number
            user = User.query.get(sms_num.agent_id)
            if user:
                # 3. Save the message in the user's logs (CDR)
                cdr = SMSCDR(
                    number_id=sms_num.id,
                    range_id=sms_num.range_id,
                    user_id=user.id,
                    client_id=sms_num.client_id,
                    caller_id="external_msg_id", # To be replaced with the real message ID
                    destination=destination_address,
                    cli=source_address,
                    message=text,
                    sms_type="received",
                    status="completed",
                    currency="USD"
                )
                db.session.add(cdr)
                
                # Add earnings to the account
                payout = 0.005 # For example
                user.balance = (user.balance or 0.0) + payout
                
                db.session.commit()

                # Sync updated user and CDR to Firebase Firestore for dual-database persistence
                try:
                    from app.firebase_helper import sync_client_to_firebase, sync_cdr_to_firebase
                    sync_client_to_firebase(user)
                    if sms_num.client_id:
                        client_user = User.query.get(sms_num.client_id)
                        if client_user:
                            sync_client_to_firebase(client_user)
                    sync_cdr_to_firebase(cdr)
                except Exception as fe:
                    print(f"[FIREBASE INCOMING SYNC ERROR] {fe}")
                
                return True, "Message received and successfully routed to the account"
                
        return False, "No account found that owns this number"
