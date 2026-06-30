import time
import signal
import sys
from typing import List

from smpp.providers import get_enabled_providers
from smpp.client import SMPPProviderClient
from smpp.logger import setup_logger
from smpp.config import LOGS_DIR

logger = setup_logger("smpp.main", log_dir=LOGS_DIR)

class SMPPServiceManager:
    """
    Manages the lifecycle of multiple SMPP client threads.
    """
    def __init__(self):
        self.clients: List[SMPPProviderClient] = []
        self._running = False

    def start(self):
        """
        Reads configuration, initializes provider threads, and starts them.
        """
        providers = get_enabled_providers()
        
        if not providers:
            logger.warning("No enabled providers found. Service will exit.")
            return

        logger.info(f"Starting SMPP Service with {len(providers)} providers...")
        
        for p_config in providers:
            client_thread = SMPPProviderClient(config=p_config)
            self.clients.append(client_thread)
            client_thread.start()
            
        self._running = True
        
        # Setup graceful shutdown handlers
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        
        self._keep_alive()

    def _keep_alive(self):
        """
        Keeps the main thread alive while worker threads run.
        """
        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            self._handle_shutdown(None, None)

    def _handle_shutdown(self, signum, frame):
        """
        Gracefully stops all client threads on exit signal.
        """
        if not self._running:
            return
            
        logger.info("\nShutdown signal received. Stopping all SMPP providers gracefully...")
        self._running = False
        
        for client in self.clients:
            client.stop()
            
        for client in self.clients:
            client.join(timeout=5)
            
        logger.info("All SMPP providers stopped. Exiting.")
        sys.exit(0)

def run():
    manager = SMPPServiceManager()
    manager.start()

if __name__ == "__main__":
    run()
