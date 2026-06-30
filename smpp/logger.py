import logging
import os
from logging.handlers import RotatingFileHandler

def setup_logger(name: str, log_dir: str = "logs", level=logging.INFO) -> logging.Logger:
    """
    Sets up a professional logger that writes to both console and a rotating file.
    
    Args:
        name: Name of the logger (usually __name__).
        log_dir: Directory where logs will be saved.
        level: Logging level.
        
    Returns:
        logging.Logger: The configured logger.
    """
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Prevent adding multiple handlers if logger is already configured
    if not logger.handlers:
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        # Console Handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # File Handler (Rotate after 5MB, keep 5 backups)
        log_file = os.path.join(log_dir, "smpp_service.log")
        file_handler = RotatingFileHandler(
            log_file, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
