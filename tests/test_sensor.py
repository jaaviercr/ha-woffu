"""Tests for the Woffu worked-hours sensor."""

from unittest.mock import MagicMock

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from custom_components.woffu.const import DOMAIN
from custom_components.woffu.coordinator import (
    WoffuAPIData,
    WoffuCoordinator,
)
from custom_components.woffu.sensor import (
    WoffuBreakTimeToday,
    WoffuWorkedHours,
    WoffuWorkedHoursThisWeek,
)
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
        work_intervals=[{"entry": "09:00", "exit": "10:30"}],
        break_minutes=30,
        sign_count=4,
        weekly_minutes=450,
        weekly_daily_minutes={"2026-10-17": 360, "2026-10-18": 90},
        weekly_history_stale=False,
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


async def test_worked_hours_expose_intervals_as_attributes(sensor):
    """The existing worked-hours sensor exposes today's clocking pairs."""
    entity, _ = sensor

    assert entity.extra_state_attributes == {
        "work_intervals": [{"entry": "09:00", "exit": "10:30"}],
        "sign_count": 4,
    }


async def test_break_sensor_reports_break_hours(sensor):
    """The break sensor converts accumulated minutes to decimal hours."""
    _, coordinator = sensor
    entity = WoffuBreakTimeToday(coordinator)

    assert entity.native_value == pytest.approx(0.5)


async def test_weekly_sensor_reports_hours_and_daily_breakdown(sensor):
    """The weekly sensor converts minutes and exposes a daily breakdown."""
    _, coordinator = sensor
    entity = WoffuWorkedHoursThisWeek(coordinator)

    assert entity.native_value == pytest.approx(7.5)
    assert entity.extra_state_attributes == {
        "daily_worked_hours": {"2026-10-17": 6, "2026-10-18": 1.5},
        "history_stale": False,
    }


async def test_sensors_use_distinct_icons(sensor):
    """Each duration sensor has an icon matching its time period or purpose."""
    worked_entity, coordinator = sensor
    break_entity = WoffuBreakTimeToday(coordinator)
    weekly_entity = WoffuWorkedHoursThisWeek(coordinator)

    assert worked_entity.icon == "mdi:clock-check-outline"
    assert break_entity.icon == "mdi:coffee-outline"
    assert weekly_entity.icon == "mdi:calendar-week"
