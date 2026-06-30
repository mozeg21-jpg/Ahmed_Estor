#!/usr/bin/env python3
"""
ABYSS SMS - run script
"""
import os
from app import create_app, db
from app.models.user import User, Role
from app.models.sms import SMDRange, SMSNumber, SMSCDR
from app.models.activity import ActivityLog

config_name = os.environ.get('FLASK_ENV', 'production')
app = create_app(config_name)

if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    host  = os.environ.get('HOST', '0.0.0.0')   # bind all interfaces
    port  = int(os.environ.get('PORT', '3000'))

    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

    logger.info(f"Starting ABYSS SMS on {host}:{port} (debug={debug})")
    app.run(host=host, port=port, debug=debug)
