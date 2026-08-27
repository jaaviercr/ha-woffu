"""Interfaces with the Woffu api sensors."""

import logging

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import WoffuConfigEntry
from .coordinator import Device, DeviceType
from .const import DOMAIN
from .coordinator import WoffuCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: WoffuConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up the sensor entities."""
    coordinator: WoffuCoordinator = config_entry.runtime_data.coordinator

    sensors = [
        WoffuWorkedHours(coordinator, device)
        for device in coordinator.data.devices
        if device.device_type == DeviceType.TIME
    ]

    async_add_entities(sensors)


class WoffuWorkedHours(CoordinatorEntity, SensorEntity):
    """Sensor to show the accumulated hours and minutes in the current workday."""
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: WoffuCoordinator, device: Device) -> None:
        super().__init__(coordinator)
        self.device = device
        self.device_id = device.device_id
        self._attr_unique_id = device.device_unique_id
        self._attr_translation_key = device.translation_key

    @callback
    def _handle_coordinator_update(self) -> None:
        self.device = self.coordinator.get_device_by_id(
            self.device.device_type, self.device_id
        )
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            name=f"Woffu {self.coordinator.user}",
            model="Woffu",
            manufacturer="WOFFU JOB ORGANIZER SL",
            identifiers={(DOMAIN, self.coordinator.account_id)},
        )

    @property
    def translation_placeholders(self) -> dict[str, str]:
        return {"user": self.coordinator.user}

    @property
    def native_value(self) -> float | None:
        """Return the hours accumulated during the current workday."""
        if self.device is None or self.device.state is None:
            return None
        return self.device.state / 60