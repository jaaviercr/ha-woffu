"""Tests for the Woffu coordinator."""

from unittest.mock import MagicMock

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.woffu.api import APIAuthError, APIConnectionError
from custom_components.woffu.const import DOMAIN
from custom_components.woffu.coordinator import WoffuCoordinator
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


async def test_update_builds_switch_and_time_devices(hass, config_entry):
    """A successful update exposes both configured device values."""
    coordinator = WoffuCoordinator(hass, config_entry)
    coordinator.api.connected = True
    coordinator.get_device_value = MagicMock(side_effect=[True, 270])

    result = await coordinator.async_update_data()

    assert result.controller_name == "user_example_com"
    assert [(device.device_type, device.state) for device in result.devices] == [
        ("switch", True),
        ("time", 270),
    ]
    assert [device.device_unique_id for device in result.devices] == [
        "user@example.com_clock_in",
        "user@example.com_worked_time_today",
    ]


async def test_update_translates_authentication_error(hass, config_entry):
    """Authentication failures become a config-entry auth failure."""
    coordinator = WoffuCoordinator(hass, config_entry)
    coordinator.api.connect = MagicMock(side_effect=APIAuthError("bad password"))

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator.async_update_data()


async def test_update_translates_connection_error(hass, config_entry):
    """Connection failures become an update failure."""
    coordinator = WoffuCoordinator(hass, config_entry)
    coordinator.api.connect = MagicMock(side_effect=APIConnectionError("offline"))

    with pytest.raises(UpdateFailed, match="offline"):
        await coordinator.async_update_data()
