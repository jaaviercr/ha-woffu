"""Interfaces with the Woffu api sensors."""

from typing import Any

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

    async_add_entities(
        [
            WoffuWorkedHours(coordinator),
            WoffuBreakTimeToday(coordinator),
            WoffuWorkedHoursThisWeek(coordinator),
        ]
    )


class WoffuWorkedHours(WoffuEntity, SensorEntity):
    """Sensor to show the accumulated hours and minutes in the current workday."""
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_icon = "mdi:clock-check-outline"
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

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return today's clock-in and clock-out pairs."""
        if self.coordinator.data is None:
            return None
        return {
            "work_intervals": self.coordinator.data.work_intervals,
            "sign_count": self.coordinator.data.sign_count,
        }


class WoffuBreakTimeToday(WoffuEntity, SensorEntity):
    """Sensor for completed breaks between today's work intervals."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_icon = "mdi:coffee-outline"
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: WoffuCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.account_id}_break_time_today"
        self._attr_translation_key = "break_time_today"

    @property
    def native_value(self) -> float | None:
        """Return completed break time in hours."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.break_minutes / 60


class WoffuWorkedHoursThisWeek(WoffuEntity, SensorEntity):
    """Sensor for worked hours accumulated from Monday through today."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_icon = "mdi:calendar-week"
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: WoffuCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.account_id}_worked_time_this_week"
        self._attr_translation_key = "worked_time_this_week"

    @property
    def native_value(self) -> float | None:
        """Return the complete weekly total in hours, when available."""
        if self.coordinator.data is None:
            return None
        weekly_minutes = self.coordinator.data.weekly_minutes
        if weekly_minutes is None:
            return None
        return weekly_minutes / 60

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the daily breakdown and whether cached history is stale."""
        if self.coordinator.data is None:
            return None
        return {
            "daily_worked_hours": {
                day: minutes / 60
                for day, minutes in self.coordinator.data.weekly_daily_minutes.items()
            },
            "history_stale": self.coordinator.data.weekly_history_stale,
        }