import os

# Base directory for the SMPP module
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Path to the providers YAML file
PROVIDERS_FILE = os.path.join(BASE_DIR, "providers.yaml")

# Path to the logs directory
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# Webhook URL for forwarding messages (if needed)
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "http://127.0.0.1:5000/api/sms/receive")
