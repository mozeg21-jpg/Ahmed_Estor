import smpplib.client
from smpp.models import ProviderConfig

def bind_as_receiver_or_transceiver(client: smpplib.client.Client, config: ProviderConfig):
    """
    Binds the SMPP client to the server based on the configuration.
    
    Args:
        client: The instantiated smpplib.client.Client.
        config: The provider configuration containing binding details.
    """
    if config.mode.lower() == "transceiver":
        client.bind_transceiver(
            system_id=config.system_id,
            password=config.password,
            system_type=config.system_type,
            interface_version=config.interface_version,
            addr_ton=config.ton,
            addr_npi=config.npi,
            address_range=config.address_range
        )
    else:
        client.bind_receiver(
            system_id=config.system_id,
            password=config.password,
            system_type=config.system_type,
            interface_version=config.interface_version,
            addr_ton=config.ton,
            addr_npi=config.npi,
            address_range=config.address_range
        )
