"""Services for the ONU Stick integration."""
from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime
from typing import Any

import paramiko

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from .const import CONF_HOST, CONF_KEY_PATH, CONF_USER, CONF_PUBLIC_KEY, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up the services."""
    
    async def reboot_onu_stick(call: ServiceCall) -> None:
        """Reboot the ONU stick."""
        # Get the first ONU stick entry
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            raise ServiceValidationError("No ONU stick integration found")
        
        entry = entries[0]  # Use the first entry
        config = entry.data
        
        _LOGGER.info("Rebooting ONU stick at %s", config[CONF_HOST])
        
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            connect_kwargs = {
                "hostname": config[CONF_HOST],
                "username": config[CONF_USER],
                "timeout": 10,
                "key_filename": config[CONF_KEY_PATH],
            }
            
            def connect_and_reboot():
                client.connect(**connect_kwargs)
                client.exec_command("reboot")
            
            await hass.async_add_executor_job(connect_and_reboot)
            client.close()
            _LOGGER.info("Reboot command sent successfully to ONU stick")
            
        except Exception as err:
            _LOGGER.error("Failed to reboot ONU stick: %s", err)
            raise ServiceValidationError(f"Failed to reboot: {err}")
    
    async def regenerate_ssh_key(call: ServiceCall) -> None:
        """Regenerate SSH key with simple backup of current key."""
        # Get the first ONU stick entry
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            raise ServiceValidationError("No ONU stick integration found")
        
        entry = entries[0]  # Use the first entry
        config = entry.data
        current_key_path = config[CONF_KEY_PATH]
        
        _LOGGER.info("Regenerating SSH key for ONU stick at %s", config[CONF_HOST])
        
        try:
            # Backup current key if it exists
            backup_path = None
            if os.path.exists(current_key_path):
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = f"{current_key_path}.backup_{timestamp}"
                
                def backup_key():
                    shutil.copy2(current_key_path, backup_path)
                
                await hass.async_add_executor_job(backup_key)
                _LOGGER.info("Backed up current key to: %s", backup_path)
            
            # Generate new key
            def generate_key_pair():
                rsa_key = paramiko.RSAKey.generate(2048)
                public_key = f"{rsa_key.get_name()} {rsa_key.get_base64()}"
                return rsa_key, public_key
            
            rsa_key, public_key = await hass.async_add_executor_job(generate_key_pair)
            
            # Ensure directory exists
            key_dir = os.path.dirname(current_key_path)
            if key_dir:
                await hass.async_add_executor_job(lambda: os.makedirs(key_dir, exist_ok=True))
            
            # Write the private key
            def write_key():
                rsa_key.write_private_key_file(current_key_path)
                os.chmod(current_key_path, 0o600)
            
            await hass.async_add_executor_job(write_key)
            
            # Update the config entry with new public key
            new_data = dict(config)
            new_data[CONF_PUBLIC_KEY] = public_key
            
            hass.config_entries.async_update_entry(entry, data=new_data)
            
            _LOGGER.info("SSH key regenerated successfully")
            _LOGGER.info("New public key: %s", public_key)
            
            # Log success message with backup info
            if backup_path:
                _LOGGER.info("SSH key regenerated successfully. Previous key backed up to: %s", backup_path)
            else:
                _LOGGER.info("SSH key regenerated successfully. No previous key found to backup.")
            
        except Exception as err:
            _LOGGER.error("Failed to regenerate SSH key: %s", err)
            raise ServiceValidationError(f"Failed to regenerate key: {err}")
    
    # Register services
    hass.services.async_register(
        DOMAIN,
        "reboot_onu_stick",
        reboot_onu_stick,
    )
    
    hass.services.async_register(
        DOMAIN,
        "regenerate_ssh_key",
        regenerate_ssh_key,
    ) 