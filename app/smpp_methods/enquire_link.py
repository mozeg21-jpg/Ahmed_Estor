# Supplier Information - Connection Check (Enquire Link)
# This file is used to check the active connection with the supplier to keep the session alive.

class EnquireLinkConfig:
    def __init__(self, system_id):
        self.system_id = system_id

    def check_connection(self):
        # Here, the Enquire Link request is sent to the supplier and verification of the response (Enquire Link Resp) is done.
        pass
