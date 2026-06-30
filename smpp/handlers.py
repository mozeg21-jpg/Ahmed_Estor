from smpp.models import SMPPMessageData
from smpp.logger import setup_logger
from smpp.config import LOGS_DIR

logger = setup_logger(__name__, log_dir=LOGS_DIR)

def handle_message(message_data: SMPPMessageData):
    """
    Unified handler for all incoming SMPP messages.
    
    This function acts as a single entry point for processing messages.
    It can be easily extended to:
    - Save to Database (SQLAlchemy, Django ORM, etc.)
    - Send via Webhook (requests)
    - Push to WebSocket / Queue (Celery, Redis, RabbitMQ)
    
    Args:
        message_data: SMPPMessageData object containing parsed message details.
    """
    logger.info(
        f"[{message_data.provider_name}] New Message | "
        f"From: {message_data.sender_number} | "
        f"To: {message_data.receiver_number} | "
        f"Text: {message_data.message_text}"
    )

    # Example: Forwarding to internal API (Webhook)
    # import requests
    # payload = {
    #     "provider": message_data.provider_name,
    #     "from": message_data.sender_number,
    #     "to": message_data.receiver_number,
    #     "message": message_data.message_text,
    #     "receive_time": message_data.receive_time.isoformat()
    # }
    # try:
    #     requests.post("http://127.0.0.1:5000/api/sms/receive", json=payload, timeout=5)
    # except Exception as e:
    #     logger.error(f"Failed to forward message via webhook: {e}")
    
    # Example: Saving to Database
    # from smpp.database import save_message
    # save_message(message_data)
