from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DEVICE_MANUFACTURER,
    CONF_DEVICE_NAME,
    CONF_HOST,
    CONF_PUBLIC_KEY,
    DOMAIN,
)
from .coordinator import OnuDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

STRING_SENSOR_DEFINITIONS = {
    "active_bank": {
        "name": "Active Firmware Bank",
        "icon": "mdi:memory",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "ploam_status": {
        "name": "PLOAM Status",
        "icon": "mdi:signal",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "pon_mode": {
        "name": "PON Mode",
        "icon": "mdi:network",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "mac_address": {
        "name": "Management MAC Address",
        "icon": "mdi:ethernet-cable",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "ip_address": {
        "name": "Management IP Address",
        "icon": "mdi:ip-network",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "uptime": {
        "name": "Uptime",
        "icon": "mdi:clock",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "soc_model": {
        "name": "SoC Model",
        "icon": "mdi:chip",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "soc_arch": {
        "name": "SoC Architecture",
        "icon": "mdi:chip",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "public_key": {
        "name": "SSH Public Key",
        "icon": "mdi:key-variant",
        "entity_category": EntityCategory.CONFIG,
    },
}


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the string sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    _LOGGER.debug("Setting up string sensors for ONU at %s", entry.data[CONF_HOST])

    entities = []
    
    # Add all coordinator-based string sensors
    for key, config in STRING_SENSOR_DEFINITIONS.items():
        if key == "public_key":
            continue
        entities.append(OnuStringSensor(coordinator, key, config))

    # Add the static public key sensor
    if CONF_PUBLIC_KEY in entry.data:
        entities.append(OnuPublicKeyStringSensor(entry, STRING_SENSOR_DEFINITIONS["public_key"]))

    _LOGGER.debug("Created %d string sensors", len(entities))
    async_add_entities(entities)


class OnuPublicKeyStringSensor(SensorEntity):
    """Representation of the public key string sensor."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, config: dict) -> None:
        """Initialize the string sensor."""
        self._entry = entry
        self._attr_unique_id = f"{self._entry.data[CONF_HOST]}_public_key"
        self._attr_name = config["name"]
        self._attr_icon = config["icon"]
        self._attr_entity_category = config["entity_category"]

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.data[CONF_HOST])},
            name=self._entry.data[CONF_DEVICE_NAME],
            manufacturer=self._entry.data[CONF_DEVICE_MANUFACTURER],
        )

    @property
    def native_value(self) -> str | None:
        """Return the value of the sensor."""
        public_key = self._entry.data.get(CONF_PUBLIC_KEY)
        if public_key and public_key.startswith("ssh-rsa"):
            return "RSA"
        return "Unknown"

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Return entity specific state attributes."""
        # For now, just return the basic public key
        # Key management info will be updated via service calls
        public_key = self._entry.data.get(CONF_PUBLIC_KEY)
        if public_key:
            return {"public_key": public_key}
        return None


class OnuStringSensor(SensorEntity):
    """Representation of a string sensor from the ONU stick."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: OnuDataUpdateCoordinator, entity_key: str, config: dict) -> None:
        """Initialize the string sensor."""
        self.coordinator = coordinator
        self.entity_key = entity_key
        self._attr_unique_id = f"{coordinator.config[CONF_HOST]}_{entity_key}"
        self._attr_name = config["name"]
        self._attr_icon = config["icon"]
        self._attr_entity_category = config["entity_category"]

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        mac_address = self.coordinator.data.get("mac_address")
        connections = {("mac", mac_address)} if mac_address else set()
        
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config[CONF_HOST])},
            name=self.coordinator.config[CONF_DEVICE_NAME],
            manufacturer=self.coordinator.config[CONF_DEVICE_MANUFACTURER],
            model=self.coordinator.data.get("device_model"),
            sw_version=self.coordinator.data.get("device_sw_version"),
            hw_version=self.coordinator.data.get("device_hw_version"),
            connections=connections,
            serial_number=self.coordinator.data.get("pon_serial")
        )

    @property
    def native_value(self) -> str | None:
        """Return the value of the sensor."""
        return self.coordinator.data.get(self.entity_key, "Unknown")

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        _LOGGER.debug("Checking availability for string sensor %s: last_update_success=%s", 
                     self.entity_key, self.coordinator.last_update_success)
        return self.coordinator.last_update_success

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        ) 