"""Woffu integration using DataUpdateCoordinator."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
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
from homeassistant.util import dt as dt_util

from .api import API, APIAuthError, APIConnectionError
from .const import (
    CONF_WEEKLY_REFRESH_INTERVAL_HOURS,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DEFAULT_WEEKLY_REFRESH_INTERVAL_HOURS,
    DOMAIN,
    MIN_SCAN_INTERVAL_SECONDS,
    MIN_WEEKLY_REFRESH_INTERVAL_HOURS,
)


_LOGGER = logging.getLogger(__name__)


@dataclass
class WoffuAPIData:
    """Data returned by one Woffu account update."""

    clocked_in: bool
    worked_minutes: int | float
    work_intervals: list[dict[str, str | None]]
    break_minutes: int | float
    sign_count: int
    weekly_minutes: int | float | None
    weekly_daily_minutes: dict[str, int | float]
    weekly_history_stale: bool

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
        self.weekly_refresh_interval = timedelta(
            hours=max(
                config_entry.options.get(
                    CONF_WEEKLY_REFRESH_INTERVAL_HOURS,
                    DEFAULT_WEEKLY_REFRESH_INTERVAL_HOURS,
                ),
                MIN_WEEKLY_REFRESH_INTERVAL_HOURS,
            )
        )
        self._weekly_week_start: date | None = None
        self._weekly_closed_minutes: dict[date, int | float] = {}
        self._weekly_history_complete = False
        self._weekly_history_stale = True
        self._weekly_last_attempt: datetime | None = None
        self._weekly_attempted_through: date | None = None
        self._last_complete_weekly_minutes: int | float | None = None
        self._last_complete_weekly_daily_minutes: dict[str, int | float] = {}

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

            now = dt_util.now()
            snapshot = await self.api.async_get_workday_snapshot(True, now=now)
            week_start = now.date() - timedelta(days=now.weekday())
            await self._async_update_weekly_history(now, week_start)
        except APIAuthError as err:
            raise ConfigEntryAuthFailed(err) from err
        except APIConnectionError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        weekly_minutes = self._last_complete_weekly_minutes
        weekly_daily_minutes = self._last_complete_weekly_daily_minutes.copy()
        if self._weekly_history_complete:
            weekly_daily_minutes = {
                day.isoformat(): minutes
                for day, minutes in self._weekly_closed_minutes.items()
            }
            weekly_daily_minutes[now.date().isoformat()] = snapshot.worked_minutes
            weekly_minutes = sum(weekly_daily_minutes.values())
            self._last_complete_weekly_minutes = weekly_minutes
            self._last_complete_weekly_daily_minutes = weekly_daily_minutes.copy()

        return WoffuAPIData(
            clocked_in=snapshot.clocked_in,
            worked_minutes=snapshot.worked_minutes,
            work_intervals=snapshot.work_intervals,
            break_minutes=snapshot.break_minutes,
            sign_count=snapshot.sign_count,
            weekly_minutes=weekly_minutes,
            weekly_daily_minutes=weekly_daily_minutes,
            weekly_history_stale=self._weekly_history_stale,
        )

    async def _async_update_weekly_history(
        self, now: datetime, week_start: date
    ) -> None:
        """Refresh and atomically replace cached minutes for closed week days."""
        if self._weekly_week_start != week_start:
            self._weekly_week_start = week_start
            self._weekly_closed_minutes.clear()
            self._weekly_history_complete = False
            self._weekly_history_stale = True
            self._weekly_last_attempt = None
            self._weekly_attempted_through = None
            self._last_complete_weekly_minutes = None
            self._last_complete_weekly_daily_minutes = {}

        latest_closed_day = now.date() - timedelta(days=1)
        should_refresh = (
            self._weekly_last_attempt is None
            or now - self._weekly_last_attempt >= self.weekly_refresh_interval
            or (
                latest_closed_day >= week_start
                and (
                    self._weekly_attempted_through is None
                    or latest_closed_day > self._weekly_attempted_through
                )
            )
        )
        if not should_refresh:
            return

        self._weekly_last_attempt = now
        self._weekly_attempted_through = (
            latest_closed_day if latest_closed_day >= week_start else None
        )
        refreshed_minutes: dict[date, int | float] = {}
        try:
            if latest_closed_day >= week_start:
                refreshed_minutes = await self.api.async_get_worked_minutes_for_range(
                    week_start, latest_closed_day
                )
                expected_dates = {
                    week_start + timedelta(days=day_offset)
                    for day_offset in range((latest_closed_day - week_start).days + 1)
                }
                if set(refreshed_minutes) != expected_dates:
                    raise APIConnectionError(
                        "Woffu returned an incomplete weekly diary range"
                    )
        except APIAuthError:
            raise
        except APIConnectionError as err:
            self._weekly_history_stale = True
            _LOGGER.warning("Unable to refresh weekly Woffu history: %s", err)
            return

        self._weekly_closed_minutes = refreshed_minutes
        self._weekly_history_complete = True
        self._weekly_history_stale = False
