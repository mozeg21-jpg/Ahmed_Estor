# Supplier Configuration - Unbind
# Used to terminate the session gracefully and securely with the supplier

import logging

logger = logging.getLogger(__name__)

class SupplierUnbindConfig:
    def __init__(self, system_id, reason="Session terminated"):
        self.system_id = system_id
        self.reason = reason

    def get_unbind_params(self):
        return {
            "system_id": self.system_id,
            "reason": self.reason,
            "command": "unbind"
        }

    def terminate_session(self, client_instance=None):
        """
        Gracefully sends an unbind PDU to the supplier and closes the socket.
        """
        logger.info(f"Initiating unbind for {self.system_id}. Reason: {self.reason}")
        if client_instance:
            try:
                client_instance.unbind()
                client_instance.disconnect()
                return True, "Successfully unbound and disconnected from SMPP provider"
            except Exception as e:
                logger.error(f"Failed to unbind gracefully: {str(e)}")
                return False, f"Unbind error: {str(e)}"
        return True, "Session closed simulation successful"
