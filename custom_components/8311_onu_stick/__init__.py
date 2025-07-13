from __future__ import annotations
import os
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_KEY_PATH
from .coordinator import OnuDataUpdateCoordinator
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up XGSPON ONU Stick from a config entry."""
    _LOGGER.debug("Setting up ONU Stick integration for %s", entry.data.get("onu_host"))
    coordinator = OnuDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
    }

    # Set up options update listener
    entry.async_on_unload(entry.add_update_listener(async_options_updated))

    _LOGGER.debug("Forwarding entry setups for platforms: %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    # Update the coordinator's scan interval
    if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
        coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
        coordinator.update_scan_interval()
        _LOGGER.debug("Updated scan interval for entry %s", entry.entry_id)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the XGSPON ONU Stick component."""
    # Set up services
    await async_setup_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # Clean up the generated key file if it exists
        key_path = entry.data.get(CONF_KEY_PATH)
        # Get storage directory path
        storage_dir = hass.config.path("storage")
        if key_path and key_path.startswith(storage_dir):
            try:
                await hass.async_add_executor_job(os.remove, key_path)
                _LOGGER.info("Removed SSH key file: %s", key_path)
            except OSError as e:
                _LOGGER.error("Error removing SSH key file %s: %s", key_path, e)
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
