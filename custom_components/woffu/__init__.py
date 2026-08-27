"""The Woffu integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import WoffuCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH]

type WoffuConfigEntry = ConfigEntry[RuntimeData]


@dataclass
class RuntimeData:
    """Runtime data shared by the Woffu platforms."""

    coordinator: WoffuCoordinator


async def async_setup_entry(
    hass: HomeAssistant, config_entry: WoffuConfigEntry
) -> bool:
    """Set up Woffu Integration from a config entry."""
    coordinator = WoffuCoordinator(hass, config_entry)
    await coordinator.async_config_entry_first_refresh()

    config_entry.async_on_unload(
        config_entry.add_update_listener(_async_update_listener)
    )
    config_entry.runtime_data = RuntimeData(coordinator)

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    return True


async def _async_update_listener(
    hass: HomeAssistant, config_entry: WoffuConfigEntry
) -> None:
    """Reload the integration when the options change."""
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, config_entry: WoffuConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)
