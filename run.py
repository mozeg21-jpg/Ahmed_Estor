#!/usr/bin/env python3
"""
DREEM SMS - run script
"""
import os

# Capture the original system environment ports BEFORE loading any .env file
sys_server_port = os.environ.get('SERVER_PORT')
sys_port = os.environ.get('PORT')

from dotenv import load_dotenv
load_dotenv()  # Load .env file if it exists

from app import create_app, db
from app.models.user import User, Role
from app.models.sms import SMDRange, SMSNumber, SMSCDR
from app.models.activity import ActivityLog

config_name = os.environ.get('FLASK_ENV', 'production')
app = create_app(config_name)

if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    host  = os.environ.get('HOST', '0.0.0.0')   # bind all interfaces
    
    # 1. If DEFAULT_APP_PORT is defined (AI Studio environment), use it.
    # 2. If sys_server_port (Wispbyte/Pterodactyl environment) is defined, use it.
    # 3. If sys_port is defined, use it.
    # 4. Fallback to loaded .env variables or 3000.
    if os.environ.get('DEFAULT_APP_PORT'):
        port = int(os.environ.get('DEFAULT_APP_PORT'))
    elif sys_server_port:
        port = int(sys_server_port)
    elif sys_port:
        port = int(sys_port)
    elif os.environ.get('SERVER_PORT'):
        port = int(os.environ.get('SERVER_PORT'))
    else:
        port = int(os.environ.get('PORT', '3000'))

    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

    logger.info(f"Starting DREEM SMS on {host}:{port} (debug={debug})")
    app.run(host=host, port=port, debug=debug)
