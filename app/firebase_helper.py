import os
import requests
import json
from datetime import datetime

class FirebaseFirestoreRESTClient:
    """
    A lightweight, pure-Python REST client for Firebase Firestore.
    Bypasses python pip install restrictions by using standard requests.
    """
    def __init__(self, project_id=None, api_key=None, database_id=None):
        self.project_id = project_id or os.environ.get("FIREBASE_PROJECT_ID")
        self.api_key = api_key or os.environ.get("FIREBASE_API_KEY")
        self.database_id = database_id or os.environ.get("FIREBASE_DATABASE_ID")
        
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
        except Exception:
            pass

        if not self.database_id:
            self.database_id = "(default)"
        
        # Try loading dynamically from DREEM SMS's News-based key-value store if running within Flask context
        try:
            from app.models.activity import News
            proj_setting = News.query.filter_by(title='firebase_project_id').first()
            key_setting = News.query.filter_by(title='firebase_api_key').first()
            db_setting = News.query.filter_by(title='firebase_database_id').first()
            
            if proj_setting and proj_setting.content:
                self.project_id = proj_setting.content
            if key_setting and key_setting.content:
                self.api_key = key_setting.content
            if db_setting and db_setting.content:
                self.database_id = db_setting.content
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
        """Lists all documents inside a collection"""
        if not self.base_url:
            raise ValueError("Firebase Project ID not configured.")
        
        url = f"{self.base_url}/{collection_path}"
        params = {}
        if self.api_key:
            params["key"] = self.api_key
            
        res = requests.get(url, params=params, timeout=8)
        if res.status_code == 200:
            docs = res.json().get("documents", [])
            return True, [self._from_firestore_document(d) for d in docs]
        else:
            try:
                err_msg = res.json().get("error", {}).get("message", res.text)
            except Exception:
                err_msg = res.text
            return False, err_msg

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

# Ready-to-use helpers for Client / Client Data syncing as requested by user

def sync_client_to_firebase(client_user_object):
    """
    Helper function to sync/save a DREEM SMS local User client model to Firestore.
    """
    try:
        client = FirebaseFirestoreRESTClient()
        if not client.project_id:
            return False, "Firebase not configured."
        
        data = {
            "username": client_user_object.username,
            "name": client_user_object.name or "",
            "email": client_user_object.email or "",
            "is_active": client_user_object.is_active,
            "balance": float(client_user_object.balance or 0.0),
            "credit_limit": float(client_user_object.credit_limit or 0.0),
            "phone": client_user_object.phone or "",
            "role": client_user_object.role.name if client_user_object.role else "client",
            "last_login": client_user_object.last_login.isoformat() if client_user_object.last_login else None,
            "created_at": client_user_object.created_at.isoformat() if client_user_object.created_at else datetime.utcnow().isoformat()
        }
        
        success, res = client.save_document("clients", client_user_object.username, data)
        return success, res
    except Exception as e:
        return False, str(e)


def sync_cdr_to_firebase(cdr_object):
    """
    Helper function to sync/save a DREEM SMS local SMSCDR model to Firestore.
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
            "created_at": cdr_object.created_at.isoformat() if cdr_object.created_at else datetime.utcnow().isoformat()
        }
        
        doc_id = cdr_object.caller_id or f"cdr_{cdr_object.id or int(datetime.utcnow().timestamp())}"
        success, res = client.save_document("sms_cdr", doc_id, data)
        return success, res
    except Exception as e:
        return False, str(e)

