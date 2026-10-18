"""Tests for the Woffu coordinator."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.woffu.api import (
    APIAuthError,
    APIConnectionError,
    WorkdaySnapshot,
)
from custom_components.woffu.const import (
    CONF_WEEKLY_REFRESH_INTERVAL_HOURS,
    DEFAULT_WEEKLY_REFRESH_INTERVAL_HOURS,
    DOMAIN,
    MIN_SCAN_INTERVAL_SECONDS,
)
from custom_components.woffu.coordinator import WoffuAPIData, WoffuCoordinator
from pytest_homeassistant_custom_component.common import MockConfigEntry


@pytest.fixture
def config_entry(hass):
    """Return a configured Woffu entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"},
        unique_id="user@example.com",
    )
    entry.add_to_hass(hass)
    return entry


async def test_update_builds_account_data_from_one_snapshot(
    hass, config_entry, monkeypatch
):
    """One workday snapshot provides all account data."""
    now = datetime(2026, 10, 21, 8, tzinfo=timezone.utc)
    monkeypatch.setattr("custom_components.woffu.coordinator.dt_util.now", lambda: now)
    coordinator = WoffuCoordinator(hass, config_entry)
    coordinator.api.connected = True
    coordinator._async_update_weekly_history = AsyncMock()
    coordinator.api.async_get_workday_snapshot = AsyncMock(
        return_value=WorkdaySnapshot(
            worked_minutes=270,
            clocked_in=True,
            work_intervals=[{"entry": "09:00", "exit": None}],
            break_minutes=0,
            sign_count=1,
        )
    )

    result = await coordinator.async_update_data()

    coordinator.api.async_get_workday_snapshot.assert_awaited_once_with(True, now=now)
    assert result == WoffuAPIData(
        clocked_in=True,
        worked_minutes=270,
        work_intervals=[{"entry": "09:00", "exit": None}],
        break_minutes=0,
        sign_count=1,
        weekly_minutes=None,
        weekly_daily_minutes={},
        weekly_history_stale=True,
    )


async def test_update_translates_authentication_error(hass, config_entry):
    """Authentication failures become a config-entry auth failure."""
    coordinator = WoffuCoordinator(hass, config_entry)
    coordinator.api.async_connect = AsyncMock(
        side_effect=APIAuthError("bad password")
    )

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator.async_update_data()


async def test_update_translates_connection_error(hass, config_entry):
    """Connection failures become an update failure."""
    coordinator = WoffuCoordinator(hass, config_entry)
    coordinator.api.async_connect = AsyncMock(
        side_effect=APIConnectionError("offline")
    )

    with pytest.raises(UpdateFailed, match="offline"):
        await coordinator.async_update_data()


async def test_coordinator_enforces_minimum_scan_interval(hass):
    """Legacy options below one minute are raised to the new minimum."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"},
        options={"scan_interval": 10},
        unique_id="user@example.com",
    )

    coordinator = WoffuCoordinator(hass, entry)

    assert coordinator.poll_interval == MIN_SCAN_INTERVAL_SECONDS


async def test_weekly_total_caches_closed_days_and_refreshes_on_interval(
    hass, config_entry, monkeypatch
):
    """The weekly sum uses cached historical days and current daily data."""
    now = datetime(2026, 10, 21, 8, tzinfo=timezone.utc)
    monkeypatch.setattr("custom_components.woffu.coordinator.dt_util.now", lambda: now)
    coordinator = WoffuCoordinator(hass, config_entry)
    coordinator.api.connected = True
    coordinator.api.async_get_workday_snapshot = AsyncMock(
        return_value=WorkdaySnapshot(
            worked_minutes=120,
            clocked_in=False,
            work_intervals=[],
            break_minutes=0,
            sign_count=0,
        )
    )
    coordinator.api.async_get_worked_minutes_for_range = AsyncMock(
        return_value={date(2026, 10, 19): 480, date(2026, 10, 20): 0}
    )

    result = await coordinator.async_update_data()

    coordinator.api.async_get_worked_minutes_for_range.assert_awaited_once_with(
        date(2026, 10, 19), date(2026, 10, 20)
    )
    assert result.weekly_minutes == 600
    assert result.weekly_daily_minutes == {
        "2026-10-19": 480,
        "2026-10-20": 0,
        "2026-10-21": 120,
    }
    assert result.weekly_history_stale is False

    coordinator.api.async_get_workday_snapshot.return_value = WorkdaySnapshot(
        worked_minutes=180,
        clocked_in=False,
        work_intervals=[],
        break_minutes=0,
        sign_count=0,
    )
    result = await coordinator.async_update_data()

    coordinator.api.async_get_worked_minutes_for_range.assert_awaited_once()
    assert result.weekly_minutes == 660


async def test_weekly_total_keeps_last_complete_value_on_history_error(
    hass, config_entry, monkeypatch
):
    """A failed refresh preserves the last full weekly total, not a partial sum."""
    now = datetime(2026, 10, 21, 8, tzinfo=timezone.utc)
    monkeypatch.setattr("custom_components.woffu.coordinator.dt_util.now", lambda: now)
    coordinator = WoffuCoordinator(hass, config_entry)
    coordinator.api.connected = True
    coordinator.api.async_get_workday_snapshot = AsyncMock(
        return_value=WorkdaySnapshot(
            worked_minutes=120,
            clocked_in=False,
            work_intervals=[],
            break_minutes=0,
            sign_count=0,
        )
    )
    coordinator.api.async_get_worked_minutes_for_range = AsyncMock(
        return_value={date(2026, 10, 19): 480, date(2026, 10, 20): 0}
    )
    await coordinator.async_update_data()

    coordinator._weekly_last_attempt -= timedelta(hours=6)
    coordinator.api.async_get_worked_minutes_for_range.side_effect = APIConnectionError(
        "offline"
    )
    result = await coordinator.async_update_data()

    assert coordinator.api.async_get_worked_minutes_for_range.await_count == 2
    assert result.weekly_minutes == 600
    assert result.weekly_history_stale is True


async def test_coordinator_uses_default_weekly_refresh_interval(hass, config_entry):
    """Legacy entries get the default weekly history refresh interval."""
    coordinator = WoffuCoordinator(hass, config_entry)

    assert coordinator.weekly_refresh_interval == timedelta(
        hours=DEFAULT_WEEKLY_REFRESH_INTERVAL_HOURS
    )


async def test_coordinator_enforces_minimum_weekly_refresh_interval(hass):
    """Legacy options below one hour are raised to the minimum."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"},
        options={CONF_WEEKLY_REFRESH_INTERVAL_HOURS: 0},
        unique_id="user@example.com",
    )

    coordinator = WoffuCoordinator(hass, entry)

    assert coordinator.weekly_refresh_interval == timedelta(hours=1)
