import binascii

def decode_message(short_message: bytes, data_coding: int) -> str:
    """
    Decodes the raw bytes of an SMPP message into a string based on data_coding.
    
    Args:
        short_message: The raw bytes of the message.
        data_coding: The data_coding parameter from the Deliver_SM PDU.
        
    Returns:
        str: The decoded message text.
    """
    if not short_message:
        return ""
        
    try:
        if data_coding == 0:
            # Default Alphabet (usually GSM 7-bit, but often transmitted as ASCII/Latin-1)
            return short_message.decode('latin-1', errors='replace')
        elif data_coding == 3:
            # Latin-1
            return short_message.decode('latin-1', errors='replace')
        elif data_coding == 8:
            # UCS2 (UTF-16-BE)
            return short_message.decode('utf-16-be', errors='replace')
        else:
            # Fallback
            return short_message.decode('latin-1', errors='replace')
    except Exception:
        # Absolute fallback if decoding fails
        return repr(short_message)
