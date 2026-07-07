import os
import requests
import json
from datetime import datetime

class FirebaseFirestoreRESTClient:
    """
    A lightweight, pure-Python REST client for Firebase Firestore.
    Bypasses python pip install restrictions by using standard requests.
    """
    def __init__(self, project_id=None, api_key=None, database_id=None, storage_bucket=None):
        self.project_id = project_id or os.environ.get("FIREBASE_PROJECT_ID")
        self.api_key = api_key or os.environ.get("FIREBASE_API_KEY")
        self.database_id = database_id or os.environ.get("FIREBASE_DATABASE_ID")
        self.storage_bucket = storage_bucket or os.environ.get("FIREBASE_STORAGE_BUCKET")
        
        # Try loading from firebase-applet-config.json automatically
        try:
            # The config is in the root directory relative to /app/firebase_helper.py
            root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            config_path = os.path.join(root_dir, "firebase-applet-config.json")
            if os.path.exists(config_path):
                with open(config_path, "r") as f:
                    cfg = json.load(f)
                    if not self.project_id:
                        self.project_id = cfg.get("projectId")
                    if not self.api_key:
                        self.api_key = cfg.get("apiKey")
                    if not self.database_id:
                        self.database_id = cfg.get("firestoreDatabaseId")
                    if not self.storage_bucket:
                        self.storage_bucket = cfg.get("storageBucket")
        except Exception:
            pass

        if not self.database_id:
            self.database_id = "(default)"
        
        # Try loading dynamically from Volt SMS's News-based key-value store if running within Flask context
        try:
            from app.models.activity import News
            proj_setting = News.query.filter_by(title='firebase_project_id').first()
            key_setting = News.query.filter_by(title='firebase_api_key').first()
            db_setting = News.query.filter_by(title='firebase_database_id').first()
            bucket_setting = News.query.filter_by(title='firebase_storage_bucket').first()
            
            if proj_setting and proj_setting.content:
                self.project_id = proj_setting.content
            if key_setting and key_setting.content:
                self.api_key = key_setting.content
            if db_setting and db_setting.content:
                self.database_id = db_setting.content
            if bucket_setting and bucket_setting.content:
                self.storage_bucket = bucket_setting.content
        except Exception:
            pass # Not in Flask app context or DB not initialized yet

    @property
    def base_url(self):
        if not self.project_id:
            return None
        return f"https://firestore.googleapis.com/v1/projects/{self.project_id}/databases/{self.database_id}/documents"

    def _to_firestore_value(self, val):
        """Convert Python variable to Firestore API Value structure"""
        if val is None:
            return {"nullValue": None}
        elif isinstance(val, bool):
            return {"booleanValue": val}
        elif isinstance(val, (int, float)):
            if isinstance(val, int):
                return {"integerValue": str(val)}
            return {"doubleValue": val}
        elif isinstance(val, str):
            return {"stringValue": val}
        elif isinstance(val, datetime):
            return {"timestampValue": val.isoformat() + "Z"}
        elif isinstance(val, list):
            return {"arrayValue": {"values": [self._to_firestore_value(v) for v in val]}}
        elif isinstance(val, dict):
            return {"mapValue": {"fields": {k: self._to_firestore_value(v) for k, v in val.items()}}}
        else:
            return {"stringValue": str(val)}

    def _from_firestore_value(self, value_dict):
        """Convert Firestore API Value structure to native Python variable"""
        if not value_dict or not isinstance(value_dict, dict):
            return None
        
        for key, val in value_dict.items():
            if key == "nullValue":
                return None
            elif key == "booleanValue":
                return val
            elif key == "integerValue":
                return int(val)
            elif key == "doubleValue":
                return float(val)
            elif key == "stringValue":
                return val
            elif key == "timestampValue":
                return val # ISO string
            elif key == "arrayValue":
                values_list = val.get("values", [])
                return [self._from_firestore_value(item) for item in values_list]
            elif key == "mapValue":
                fields_dict = val.get("fields", {})
                return {k: self._from_firestore_value(v) for k, v in fields_dict.items()}
        return None

    def _to_firestore_document(self, python_dict):
        """Convert flat dictionary to Firestore Document body"""
        return {
            "fields": {k: self._to_firestore_value(v) for k, v in python_dict.items()}
        }

    def _from_firestore_document(self, doc_dict):
        """Convert Firestore Document response to simple Python dictionary"""
        if "fields" not in doc_dict:
            return {}
        
        doc_id = doc_dict.get("name", "").split("/")[-1]
        fields = doc_dict["fields"]
        result = {"_id": doc_id}
        for k, v in fields.items():
            result[k] = self._from_firestore_value(v)
        return result

    def test_connection(self):
        """Pings Firestore to check connection authorization"""
        if not self.base_url:
            return False, "Firebase Project ID not configured."
        
        url = f"{self.base_url}?pageSize=1"
        params = {}
        if self.api_key:
            params["key"] = self.api_key
            
        try:
            res = requests.get(url, params=params, timeout=8)
            if res.status_code == 200 or res.status_code == 404:
                return True, "Successfully connected to Firestore!"
            else:
                try:
                    err_msg = res.json().get("error", {}).get("message", res.text)
                except Exception:
                    err_msg = res.text
                return False, f"Connection failed with status {res.status_code}: {err_msg}"
        except Exception as e:
            return False, f"Connection exception occurred: {str(e)}"

    def save_document(self, collection_path, document_id, data_dict):
        """Creates or overwrites a document in a given Firestore collection"""
        if not self.base_url:
            raise ValueError("Firebase Project ID not configured.")
        
        url = f"{self.base_url}/{collection_path}/{document_id}"
        params = {}
        if self.api_key:
            params["key"] = self.api_key
            
        payload = self._to_firestore_document(data_dict)
        
        res = requests.patch(url, params=params, json=payload, timeout=8)
        if res.status_code == 200:
            return True, self._from_firestore_document(res.json())
        else:
            try:
                err_msg = res.json().get("error", {}).get("message", res.text)
            except Exception:
                err_msg = res.text
            return False, err_msg

    def get_document(self, collection_path, document_id):
        """Fetches a single document from a given Firestore collection"""
        if not self.base_url:
            raise ValueError("Firebase Project ID not configured.")
        
        url = f"{self.base_url}/{collection_path}/{document_id}"
        params = {}
        if self.api_key:
            params["key"] = self.api_key
            
        res = requests.get(url, params=params, timeout=8)
        if res.status_code == 200:
            return True, self._from_firestore_document(res.json())
        elif res.status_code == 404:
            return False, "Document not found"
        else:
            try:
                err_msg = res.json().get("error", {}).get("message", res.text)
            except Exception:
                err_msg = res.text
            return False, err_msg

    def list_documents(self, collection_path):
        """Lists all documents inside a collection using runQuery to bypass REST list restrictions"""
        if not self.project_id:
            raise ValueError("Firebase Project ID not configured.")
        
        url = f"https://firestore.googleapis.com/v1/projects/{self.project_id}/databases/{self.database_id}/documents:runQuery"
        params = {}
        if self.api_key:
            params["key"] = self.api_key
            
        payload = {
            "structuredQuery": {
                "from": [
                    {"collectionId": collection_path}
                ]
            }
        }
        
        try:
            res = requests.post(url, params=params, json=payload, timeout=10)
            if res.status_code == 200:
                results = res.json()
                docs = []
                if isinstance(results, list):
                    for item in results:
                        doc_dict = item.get("document")
                        if doc_dict:
                            docs.append(self._from_firestore_document(doc_dict))
                return True, docs
            else:
                # Fallback to GET list
                fallback_url = f"{self.base_url}/{collection_path}"
                fallback_res = requests.get(fallback_url, params=params, timeout=8)
                if fallback_res.status_code == 200:
                    docs = fallback_res.json().get("documents", [])
                    return True, [self._from_firestore_document(d) for d in docs]
                
                try:
                    err_msg = res.json().get("error", {}).get("message", res.text)
                except Exception:
                    err_msg = res.text
                return False, err_msg
        except Exception as e:
            return False, str(e)

    def delete_document(self, collection_path, document_id):
        """Deletes a document from a collection"""
        if not self.base_url:
            raise ValueError("Firebase Project ID not configured.")
        
        url = f"{self.base_url}/{collection_path}/{document_id}"
        params = {}
        if self.api_key:
            params["key"] = self.api_key
            
        res = requests.delete(url, params=params, timeout=8)
        if res.status_code == 200 or res.status_code == 204:
            return True, "Deleted successfully"
        else:
            try:
                err_msg = res.json().get("error", {}).get("message", res.text)
            except Exception:
                err_msg = res.text
            return False, err_msg

    def upload_to_firebase_storage(self, filename, file_data, content_type="application/octet-stream"):
        """
        Uploads a file directly to the configured Firebase Storage bucket via REST API.
        No credentials required if the bucket has public write rules.
        URL: https://firebasestorage.googleapis.com/v0/b/{bucket_name}/o?uploadType=media&name={filename}
        Returns: (success, download_url or error_message)
        """
        bucket_name = self.storage_bucket
        if not bucket_name and self.project_id:
            bucket_name = f"{self.project_id}.firebasestorage.app"
        if not bucket_name:
            return False, "Storage bucket not configured."
        
        url = f"https://firebasestorage.googleapis.com/v0/b/{bucket_name}/o"
        params = {
            "uploadType": "media",
            "name": filename
        }
        headers = {
            "Content-Type": content_type
        }
        if self.api_key:
            params["key"] = self.api_key
            
        try:
            res = requests.post(url, params=params, headers=headers, data=file_data, timeout=15)
            if res.status_code == 200:
                res_data = res.json()
                # Firebase Storage returns downloadTokens which are used to generate public links:
                download_token = res_data.get("downloadTokens", "")
                import urllib.parse
                encoded_name = urllib.parse.quote(filename, safe='')
                if download_token:
                    download_url = f"https://firebasestorage.googleapis.com/v0/b/{bucket_name}/o/{encoded_name}?alt=media&token={download_token}"
                else:
                    download_url = f"https://firebasestorage.googleapis.com/v0/b/{bucket_name}/o/{encoded_name}?alt=media"
                return True, download_url
            else:
                try:
                    err_text = res.json().get("error", {}).get("message", res.text)
                except Exception:
                    err_text = res.text
                return False, f"Upload failed with status {res.status_code}: {err_text}"
        except Exception as e:
            return False, f"Upload exception: {str(e)}"

# Ready-to-use helpers for Client / Client Data syncing as requested by user

def sync_client_to_firebase(client_user_object):
    """
    Helper function to sync/save a Volt SMS local User client model to Firestore.
    """
    try:
        client = FirebaseFirestoreRESTClient()
        if not client.project_id:
            return False, "Firebase not configured."
        
        data = {
            "username": client_user_object.username,
            "name": client_user_object.name or "",
            "email": client_user_object.email or "",
            "password_hash": client_user_object.password_hash or "",
            "is_active": client_user_object.is_active,
            "balance": float(client_user_object.balance or 0.0),
            "total_earned": float(client_user_object.total_earned or 0.0),
            "sms_limit": int(client_user_object.sms_limit or 0),
            "sms_count": int(client_user_object.sms_count or 0),
            "company": client_user_object.company or "",
            "address": client_user_object.address or "",
            "country": client_user_object.country or "",
            "skype": client_user_object.skype or "",
            "contact": client_user_object.contact or "",
            "agent_id": client_user_object.agent_id,
            "api_token": client_user_object.api_token or "",
            "role": client_user_object.role.name if client_user_object.role else "client",
            "last_login": client_user_object.last_login.isoformat() if client_user_object.last_login else None,
            "created_at": client_user_object.created_at.isoformat() if client_user_object.created_at else datetime.utcnow().isoformat(),
            "delete_messages_after": int(client_user_object.delete_messages_after or 0),
            "telegram_bot_token": client_user_object.telegram_bot_token or "",
            "telegram_chat_id": client_user_object.telegram_chat_id or "",
            "telegram_enabled": bool(client_user_object.telegram_enabled)
        }
        
        success, res = client.save_document("clients", client_user_object.username, data)
        return success, res
    except Exception as e:
        return False, str(e)


def delete_client_from_firebase(username):
    """
    Helper function to delete a user client from Firestore when they are deleted locally.
    """
    try:
        client = FirebaseFirestoreRESTClient()
        if not client.project_id:
            return False, "Firebase not configured."
        success, res = client.delete_document("clients", username)
        return success, res
    except Exception as e:
        return False, str(e)


def restore_clients_from_firebase(app):
    """
    On app startup, fetch all registered clients/users from Firestore and insert
    them into the local SQLite database if they don't exist.
    This prevents users from being "deleted automatically" on container restarts.
    """
    try:
        client = FirebaseFirestoreRESTClient()
        if not client.project_id:
            print("[FIREBASE RESTORE] Project ID not configured.")
            return False
        
        success, docs = client.list_documents("clients")
        if not success:
            print(f"[FIREBASE RESTORE] Failed to list documents: {docs}")
            return False
            
        from app import db
        from app.models.user import User, Role
        
        restored_count = 0
        with app.app_context():
            for doc in docs:
                doc_id = doc.get("_id", "")
                if doc_id.startswith("cdr_"):
                    # Skip SMS CDR logs stored in this collection
                    continue
                username = doc.get("username")
                if not username:
                    continue
                
                # Check if user already exists
                existing_user = User.query.filter_by(username=username).first()
                if existing_user:
                    # Sync updates from Firestore back to SQLite if needed
                    existing_user.balance = float(doc.get("balance", existing_user.balance or 0.0))
                    existing_user.is_active = bool(doc.get("is_active", existing_user.is_active))
                    existing_user.telegram_bot_token = doc.get("telegram_bot_token", existing_user.telegram_bot_token)
                    existing_user.telegram_chat_id = doc.get("telegram_chat_id", existing_user.telegram_chat_id)
                    existing_user.telegram_enabled = bool(doc.get("telegram_enabled", existing_user.telegram_enabled))
                    continue
                
                # Role lookup
                role_name = doc.get("role", "client")
                role = Role.query.filter_by(name=role_name).first()
                if not role:
                    role = Role.query.filter_by(name="client").first()
                
                # Create user from Firestore data
                new_user = User(
                    username=username,
                    email=doc.get("email", f"{username}@system.local"),
                    password_hash=doc.get("password_hash", ""),
                    role=role,
                    is_active=bool(doc.get("is_active", True)),
                    api_token=doc.get("api_token") or doc.get("api_key"),
                    name=doc.get("name"),
                    company=doc.get("company"),
                    address=doc.get("address"),
                    country=doc.get("country"),
                    skype=doc.get("skype"),
                    contact=doc.get("contact"),
                    agent_id=doc.get("agent_id"),
                    sms_limit=doc.get("sms_limit", 0),
                    sms_count=doc.get("sms_count", 0),
                    balance=float(doc.get("balance", 0.0)),
                    total_earned=float(doc.get("total_earned", 0.0)),
                    delete_messages_after=doc.get("delete_messages_after", 0),
                    telegram_bot_token=doc.get("telegram_bot_token"),
                    telegram_chat_id=doc.get("telegram_chat_id"),
                    telegram_enabled=bool(doc.get("telegram_enabled", False))
                )
                
                if not new_user.api_token:
                    new_user.generate_api_token()
                    
                db.session.add(new_user)
                restored_count += 1
                
            db.session.commit()
            if restored_count > 0:
                print(f"[FIREBASE RESTORE] Successfully restored {restored_count} users/clients from Firestore.")
            else:
                print("[FIREBASE RESTORE] No new users to restore.")
        return True
    except Exception as e:
        print(f"[FIREBASE RESTORE] Error restoring clients: {e}")
        return False


def sync_cdr_to_firebase(cdr_object):
    """
    Helper function to sync/save a Volt SMS local SMSCDR model to Firestore.
    Acts as a bridge for dual database support.
    """
    try:
        client = FirebaseFirestoreRESTClient()
        if not client.project_id:
            return False, "Firebase not configured."
        
        data = {
            "id": int(cdr_object.id) if cdr_object.id else None,
            "destination": cdr_object.destination or "",
            "cli": cdr_object.cli or "",
            "message": cdr_object.message or "",
            "caller_id": cdr_object.caller_id or "",
            "sms_type": cdr_object.sms_type or "received",
            "status": cdr_object.status or "completed",
            "agent_payout": float(cdr_object.agent_payout or 0.0),
            "client_payout": float(cdr_object.client_payout or 0.0),
            "profit": float(cdr_object.profit or 0.0),
            "currency": cdr_object.currency or "USD",
            "created_at": cdr_object.created_at.isoformat() if cdr_object.created_at else datetime.utcnow().isoformat(),
            "type": "sms_cdr"
        }
        
        raw_id = cdr_object.caller_id or f"{cdr_object.id or int(datetime.utcnow().timestamp())}"
        doc_id = f"cdr_{raw_id}"
        success, res = client.save_document("clients", doc_id, data)
        return success, res
    except Exception as e:
        return False, str(e)


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
        # Find all users with a balance > 0
        users = User.query.filter(User.balance > 0).all()

        for u in users:
            # Check if today is equal to or past their reset_day of this month
            if now.day >= (u.reset_day or 1):
                # Also ensure they haven't been reset yet in this calendar month
                if u.last_reset_date:
                    if u.last_reset_date.year == now.year and u.last_reset_date.month == now.month:
                        # Already reset this month
                        continue

                balance_amount = u.balance
                limit_threshold = u.monthly_limit if u.monthly_limit is not None else 50.0
                if balance_amount < limit_threshold:
                    # Balance has not reached the allowed limit yet, do not auto-withdraw/reset
                    continue
                if balance_amount <= 0.0:
                    continue

                # Find or create a bank account for the PaymentRequest
                bank_acc = BankAccount.query.filter_by(user_id=u.id, status='active').first()
                if not bank_acc:
                    bank_acc = BankAccount.query.filter_by(user_id=u.id).first()
                if not bank_acc:
                    # Create a seeded default bank account for this user so constraints are met
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

                # Create the payment request (payout)
                p_req = PaymentRequest(
                    user_id=u.id,
                    amount=balance_amount,
                    currency="USD",
                    bank_account_id=bank_acc.id,
                    status="pending",
                    requested_at=now
                )
                db.session.add(p_req)

                # Log the reset
                log_desc = f"طلب سحب تلقائي وتصفير حساب بقيمة ${balance_amount:.2f} بسبب الوصول لليوم المحدد للمزامنة والتصفير ({u.reset_day})"
                ActivityLog.log(
                    user_id=u.id,
                    action="auto_reset_payout",
                    description=log_desc,
                    ip_address="127.0.0.1"
                )

                # Reset user balance
                u.balance = 0.0
                u.last_reset_date = now
                db.session.commit()

                # Sync to Firebase
                try:
                    sync_client_to_firebase(u)
                except Exception as fe:
                    print(f"[RESET SYNC] Failed to sync reset balance to firebase: {fe}")
    except Exception as e:
        print(f"[RESET CHECK ERROR] {e}")


def restore_single_client_from_firebase(username):
    """
    On-demand fetch of a single user from Firestore to local SQLite.
    Extremely robust fallback for dual-database synchronization.
    """
    try:
        client = FirebaseFirestoreRESTClient()
        if not client.project_id:
            return None
        
        success, doc = client.get_document("clients", username)
        if not success or not doc:
            return None
            
        from app import db
        from app.models.user import User, Role
        
        # Double check if user exists now
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            return existing_user
            
        # Role lookup
        role_name = doc.get("role", "client")
        role = Role.query.filter_by(name=role_name).first()
        if not role:
            role = Role.query.filter_by(name="client").first()
            
        new_user = User(
            username=username,
            email=doc.get("email", f"{username}@system.local"),
            password_hash=doc.get("password_hash", ""),
            role=role,
            is_active=bool(doc.get("is_active", True)),
            api_token=doc.get("api_token") or doc.get("api_key"),
            name=doc.get("name"),
            company=doc.get("company"),
            address=doc.get("address"),
            country=doc.get("country"),
            skype=doc.get("skype"),
            contact=doc.get("contact"),
            agent_id=doc.get("agent_id"),
            sms_limit=doc.get("sms_limit", 0),
            sms_count=doc.get("sms_count", 0),
            balance=float(doc.get("balance", 0.0)),
            total_earned=float(doc.get("total_earned", 0.0)),
            delete_messages_after=doc.get("delete_messages_after", 0),
            telegram_bot_token=doc.get("telegram_bot_token"),
            telegram_chat_id=doc.get("telegram_chat_id"),
            telegram_enabled=bool(doc.get("telegram_enabled", False))
        )
        if not new_user.api_token:
            new_user.generate_api_token()
            
        db.session.add(new_user)
        db.session.commit()
        print(f"[FIREBASE RESTORE] Successfully restored single user '{username}' from Firestore on-demand.")
        return new_user
    except Exception as e:
        print(f"[FIREBASE RESTORE] Error restoring single client '{username}': {e}")
        return None


def is_username_in_firebase(username):
    """
    Check if a username is already taken/exists in Firebase.
    """
    try:
        client = FirebaseFirestoreRESTClient()
        if not client.project_id:
            return False
        success, doc = client.get_document("clients", username)
        return success and doc is not None
    except Exception:
        return False



