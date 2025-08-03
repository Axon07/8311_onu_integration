import logging
import os
from typing import Any

import paramiko
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_KEY_PATH,
    CONF_PUBLIC_KEY,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("onu_host"): str,
        vol.Required("onu_user"): str,
        vol.Required("device_manufacturer", default="Unknown"): str,
        vol.Required("device_name", default="XGSPON ONU Stick"): str,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=30, max=3600)
        ),
    }
)

STEP_ADD_KEY_SCHEMA = vol.Schema(
    {
        vol.Required("confirm_key_added"): bool,
    }
)


async def check_ssh_availability(hass: HomeAssistant, host: str) -> bool:
    """Check if SSH is available on the ONU without authentication."""
    _LOGGER.debug("Checking SSH availability on %s", host)
    
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        def connect_ssh():
            _LOGGER.debug("Attempting SSH connection to check availability...")
            # Try to connect without authentication to see if SSH is available
            client.connect(
                hostname=host,
                port=22,
                timeout=10,
                look_for_keys=False,
                allow_agent=False,
            )
            _LOGGER.debug("SSH is available on %s", host)
        
        await hass.async_add_executor_job(connect_ssh)
        client.close()
        return True
    except (paramiko.AuthenticationException, paramiko.SSHException) as exc:
        # AuthenticationException means SSH is available but auth failed (expected)
        # SSHException might also indicate SSH is available
        _LOGGER.debug("SSH is available but authentication failed (expected): %s", exc)
        return True
    except (TimeoutError, ConnectionRefusedError, OSError) as exc:
        _LOGGER.error("SSH is not available on %s: %s", host, exc)
        return False
    except Exception as exc:
        _LOGGER.error("Unexpected error checking SSH availability: %s", exc)
        return False


async def generate_ssh_key(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Generate SSH key pair and return the public key."""
    _LOGGER.debug("Generating SSH key pair for %s", data["onu_host"])
    
    # Generate or get existing SSH key
    storage_dir = hass.config.path(".storage")
    key_filename = f"xgpon_onu_{hass.config.location_name.lower().replace(' ', '_')}.key"
    private_key_path = os.path.join(storage_dir, key_filename)
    
    # Check if key already exists
    if not os.path.exists(private_key_path):
        _LOGGER.info("Generating new SSH key pair")
        try:
            # Generate key pair using paramiko RSAKey
            def generate_key_pair():
                _LOGGER.debug("Starting key generation with paramiko RSAKey...")
                # Generate RSA key using paramiko
                rsa_key = paramiko.RSAKey.generate(2048)
                _LOGGER.debug("Generated RSA key with size: 2048")
                
                # Get public key in OpenSSH format
                public_key = f"{rsa_key.get_name()} {rsa_key.get_base64()}"
                _LOGGER.debug("Generated public key (first 50 chars): %s", public_key[:50])
                
                return rsa_key, public_key
            
            rsa_key, public_key = await hass.async_add_executor_job(generate_key_pair)
            _LOGGER.debug("Key generation completed, public key length: %s", len(public_key))
            
            # Ensure storage directory exists
            def ensure_dir_exists():
                os.makedirs(storage_dir, exist_ok=True)
            
            await hass.async_add_executor_job(ensure_dir_exists)
            
            # Write the private key using paramiko's format
            def write_key():
                rsa_key.write_private_key_file(private_key_path)
                _LOGGER.debug("Wrote private key to: %s", private_key_path)
            
            await hass.async_add_executor_job(write_key)
            
            # Ensure proper file permissions
            await hass.async_add_executor_job(
                lambda: os.chmod(private_key_path, 0o600)
            )
            
            _LOGGER.info("Generated SSH key pair and stored at: %s", private_key_path)
            data[CONF_PUBLIC_KEY] = public_key
            data[CONF_KEY_PATH] = private_key_path
            
        except Exception as e:
            _LOGGER.error("Failed to generate SSH key: %s", e)
            raise CannotConnect("key_generation_failed") from e
    else:
        _LOGGER.info("Using existing SSH key at: %s", private_key_path)
        data[CONF_KEY_PATH] = private_key_path
        
        # Try to derive public key from existing private key using paramiko
        try:
            def read_private_key():
                rsa_key = paramiko.RSAKey.from_private_key_file(private_key_path)
                return rsa_key
            
            rsa_key = await hass.async_add_executor_job(read_private_key)
            public_key = f"{rsa_key.get_name()} {rsa_key.get_base64()}"
            data[CONF_PUBLIC_KEY] = public_key
        except (OSError, ValueError) as e:
            _LOGGER.warning("Could not derive public key from existing private key: %s", e)
            data[CONF_PUBLIC_KEY] = "Could not be derived from existing key."
    
    return data


async def test_ssh_connection(hass: HomeAssistant, data: dict[str, Any]) -> bool:
    """Test SSH connection with the generated key."""
    _LOGGER.debug("Testing SSH connection to %s with user %s", data["onu_host"], data["onu_user"])
    
    connect_kwargs = {
        "hostname": data["onu_host"],
        "username": data["onu_user"],
        "timeout": 10,
        "key_filename": data[CONF_KEY_PATH],
    }
    
    _LOGGER.debug("SSH connection kwargs: %s", connect_kwargs)
    _LOGGER.debug("Key file path: %s", data[CONF_KEY_PATH])
    _LOGGER.debug("Key file exists: %s", os.path.exists(data[CONF_KEY_PATH]))

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        def connect_ssh():
            _LOGGER.debug("Attempting SSH connection...")
            client.connect(**connect_kwargs)
            _LOGGER.debug("SSH connection established successfully")
        
        await hass.async_add_executor_job(connect_ssh)
        client.close()
        _LOGGER.debug("SSH connection successful")
        return True
    except FileNotFoundError as exc:
        _LOGGER.error("SSH key file not found at path: %s", data[CONF_KEY_PATH])
        raise CannotConnect("key_not_found") from exc
    except paramiko.AuthenticationException as exc:
        _LOGGER.error("SSH authentication failed: %s", exc)
        raise CannotConnect("invalid_auth") from exc
    except (paramiko.SSHException, TimeoutError) as exc:
        _LOGGER.error("SSH connection failed: %s", exc)
        _LOGGER.error("SSH exception type: %s", type(exc).__name__)
        _LOGGER.error("SSH exception args: %s", exc.args)
        raise CannotConnect("cannot_connect") from exc
    except Exception as exc:
        _LOGGER.error("Unexpected SSH error: %s", exc)
        _LOGGER.error("Exception type: %s", type(exc).__name__)
        _LOGGER.error("Exception args: %s", exc.args)
        raise CannotConnect("cannot_connect") from exc


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for XGSPON ONU Stick."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        super().__init__()
        self._data = {}

    async def async_step_user(
            self, user_input: dict[str, Any] | None = None
    ):
        """Handle the initial step."""
        if user_input is not None:
            # Store user input
            self._data.update(user_input)
            
            # Check if SSH is available
            if not await check_ssh_availability(self.hass, user_input["onu_host"]):
                return self.async_show_form(
                    step_id="user", 
                    data_schema=STEP_USER_DATA_SCHEMA, 
                    errors={"base": "ssh_not_available"}
                )
            
            # Generate SSH key using original method
            try:
                await generate_ssh_key(self.hass, self._data)
            except CannotConnect as e:
                return self.async_show_form(
                    step_id="user", 
                    data_schema=STEP_USER_DATA_SCHEMA, 
                    errors={"base": str(e)}
                )
            except Exception:
                _LOGGER.exception("Unexpected exception")
                return self.async_show_form(
                    step_id="user", 
                    data_schema=STEP_USER_DATA_SCHEMA, 
                    errors={"base": "unknown"}
                )
            
            # Move to the key addition step
            return await self.async_step_add_key()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA
        )

    async def async_step_add_key(
            self, user_input: dict[str, Any] | None = None
    ):
        """If no SSH key exists, generate one, show it to the user and confirm addition with a checkbox."""
        if user_input is not None and user_input.get("confirm_key_added"):
            # Test the SSH connection
            try:
                if await test_ssh_connection(self.hass, self._data):
                    # Success! Create the config entry
                    await self.async_set_unique_id(self._data["onu_host"])
                    self._abort_if_unique_id_configured()
                    
                    # Separate data from options
                    data = {k: v for k, v in self._data.items() if k != CONF_SCAN_INTERVAL}
                    options = {CONF_SCAN_INTERVAL: self._data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)}
                    
                    return self.async_create_entry(
                        title=self._data["device_name"], 
                        data=data,
                        options=options
                    )
            except CannotConnect as e:
                return self.async_show_form(
                    step_id="add_key", 
                    data_schema=STEP_ADD_KEY_SCHEMA, 
                    errors={"base": str(e)}
                )
            except Exception:
                _LOGGER.exception("Unexpected exception")
                return self.async_show_form(
                    step_id="add_key", 
                    data_schema=STEP_ADD_KEY_SCHEMA, 
                    errors={"base": "unknown"}
                )

        # Show the form with instructions
        return self.async_show_form(
            step_id="add_key",
            data_schema=STEP_ADD_KEY_SCHEMA,
            description_placeholders={
                "onu_host": self._data["onu_host"],
                "public_key": self._data[CONF_PUBLIC_KEY],
            }
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        """Handle the reconfigure step."""
        errors: dict[str, str] = {}

        # Define the schema for reconfiguration (exclude optional scan_interval)
        RECONFIGURE_SCHEMA = vol.Schema(
            {
                vol.Required(
                    "onu_host",
                    default=self._get_reconfigure_entry().data.get("onu_host"),
                ): str,
                vol.Required(
                    "onu_user",
                    default=self._get_reconfigure_entry().data.get("onu_user"),
                ): str,
                vol.Required(
                    "device_manufacturer",
                    default=self._get_reconfigure_entry().data.get(
                        "device_manufacturer", "Unknown"
                    ),
                ): str,
                vol.Required(
                    "device_name",
                    default=self._get_reconfigure_entry().data.get(
                        "device_name", "XGSPON ONU Stick"
                    ),
                ): str,
            }
        )

        if user_input is not None:
            # Store user input
            self._data.update(user_input)

            # Check if SSH is available on the new host
            if not await check_ssh_availability(self.hass, user_input["onu_host"]):
                errors["base"] = "ssh_not_available"
            else:
                try:
                    # Generate or reuse SSH key
                    await generate_ssh_key(self.hass, self._data)

                    # Set the unique_id and check for conflicts
                    await self.async_set_unique_id(self._data["onu_host"])
                    self._abort_if_unique_id_configured(updates={})

                    # Update the existing config entry
                    return self.async_update_reload_and_abort(
                        self._get_reconfigure_entry(),
                        data_updates=self._data,
                        title=user_input["device_name"],
                    )
                except CannotConnect as e:
                    errors["base"] = str(e)
                except Exception:
                    _LOGGER.exception("Unexpected exception during reconfiguration")
                    errors["base"] = "unknown"

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=RECONFIGURE_SCHEMA,
            errors=errors,
            description_placeholders={
                "onu_host": self._data.get(
                    "onu_host", self._get_reconfigure_entry().data.get("onu_host")
                ),
                "public_key": self._data.get(
                    CONF_PUBLIC_KEY,
                    self._get_reconfigure_entry().data.get(CONF_PUBLIC_KEY, ""),
                ),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Define the config flow to handle options."""
        return OptionsFlow(config_entry)


class OptionsFlow(config_entries.OptionsFlow):
    """Handle options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ):
        """Manage the options."""
        if user_input is not None:
            # Save the options
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
                }
            ),
        )
