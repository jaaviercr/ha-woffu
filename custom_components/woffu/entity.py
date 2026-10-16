"""Shared entities for the Woffu integration."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WoffuCoordinator


class WoffuEntity(CoordinatorEntity):
    """Base entity with account-level device metadata."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WoffuCoordinator) -> None:
        super().__init__(coordinator)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            name=f"Woffu {self.coordinator.user}",
            model="Woffu",
            manufacturer="WOFFU JOB ORGANIZER SL",
            identifiers={(DOMAIN, self.coordinator.account_id)},
        )

    @property
    def translation_placeholders(self) -> dict[str, str]:
        return {"user": self.coordinator.user}
