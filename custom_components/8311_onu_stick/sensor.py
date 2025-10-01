from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfTemperature,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfDataRate,
    UnitOfInformation,
    PERCENTAGE,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_DEVICE_MANUFACTURER,
    CONF_DEVICE_NAME,
    CONF_HOST,
    CONF_PUBLIC_KEY,
    DOMAIN,
)
from .coordinator import OnuDataUpdateCoordinator

from .string_sensor import OnuStringSensor, OnuPublicKeyStringSensor, STRING_SENSOR_DEFINITIONS

_LOGGER = logging.getLogger(__name__)

ENTITY_DEFINITIONS = {
    "temp_cpu0": SensorEntityDescription(
        key="temp_cpu0",
        name="CPU 0",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "temp_cpu1": SensorEntityDescription(
        key="temp_cpu1",
        name="CPU 1",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "temp_optic": SensorEntityDescription(
        key="temp_optic",
        name="Optical",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "rx_power": SensorEntityDescription(
        key="rx_power",
        name="RX Power",
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "tx_power": SensorEntityDescription(
        key="tx_power",
        name="TX Power",
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "tx_bias": SensorEntityDescription(
        key="tx_bias",
        name="TX Bias",
        native_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "voltage": SensorEntityDescription(
        key="voltage",
        name="Module Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "eth_speed": SensorEntityDescription(
        key="eth_speed",
        name="Ethernet Speed",
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:ethernet",
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "cpu_utilization": SensorEntityDescription(
        key="cpu_utilization",
        name="CPU Utilization",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:percent",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "memory_total": SensorEntityDescription(
        key="memory_total",
        name="Memory Total",
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:memory",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "memory_used": SensorEntityDescription(
        key="memory_used",
        name="Memory Used",
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:memory",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "memory_available": SensorEntityDescription(
        key="memory_available",
        name="Memory Available",
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:memory",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "memory_percent": SensorEntityDescription(
        key="memory_percent",
        name="Memory Usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:memory",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
}


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    _LOGGER.debug("Setting up sensor entities for ONU at %s", entry.data[CONF_HOST])

    entities = []
    
    # Add numeric sensors
    for key in ENTITY_DEFINITIONS:
        entities.append(OnuSensor(coordinator, key))



    # Add string sensors (replacing text sensors)
    for key, config in STRING_SENSOR_DEFINITIONS.items():
        if key == "public_key":
            continue
        entities.append(OnuStringSensor(coordinator, key, config))

    # Add the static public key sensor
    if CONF_PUBLIC_KEY in entry.data:
        entities.append(OnuPublicKeyStringSensor(entry, STRING_SENSOR_DEFINITIONS["public_key"]))

    _LOGGER.debug("Created %d sensor entities", len(entities))
    async_add_entities(entities)


class OnuSensor(SensorEntity):
    """Representation of a Sensor."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: OnuDataUpdateCoordinator, sensor_key: str) -> None:
        """Initialize the sensor."""
        self.coordinator = coordinator
        self.sensor_key = sensor_key
        self._attr_unique_id = f"{coordinator.config[CONF_HOST]}_{sensor_key}"
        entity_desc = ENTITY_DEFINITIONS[sensor_key]
        _LOGGER.debug("Creating sensor %s with entity description type: %s", sensor_key, type(entity_desc))
        # The frozen dataclass is the correct type, so we don't need to check
        self.entity_description = entity_desc

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
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        return self.coordinator.data.get(self.sensor_key)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        _LOGGER.debug("Checking availability for sensor %s: last_update_success=%s, data=%s", 
                     self.sensor_key, self.coordinator.last_update_success, 
                     self.coordinator.data.get(self.sensor_key) if self.coordinator.data else "No data")
        return self.coordinator.last_update_success
