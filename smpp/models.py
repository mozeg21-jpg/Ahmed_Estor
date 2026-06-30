from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

@dataclass
class ProviderConfig:
    """
    Data model representing a single SMPP provider's configuration.
    """
    name: str
    host: str
    port: int
    system_id: str
    password: str
    system_type: str = "SMPP"
    mode: str = "receiver"
    interface_version: int = 34
    ton: int = 0
    npi: int = 0
    address_range: str = ""
    heartbeat_interval: int = 30
    auto_reconnect: bool = True
    reconnect_delay: int = 5
    connection_timeout: int = 10
    read_timeout: int = 60
    enabled: bool = False

@dataclass
class SMPPMessageData:
    """
    Data model representing an incoming SMPP Message (Deliver_SM).
    """
    provider_name: str
    sender_number: str
    receiver_number: str
    message_text: str
    message_id: Optional[str] = None
    ton: Optional[int] = None
    npi: Optional[int] = None
    data_coding: Optional[int] = None
    sequence_number: Optional[int] = None
    service_type: Optional[str] = None
    receive_time: datetime = field(default_factory=datetime.utcnow)
    raw_pdu: Optional[bytes] = None
