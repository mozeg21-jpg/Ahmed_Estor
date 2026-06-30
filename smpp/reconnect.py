import time
import logging

def wait_for_reconnect(provider_name: str, delay: int, stop_event, logger: logging.Logger):
    """
    Handles the waiting period before reconnecting, and checks for stop signals.
    
    Args:
        provider_name: The name of the provider.
        delay: Time to wait in seconds.
        stop_event: Threading event to check for early exit.
        logger: Logger instance to use.
    """
    logger.info(f"[{provider_name}] Waiting {delay} seconds before reconnecting...")
    # Sleep in small chunks to remain responsive to stop signals
    for _ in range(delay * 10):
        if stop_event.is_set():
            logger.info(f"[{provider_name}] Reconnect aborted due to stop signal.")
            break
        time.sleep(0.1)
