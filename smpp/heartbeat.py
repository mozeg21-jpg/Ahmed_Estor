import time
import logging

def should_send_heartbeat(last_enquire_link: float, heartbeat_interval: int) -> bool:
    """
    Checks if the heartbeat interval has elapsed.
    
    Args:
        last_enquire_link: Timestamp of the last enquire link sent.
        heartbeat_interval: Required interval in seconds.
        
    Returns:
        bool: True if a heartbeat should be sent.
    """
    now = time.time()
    return (now - last_enquire_link) >= heartbeat_interval
