"""Tests for the Woffu worked-hours sensor."""

from unittest.mock import MagicMock

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from custom_components.woffu.const import DOMAIN
from custom_components.woffu.coordinator import (
    WoffuAPIData,
    WoffuCoordinator,
)
from custom_components.woffu.sensor import WoffuWorkedHours
from pytest_homeassistant_custom_component.common import MockConfigEntry


@pytest.fixture
async def sensor(hass):
    """Return a worked-hours sensor with an initial value."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"},
        unique_id="user@example.com",
    )
    entry.add_to_hass(hass)
    coordinator = WoffuCoordinator(hass, entry)
    coordinator.data = WoffuAPIData(
        clocked_in=False,
        worked_minutes=90,
    )
    entity = WoffuWorkedHours(coordinator)
    entity.hass = hass
    entity.async_write_ha_state = MagicMock()
    return entity, coordinator


async def test_sensor_exposes_minutes_as_hours(sensor):
    """The sensor converts the API minutes to decimal hours."""
    entity, _ = sensor

    assert entity.native_value == pytest.approx(1.5)


async def test_sensor_uses_shared_account_metadata(sensor):
    """The sensor exposes account-level device metadata."""
    entity, coordinator = sensor

    assert entity.device_info["identifiers"] == {(DOMAIN, coordinator.account_id)}
    assert entity.translation_placeholders == {"user": coordinator.user}


async def test_sensor_uses_updated_coordinator_device(sensor):
    """The sensor uses the latest value after a coordinator update."""
    entity, coordinator = sensor
    coordinator.data.worked_minutes = 150

    entity._handle_coordinator_update()

    assert entity.native_value == pytest.approx(2.5)
    entity.async_write_ha_state.assert_called_once_with()
