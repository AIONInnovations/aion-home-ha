"""Shared base entity used by all AION Home Home Assistant platforms."""

from __future__ import annotations

from typing import Any
import logging

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_CONFIG_ENTRY_ID, ATTR_DEVICE_UID, ATTR_ENTITY_UID, DOMAIN
from .coordinator import AionHomeDataUpdateCoordinator


LOGGER = logging.getLogger(__name__)


class AionHomeBaseEntity(CoordinatorEntity[AionHomeDataUpdateCoordinator], Entity):
    """Expose the shared entity metadata, device info, and optimistic service path."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AionHomeDataUpdateCoordinator,
        descriptor: dict[str, Any],
    ) -> None:
        """Store the normalized descriptor used to build the Home Assistant entity."""
        super().__init__(coordinator)
        self._entity_uid = descriptor[ATTR_ENTITY_UID]
        self._attr_unique_id = self._entity_uid

    @property
    def descriptor(self) -> dict[str, Any]:
        """Return the latest descriptor snapshot for this entity."""
        return self.coordinator.get_entity(self._entity_uid) or {}

    @property
    def name(self) -> str | None:
        """Return the user-facing entity name from the gateway descriptor."""
        return self.descriptor.get("name")

    @property
    def available(self) -> bool:
        """Mark the entity unavailable when local connection details are missing or device is offline."""
        local = self.descriptor.get("local", {})
        if not (
            bool(local.get("device_ip"))
            and bool(local.get("device_ssid"))
            and bool(local.get("main_key"))
        ):
            return False
        return self.descriptor.get("local_available", True)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose normalized ids and routing metadata for gateway services and debugging."""
        device = self.descriptor.get("device", {})
        control = self.descriptor.get("control", {})
        return {
            ATTR_ENTITY_UID: self._entity_uid,
            ATTR_DEVICE_UID: device.get(ATTR_DEVICE_UID),
            ATTR_CONFIG_ENTRY_ID: self.coordinator.config_entry.entry_id,
            "home_name": device.get("home_name"),
            "room_name": device.get("room_name"),
            "room_key": device.get("room_key"),
            "category": device.get("category"),
            "control_family": control.get("family"),
        }

    @property
    def entity_category(self) -> EntityCategory | None:
        """Map the normalized category string into Home Assistant entity categories."""
        raw_category = self.descriptor.get("entity_category")
        if raw_category == "config":
            return EntityCategory.CONFIG
        if raw_category == "diagnostic":
            return EntityCategory.DIAGNOSTIC
        return None

    @property
    def device_info(self) -> DeviceInfo:
        """Attach every normalized entity to its parent physical AION device."""
        device = self.descriptor.get("device", {})
        device_uid = device.get(ATTR_DEVICE_UID)
        suggested_area = device.get("room_name")
        return DeviceInfo(
            identifiers={(DOMAIN, device_uid)},
            manufacturer="AION",
            model=device.get("category"),
            name=device.get("name"),
            suggested_area=suggested_area,
        )

    async def async_execute_service_command(
        self,
        command_type: str,
        command_payload: Any,
    ) -> None:
        """Execute a raw auxiliary command and apply an optimistic patch if one exists."""
        state_patch = await self.coordinator.local_client.async_execute_service_command(
            descriptor=self.descriptor,
            command_type=command_type,
            command_payload=command_payload,
        )
        await self.coordinator.async_apply_entity_patch(self._entity_uid, state_patch)