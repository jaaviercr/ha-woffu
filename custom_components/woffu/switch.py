"""Interfaces with the Woffu api switches."""

import logging

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
)
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
    """Set up the Switch entity."""
    coordinator: WoffuCoordinator = config_entry.runtime_data.coordinator

    switches = [
        WoffuSwitch(coordinator, device)
        for device in coordinator.data.devices
        if device.device_type == DeviceType.SWITCH
    ]

    async_add_entities(switches)


class WoffuSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to clock-in or clock-out the user in Woffu."""
    _attr_has_entity_name = True
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: WoffuCoordinator, device: Device) -> None:
        super().__init__(coordinator)
        self.device = device
        self.device_id = device.device_id
        self._attr_unique_id = device.device_unique_id
        self._attr_translation_key = device.translation_key

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update sensor with latest data from coordinator."""
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
    def is_on(self) -> bool | None:
        """Return True if the user is clocked in."""
        if self.device is None:
            return None
        return bool(self.device.state)

    async def _async_clock(self, clock_in: bool) -> None:
        await self.hass.async_add_executor_job(
            self.coordinator.api.clock_in_out, clock_in
        )
        if self.device is not None:
            self.device.state = clock_in
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        """Clock in."""
        await self._async_clock(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Clock out."""
        await self._async_clock(False)