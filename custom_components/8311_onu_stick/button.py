"""Button platform for the ONU Stick integration."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DEVICE_MANUFACTURER,
    CONF_DEVICE_NAME,
    CONF_HOST,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the button platform."""
    _LOGGER.debug("Setting up buttons for ONU at %s", entry.data[CONF_HOST])

    entities = [
        OnuRebootButton(entry),
        OnuRegenerateSshKeyButton(entry),
    ]

    _LOGGER.debug("Created %d buttons", len(entities))
    async_add_entities(entities)


class OnuRebootButton(ButtonEntity):
    """Representation of the reboot button."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:restart"

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the reboot button."""
        self._entry = entry
        self._attr_unique_id = f"{entry.data[CONF_HOST]}_reboot"
        self._attr_name = "Reboot"

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.data[CONF_HOST])},
            name=self._entry.data[CONF_DEVICE_NAME],
            manufacturer=self._entry.data[CONF_DEVICE_MANUFACTURER],
        )

    async def async_press(self) -> None:
        """Handle the button press."""
        _LOGGER.info("Reboot button pressed for ONU at %s", self._entry.data[CONF_HOST])
        
        # Call the reboot service
        await self.hass.services.async_call(
            DOMAIN,
            "reboot_onu_stick",
            target={"entity": {"integration": DOMAIN}},
        )


class OnuRegenerateSshKeyButton(ButtonEntity):
    """Representation of the regenerate SSH key button."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:key-refresh"

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the regenerate SSH key button."""
        self._entry = entry
        self._attr_unique_id = f"{entry.data[CONF_HOST]}_regenerate_ssh_key"
        self._attr_name = "Regenerate SSH Key"
        self._attr_available = True  # Available by default

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.data[CONF_HOST])},
            name=self._entry.data[CONF_DEVICE_NAME],
            manufacturer=self._entry.data[CONF_DEVICE_MANUFACTURER],
        )

    async def async_press(self) -> None:
        """Handle the button press."""
        _LOGGER.info("Regenerate SSH key button pressed for ONU at %s", self._entry.data[CONF_HOST])
        
        # Call the regenerate SSH key service
        await self.hass.services.async_call(
            DOMAIN,
            "regenerate_ssh_key",
            target={"entity": {"integration": DOMAIN}},
        ) 