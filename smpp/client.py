import threading
import time
import socket
import smpplib.client
import smpplib.consts
import smpplib.exceptions
from typing import Optional

from smpp.models import ProviderConfig, SMPPMessageData
from smpp.logger import setup_logger
from smpp.handlers import handle_message
from smpp.utils import decode_message
from smpp.config import LOGS_DIR
from smpp.heartbeat import should_send_heartbeat
from smpp.reconnect import wait_for_reconnect
from smpp.receiver import bind_as_receiver_or_transceiver

logger = setup_logger(__name__, log_dir=LOGS_DIR)

class SMPPProviderClient(threading.Thread):
    """
    A threaded SMPP Client that connects to a single provider,
    binds as a receiver (or transceiver), and listens for messages.
    Handles automatic reconnection and heartbeat.
    """
    def __init__(self, config: ProviderConfig):
        super().__init__(name=f"Thread-{config.name}")
        self.config = config
        self.client: Optional[smpplib.client.Client] = None
        self._stop_event = threading.Event()
        self._connected = False
        
        # We will use this to manage our enquire_link loop
        self.last_enquire_link = time.time()

    def run(self):
        """
        Main thread execution loop. Handles connection and reconnection.
        """
        logger.info(f"[{self.config.name}] Starting SMPP Client Thread...")
        
        while not self._stop_event.is_set():
            try:
                self._connect_and_bind()
                self._listen_loop()
            except smpplib.exceptions.ConnectionError as e:
                logger.error(f"[{self.config.name}] Connection error: {e}")
            except smpplib.exceptions.PDUError as e:
                logger.error(f"[{self.config.name}] PDU parsing error: {e}")
            except socket.timeout:
                logger.warning(f"[{self.config.name}] Socket timeout. Reconnecting...")
            except Exception as e:
                logger.exception(f"[{self.config.name}] Unexpected error: {e}")
                
            self._disconnect()
            
            if not self.config.auto_reconnect:
                logger.info(f"[{self.config.name}] Auto-reconnect is disabled. Stopping thread.")
                break
                
            if not self._stop_event.is_set():
                wait_for_reconnect(self.config.name, self.config.reconnect_delay, self._stop_event, logger)

    def _connect_and_bind(self):
        """
        Connects to the SMPP server and issues a bind request.
        """
        logger.info(f"[{self.config.name}] Connecting to {self.config.host}:{self.config.port}...")
        
        self.client = smpplib.client.Client(
            self.config.host, 
            self.config.port,
            allow_unknown_opt_params=True,
            timeout=self.config.connection_timeout
        )
        
        # Set message handler
        self.client.set_message_sent_handler(self._message_sent_handler)
        self.client.set_message_received_handler(self._message_received_handler)
        
        self.client.connect()
        self.client.sock.settimeout(self.config.read_timeout)
        
        logger.info(f"[{self.config.name}] Connected. Binding as {self.config.mode}...")
        
        bind_as_receiver_or_transceiver(self.client, self.config)
            
        self._connected = True
        self.last_enquire_link = time.time()
        logger.info(f"[{self.config.name}] Bind successful!")

    def _listen_loop(self):
        """
        Continuously listens for incoming PDUs and sends heartbeats.
        """
        while not self._stop_event.is_set() and self._connected:
            # We use a short timeout on the socket read to allow us to check
            # for heartbeat requirements and the stop event.
            self.client.sock.settimeout(1.0)
            
            try:
                self.client.listen(ignore_error_codes=True)
            except socket.timeout:
                # Expected when no data arrives within 1 second
                pass
                
            self._check_heartbeat()

    def _check_heartbeat(self):
        """
        Sends an enquire_link (heartbeat) if the interval has passed.
        """
        if should_send_heartbeat(self.last_enquire_link, self.config.heartbeat_interval):
            logger.debug(f"[{self.config.name}] Sending Heartbeat (Enquire Link)...")
            try:
                self.client.enquire_link()
                self.last_enquire_link = time.time()
            except Exception as e:
                logger.error(f"[{self.config.name}] Heartbeat failed: {e}")
                raise smpplib.exceptions.ConnectionError("Heartbeat failed")

    def _disconnect(self):
        """
        Safely unbinds and disconnects the client.
        """
        self._connected = False
        if self.client:
            try:
                logger.info(f"[{self.config.name}] Unbinding and disconnecting...")
                self.client.unbind()
                self.client.disconnect()
            except Exception:
                pass
            finally:
                self.client = None

    def stop(self):
        """
        Signals the thread to stop.
        """
        logger.info(f"[{self.config.name}] Stopping client...")
        self._stop_event.set()
        self._disconnect()

    def _message_received_handler(self, pdu):
        """
        Callback fired by smpplib when a Deliver_SM PDU is received.
        """
        command_id = getattr(pdu, 'command_id', None)
        
        if command_id == smpplib.consts.SMPP_ENQUIRE_LINK_RESP:
            logger.debug(f"[{self.config.name}] Heartbeat Acknowledged.")
            return

        if command_id == smpplib.consts.SMPP_DELIVER_SM:
            sender = getattr(pdu, 'source_addr', b'').decode('ascii', errors='ignore')
            receiver = getattr(pdu, 'destination_addr', b'').decode('ascii', errors='ignore')
            data_coding = getattr(pdu, 'data_coding', 0)
            short_message = getattr(pdu, 'short_message', b'')
            
            # Decode the message text
            message_text = decode_message(short_message, data_coding)
            
            # Build data model
            msg_data = SMPPMessageData(
                provider_name=self.config.name,
                sender_number=sender,
                receiver_number=receiver,
                message_text=message_text,
                ton=getattr(pdu, 'source_addr_ton', None),
                npi=getattr(pdu, 'source_addr_npi', None),
                data_coding=data_coding,
                sequence_number=getattr(pdu, 'sequence_number', None)
            )
            
            # Pass to centralized handler
            handle_message(msg_data)
            
    def _message_sent_handler(self, pdu):
        """
        Callback fired by smpplib when a Submit_SM_Resp is received.
        Used mostly in transceiver mode when sending SMS.
        """
        pass
