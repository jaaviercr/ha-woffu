"""Tests for the Woffu coordinator."""

from unittest.mock import AsyncMock

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.woffu.api import APIAuthError, APIConnectionError
from custom_components.woffu.const import DOMAIN, MIN_SCAN_INTERVAL_SECONDS
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


async def test_update_builds_account_data_from_one_snapshot(hass, config_entry):
    """One workday snapshot provides all account data."""
    coordinator = WoffuCoordinator(hass, config_entry)
    coordinator.api.connected = True
    coordinator.api.connected = True
    coordinator.api.async_get_workday_snapshot = AsyncMock(return_value=(270, True))

    result = await coordinator.async_update_data()

    coordinator.api.async_get_workday_snapshot.assert_awaited_once_with(True)
    assert result == WoffuAPIData(
        controller_name="user_example_com",
        clocked_in=True,
        worked_minutes=270,
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
