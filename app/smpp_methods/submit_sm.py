# Supplier Information - Send Message (Submit SM)
# This file is used to store or execute message sending settings for suppliers.

class SubmitSMConfig:
    def __init__(self, system_id, destination_address, source_address, text):
        self.system_id = system_id
        self.destination_address = destination_address
        self.source_address = source_address
        self.text = text

    def send_message(self):
        # Here the message sending code to the supplier is executed
        pass
