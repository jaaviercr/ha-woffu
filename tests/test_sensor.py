"""Tests for the Woffu worked-hours sensor."""

from unittest.mock import MagicMock

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from custom_components.woffu.const import DOMAIN
from custom_components.woffu.coordinator import (
    Device,
    DeviceType,
    WoffuAPIData,
    WoffuCoordinator,
)
from custom_components.woffu.sensor import WoffuWorkedHours
from pytest_homeassistant_custom_component.common import MockConfigEntry


@pytest.fixture
def sensor(hass):
    """Return a worked-hours sensor with an initial value."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"},
        unique_id="user@example.com",
    )
    entry.add_to_hass(hass)
    coordinator = WoffuCoordinator(hass, entry)
    device = Device(
        device_id=2,
        device_type=DeviceType.TIME,
        device_unique_id="user@example.com_worked_time_today",
        translation_key="worked_time_today",
        state=90,
    )
    entity = WoffuWorkedHours(coordinator, device)
    entity.hass = hass
    entity.async_write_ha_state = MagicMock()
    return entity, coordinator


async def test_sensor_exposes_minutes_as_hours(sensor):
    """The sensor converts the API minutes to decimal hours."""
    entity, _ = sensor

    assert entity.native_value == pytest.approx(1.5)


async def test_sensor_uses_updated_coordinator_device(sensor):
    """The sensor uses the latest value after a coordinator update."""
    entity, coordinator = sensor
    coordinator.data = WoffuAPIData(
        controller_name="user_example_com",
        devices=[
            Device(
                device_id=2,
                device_type=DeviceType.TIME,
                device_unique_id="user@example.com_worked_time_today",
                translation_key="worked_time_today",
                state=150,
            )
        ],
    )

    entity._handle_coordinator_update()

    assert entity.native_value == pytest.approx(2.5)
    entity.async_write_ha_state.assert_called_once_with()
