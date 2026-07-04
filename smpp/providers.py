import os
from typing import List
from smpp.models import ProviderConfig
from smpp.config import PROVIDERS_FILE
from smpp.yaml_helper import parse_yaml_file
import logging

logger = logging.getLogger(__name__)

def load_providers(yaml_path: str = PROVIDERS_FILE) -> List[ProviderConfig]:
    """
    Load providers from the YAML configuration file using pure-Python helper.
    """
    providers: List[ProviderConfig] = []
    
    if not os.path.exists(yaml_path):
        logger.error(f"Configuration file not found: {yaml_path}")
        return providers

    try:
        data = parse_yaml_file(yaml_path)
            
        if not data or 'providers' not in data:
            logger.warning("No providers found in configuration file.")
            return providers
            
        for p_data in data['providers']:
            try:
                # Create a ProviderConfig instance from the dictionary
                provider = ProviderConfig(**p_data)
                providers.append(provider)
            except TypeError as e:
                logger.error(f"Error parsing provider {p_data.get('name', 'Unknown')}: {e}")
                
    except Exception as e:
        logger.exception(f"Failed to load configuration file {yaml_path}: {e}")

    return providers

def get_enabled_providers(yaml_path: str = PROVIDERS_FILE) -> List[ProviderConfig]:
    """
    Get only the enabled providers from the YAML configuration file.
    """
    all_providers = load_providers(yaml_path)
    enabled = [p for p in all_providers if p.enabled]
    logger.info(f"Loaded {len(enabled)} enabled providers out of {len(all_providers)} total.")
    return enabled
