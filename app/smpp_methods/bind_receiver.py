# Supplier Configuration - Bind Receiver
# Used to log in to the supplier for reception only

class SupplierReceiverConfig:
    def __init__(self, system_id, password, host, port, system_type=""):
        self.bind_type = "receiver"
        self.system_id = system_id       # Username (Login)
        self.password = password         # Password
        self.host = host                 # IP Address or Domain
        self.port = port                 # Connection Port (Port)
        self.system_type = system_type

    def get_bind_params(self):
        return {
            "system_id": self.system_id,
            "password": self.password,
            "host": self.host,
            "port": self.port,
            "system_type": self.system_type,
            "bind_type": self.bind_type
        }
