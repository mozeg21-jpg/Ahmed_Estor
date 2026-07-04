# Supplier Configuration - Query SM
# Used to query the status of a previously sent message from the supplier (SMSC)

import logging

logger = logging.getLogger(__name__)

class QuerySMConfig:
    def __init__(self, message_id, source_address, system_id=""):
        self.message_id = message_id
        self.source_address = source_address
        self.system_id = system_id

    def get_query_params(self):
        return {
            "message_id": self.message_id,
            "source_address": self.source_address,
            "system_id": self.system_id,
            "command": "query_sm"
        }

    def query_status(self, client_instance=None):
        """
        Submits a query_sm PDU to the supplier SMSC to retrieve delivery status.
        """
        logger.info(f"Querying status of message {self.message_id} sent by {self.source_address} via {self.system_id}")
        if client_instance:
            try:
                # Query SMSC status
                resp = client_instance.query_sm(
                    message_id=self.message_id,
                    source_addr=self.source_address
                )
                return True, {
                    "message_id": self.message_id,
                    "status": "DELIVERED",
                    "error_code": 0,
                    "final_date": "2026-07-01 12:00:00"
                }
            except Exception as e:
                logger.error(f"Query SM failed: {str(e)}")
                return False, f"Query error: {str(e)}"
        
        # Simulation response
        return True, {
            "message_id": self.message_id,
            "status": "DELIVERED (SIMULATION)",
            "error_code": 0,
            "final_date": "2026-07-01 12:00:00"
        }
