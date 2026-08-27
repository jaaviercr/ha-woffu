"""Woffu integration using DataUpdateCoordinator."""

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import API, APIAuthError, APIConnectionError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN


class DeviceType(StrEnum):
    SWITCH = "switch"
    TIME = "time"


@dataclass
class Device:
    device_id: int
    device_type: DeviceType
    device_unique_id: str
    translation_key: str
    state: int | float | bool


_LOGGER = logging.getLogger(__name__)


@dataclass
class WoffuAPIData:
    """Class to hold api data."""

    controller_name: str
    devices: list[Device]

class WoffuCoordinator(DataUpdateCoordinator):
    """Woffu coordinator."""

    # Definition of managed devices
    DEVICES = [
        {"id": 1, "type": DeviceType.SWITCH, "unique_id": "clock_in", "translation_key": "clock_in"},
        {"id": 2, "type": DeviceType.TIME, "unique_id": "worked_time_today", "translation_key": "worked_time_today"},
    ]

    data: WoffuAPIData

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize coordinator."""

        # Set variables from values entered in config flow setup
        self.user = config_entry.data[CONF_USERNAME]
        self.pwd = config_entry.data[CONF_PASSWORD]
        self.account_id = config_entry.unique_id or config_entry.entry_id

        # Set variables from options.  You need a default here incase options have not been set
        self.poll_interval = config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )

        # Initialise DataUpdateCoordinator
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} ({config_entry.unique_id})",
            update_method=self.async_update_data,
            update_interval=timedelta(seconds=self.poll_interval),
        )

        self.api = API(user=self.user, pwd=self.pwd)

    async def async_update_data(self):
        """Fetch data from API endpoint and build device list."""
        try:
            if not self.api.connected:
                await self.hass.async_add_executor_job(self.api.connect)

            devices = []
            for device in self.DEVICES:
                device_id = device["id"]
                device_type = device["type"]
                translation_key = device["translation_key"]
                state = await self.hass.async_add_executor_job(self.get_device_value, device_id, device_type)
                devices.append(Device(
                    device_id=device_id,
                    device_type=device_type,
                    device_unique_id=f"{self.account_id}_{device['unique_id']}",
                    translation_key=translation_key,
                    state=state
                ))
        except APIAuthError as err:
            raise ConfigEntryAuthFailed(err) from err
        except APIConnectionError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        return WoffuAPIData(self.api.controller_name, devices)

    def get_device_value(self, device_id: int, device_type: DeviceType) -> int | bool | float:
        if device_type == DeviceType.SWITCH:
            return self.api.is_clocked_in()
        if device_type == DeviceType.TIME:
            return self.api.get_time_worked_today()
        return 0

    def get_device_by_id(
        self, device_type: DeviceType, device_id: int
    ) -> Device | None:
        """Return device by device id."""
        try:
            return [
                device
                for device in self.data.devices
                if device.device_type == device_type and device.device_id == device_id
            ][0]
        except IndexError:
            return None
