"""Interfaces with the Woffu api switches."""

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
)
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
    """Set up the Switch entity."""
    coordinator: WoffuCoordinator = config_entry.runtime_data.coordinator

    async_add_entities([WoffuSwitch(coordinator)])


class WoffuSwitch(WoffuEntity, SwitchEntity):
    """Switch to clock-in or clock-out the user in Woffu."""
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:clock-in"

    def __init__(self, coordinator: WoffuCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.account_id}_clock_in"
        self._attr_translation_key = "clock_in"

    @property
    def is_on(self) -> bool | None:
        """Return True if the user is clocked in."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.clocked_in

    async def _async_clock(self, clock_in: bool) -> None:
        await self.coordinator.api.async_clock_in_out(clock_in)
        if self.coordinator.data is not None:
            self.coordinator.data.clocked_in = clock_in
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        """Clock in."""
        await self._async_clock(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Clock out."""
        await self._async_clock(False)