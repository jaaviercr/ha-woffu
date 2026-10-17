"""Tests for the Woffu switch entity."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import HomeAssistantError

from custom_components.woffu.const import DOMAIN
from custom_components.woffu.coordinator import WoffuAPIData, WoffuCoordinator
from custom_components.woffu.switch import WoffuSwitch
from pytest_homeassistant_custom_component.common import MockConfigEntry


@pytest.fixture
async def switch(hass):
    """Return a Woffu switch with an initial off state."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"},
        unique_id="user@example.com",
    )
    entry.add_to_hass(hass)
    coordinator = WoffuCoordinator(hass, entry)
    coordinator.data = WoffuAPIData(
        clocked_in=False,
        worked_minutes=0,
    )
    entity = WoffuSwitch(coordinator)
    entity.hass = hass
    entity.async_write_ha_state = MagicMock()
    coordinator.api.async_clock_in_out = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    return entity, coordinator


async def test_turn_on_updates_state_and_refreshes(switch):
    """A successful clock-in updates the entity and requests fresh data."""
    entity, coordinator = switch

    assert entity.icon == "mdi:clock-in"

    await entity.async_turn_on()

    coordinator.api.async_clock_in_out.assert_awaited_once_with(True)
    coordinator.async_request_refresh.assert_awaited_once_with()
    assert entity.is_on is True


async def test_switch_uses_shared_account_metadata(switch):
    """The switch exposes account-level device metadata."""
    entity, coordinator = switch

    assert entity.device_info["identifiers"] == {(DOMAIN, coordinator.account_id)}
    assert entity.translation_placeholders == {"user": coordinator.user}


async def test_failed_clock_does_not_update_state_or_refresh(switch):
    """A failed clock operation leaves the previous state unchanged."""
    entity, coordinator = switch
    coordinator.api.async_clock_in_out.side_effect = HomeAssistantError("offline")

    with pytest.raises(HomeAssistantError, match="offline"):
        await entity.async_turn_on()

    coordinator.async_request_refresh.assert_not_awaited()
    assert entity.is_on is False


async def test_consecutive_clock_commands_follow_requested_states(switch):
    """Consecutive commands are sent in order and update the local state."""
    entity, coordinator = switch

    await entity.async_turn_on()
    await entity.async_turn_off()

    assert coordinator.api.async_clock_in_out.await_args_list == [
        ((True,),),
        ((False,),),
    ]
    assert coordinator.async_request_refresh.await_count == 2
    assert entity.is_on is False
