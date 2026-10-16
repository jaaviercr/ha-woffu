"""Interfaces with the Woffu api sensors."""

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import WoffuConfigEntry
from .coordinator import WoffuCoordinator
from .entity import WoffuEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: WoffuConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up the sensor entities."""
    coordinator: WoffuCoordinator = config_entry.runtime_data.coordinator

    async_add_entities([WoffuWorkedHours(coordinator)])


class WoffuWorkedHours(WoffuEntity, SensorEntity):
    """Sensor to show the accumulated hours and minutes in the current workday."""
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: WoffuCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.account_id}_worked_time_today"
        self._attr_translation_key = "worked_time_today"

    @property
    def native_value(self) -> float | None:
        """Return the hours accumulated during the current workday."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.worked_minutes / 60