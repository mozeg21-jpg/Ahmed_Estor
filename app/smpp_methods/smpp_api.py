# Supplier Configuration - SMPP over HTTP API
# This file handles routing SMPP messages through HTTP REST APIs as an alternative to direct TCP/SMPP sockets.
# Excellent for bypass firewalls or integrating with modern HTTP SMS/SMPP Gateways.

import logging
import requests

logger = logging.getLogger(__name__)

class SMPPOverAPIConfig:
    def __init__(self, name, gateway_url, api_key, username=None, system_type="HTTP_GATEWAY"):
        self.name = name
        self.gateway_url = gateway_url       # Endpoint URL: e.g. http://jasmin-gateway:1401/send
        self.api_key = api_key               # Secret API Key / token
        self.username = username             # System login username if needed
        self.system_type = system_type       # Jasmin, Twilio, Generic, etc.

    def get_api_params(self):
        return {
            "name": self.name,
            "gateway_url": self.gateway_url,
            "username": self.username,
            "system_type": self.system_type
        }

    def send_via_api(self, from_number, to_number, text):
        """
        Submits the SMS request to the HTTP API Gateway which relays it via SMPP.
        Supports Jasmin SMS gateway syntax, Twilio-like syntax, and generic payloads.
        """
        logger.info(f"[{self.name}] Relay via {self.system_type} API: sending message to {to_number}")
        
        # Determine payload based on gateway system type
        if self.system_type.upper() == "JASMIN":
            # Jasmin SMS HTTP API specification
            payload = {
                "to": to_number,
                "from": from_number,
                "content": text,
                "username": self.username,
                "password": self.api_key
            }
            headers = {"Content-Type": "application/json"}
            try:
                r = requests.post(self.gateway_url, json=payload, headers=headers, timeout=10)
                if r.status_code in (200, 201):
                    return True, f"Jasmin API Success: {r.text.strip()}"
                else:
                    return False, f"Jasmin API Error {r.status_code}: {r.text.strip()}"
            except Exception as e:
                return False, f"HTTP Connection Exception: {str(e)}"

        elif self.system_type.upper() == "TWILIO":
            # Twilio-like REST format
            payload = {
                "To": to_number,
                "From": from_number,
                "Body": text
            }
            auth = (self.username, self.api_key) if self.username else None
            try:
                r = requests.post(self.gateway_url, data=payload, auth=auth, timeout=10)
                if r.status_code in (200, 201):
                    return True, "Twilio API Success"
                else:
                    return False, f"Twilio API Error {r.status_code}: {r.text.strip()}"
            except Exception as e:
                return False, f"HTTP Connection Exception: {str(e)}"

        else:
            # Generic REST SMPP/SMS Gateways
            payload = {
                "destination": to_number,
                "source": from_number,
                "message": text,
                "user": self.username,
                "token": self.api_key
            }
            try:
                r = requests.post(self.gateway_url, json=payload, timeout=10)
                if r.status_code in (200, 201):
                    return True, f"Generic API Success: {r.text.strip()}"
                else:
                    return False, f"Generic API Response Code {r.status_code}"
            except Exception as e:
                return False, f"HTTP Connection Exception: {str(e)}"
