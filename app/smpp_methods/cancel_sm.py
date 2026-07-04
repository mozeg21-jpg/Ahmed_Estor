# Supplier Configuration - Cancel SM
# Used to attempt to cancel a previously sent message before delivery at the SMSC

import logging

logger = logging.getLogger(__name__)

class CancelSMConfig:
    def __init__(self, message_id, source_address, destination_address, system_id=""):
        self.message_id = message_id
        self.source_address = source_address
        self.destination_address = destination_address
        self.system_id = system_id

    def get_cancel_params(self):
        return {
            "message_id": self.message_id,
            "source_address": self.source_address,
            "destination_address": self.destination_address,
            "system_id": self.system_id,
            "command": "cancel_sm"
        }

    def cancel_message(self, client_instance=None):
        """
        Submits a cancel_sm PDU to the supplier SMSC to cancel delivery.
        """
        logger.info(f"Cancelling message {self.message_id} to {self.destination_address} via {self.system_id}")
        if client_instance:
            try:
                # Cancel SMSC message
                client_instance.cancel_sm(
                    message_id=self.message_id,
                    source_addr=self.source_address,
                    destination_addr=self.destination_address
                )
                return True, "Successfully sent cancellation request to supplier"
            except Exception as e:
                logger.error(f"Cancel SM failed: {str(e)}")
                return False, f"Cancellation error: {str(e)}"
        
        # Simulation response
        return True, "Message cancellation request sent (SIMULATION)"
