"""Woffu integration using DataUpdateCoordinator."""

from dataclasses import dataclass
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import API, APIAuthError, APIConnectionError
from .const import (
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    MIN_SCAN_INTERVAL_SECONDS,
)


_LOGGER = logging.getLogger(__name__)


@dataclass
class WoffuAPIData:
    """Data returned by one Woffu account update."""

    clocked_in: bool
    worked_minutes: int | float

class WoffuCoordinator(DataUpdateCoordinator):
    """Woffu coordinator."""

    data: WoffuAPIData

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize coordinator."""

        # Set variables from values entered in config flow setup
        self.user = config_entry.data[CONF_USERNAME]
        self.pwd = config_entry.data[CONF_PASSWORD]
        self.account_id = config_entry.unique_id or config_entry.entry_id

        # Set variables from options.  You need a default here incase options have not been set
        self.poll_interval = max(
            config_entry.options.get(
                CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS
            ),
            MIN_SCAN_INTERVAL_SECONDS,
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

        self.api = API(
            user=self.user,
            pwd=self.pwd,
            session=async_get_clientsession(hass),
        )

    async def async_update_data(self) -> WoffuAPIData:
        """Fetch the latest account state from Woffu."""
        try:
            if not self.api.connected:
                await self.api.async_connect()

            worked_minutes, clocked_in = await self.api.async_get_workday_snapshot(
                True
            )
        except APIAuthError as err:
            raise ConfigEntryAuthFailed(err) from err
        except APIConnectionError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        return WoffuAPIData(
            clocked_in=clocked_in,
            worked_minutes=worked_minutes,
        )
