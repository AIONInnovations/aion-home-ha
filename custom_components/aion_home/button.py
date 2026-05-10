"""Button platform for AION auxiliary actions and IR command buttons."""

from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import AionHomeDataUpdateCoordinator
from .entity import AionHomeBaseEntity

LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Load button descriptors and create both auxiliary and IR command buttons."""
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]

    # Auxiliary buttons (restart etc.) from the coordinator's button platform.
    aux_buttons = [
        AionHomeButtonEntity(coordinator, descriptor)
        for descriptor in coordinator.get_entities_for_platform("button")
    ]

    # IR command buttons — one pressable tile per command on every remote entity.
    ir_buttons: list[AionHomeIRCommandButton] = []

    for remote_desc in coordinator.get_entities_for_platform("remote"):
        control = remote_desc.get("control", {})
        if control.get("family") != "ir":
            continue
        command_list = control.get("command_list", [])
        for command_name in command_list:
            ir_buttons.append(
                AionHomeIRCommandButton(coordinator, remote_desc, command_name)
            )

    # LOGGER.info(
    #     "[AION][button] setup_entry: aux_buttons=%d ir_command_buttons=%d",
    #     len(aux_buttons),
    #     len(ir_buttons),
    # )
    async_add_entities(aux_buttons + ir_buttons)


class AionHomeButtonEntity(AionHomeBaseEntity, ButtonEntity):
    """Represent a stateless auxiliary action such as remote restart."""

    async def async_press(self) -> None:
        """Trigger the normalized auxiliary action represented by this button."""
        await self.coordinator.local_client.async_execute_service_command(
            descriptor=self.descriptor,
            command_type=self.descriptor.get("control", {}).get("family", "restart"),
            command_payload=None,
        )


class AionHomeIRCommandButton(
    CoordinatorEntity[AionHomeDataUpdateCoordinator], ButtonEntity
):
    """
    A pressable tile that fires one named IR command through its parent sub-remote.

    One instance is created per command in a non-AC IR sub-remote's command_list.
    These appear as individual button tiles in the HA dashboard, grouped under the
    same physical device as the parent remote entity.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AionHomeDataUpdateCoordinator,
        parent_descriptor: dict[str, Any],
        command_name: str,
    ) -> None:
        """Store the parent descriptor reference and build a stable unique id."""
        super().__init__(coordinator)
        # Keep the parent entity_uid so we always read the latest descriptor snapshot.
        self._parent_entity_uid: str = parent_descriptor.get("entity_uid", "")
        self._command_name: str = command_name

        # Slugify the command name for a stable, filesystem-safe unique_id suffix.
        slug = re.sub(r"[^a-z0-9]+", "_", command_name.lower()).strip("_")
        self._attr_unique_id = f"{self._parent_entity_uid}::cmd_{slug}"
        self._attr_name = command_name

        # Cache device metadata — comes from the static device subtree, never changes.
        device = parent_descriptor.get("device", {})
        control = parent_descriptor.get("control", {})
        self._device_uid: str = device.get("device_uid", "")
        self._device_room: str = device.get("room_name", "")

        # Virtual sub-remote device — each IR sub-remote gets its own HA device card,
        # linked back to the physical hub via via_device.
        remote_id: str = control.get("remote_id", "")
        self._virtual_device_uid: str = (
            f"{self._device_uid}::ir_{remote_id}" if remote_id else self._device_uid
        )
        self._remote_name: str = parent_descriptor.get("name", "")
        self._remote_type: str = control.get("remote_type") or "IR Remote"
        self._remote_brand: str = control.get("brand") or "AION"

    def _get_parent(self) -> dict[str, Any]:
        """Return the latest parent remote descriptor from the coordinator cache."""
        return self.coordinator.get_entity(self._parent_entity_uid) or {}

    @property
    def available(self) -> bool:
        """Available when the parent device has a reachable local connection."""
        parent = self._get_parent()
        local = parent.get("local", {})
        if not (
            bool(local.get("device_ip"))
            and bool(local.get("device_ssid"))
            and bool(local.get("main_key"))
        ):
            return False
        return parent.get("local_available", True)

    @property
    def device_info(self) -> DeviceInfo:
        """Place this button on its sub-remote's virtual device card.

        The virtual device is a child of the physical AION hub (via_device),
        so HA groups it correctly in both the device list and the dashboard.
        """
        return DeviceInfo(
            identifiers={(DOMAIN, self._virtual_device_uid)},
            name=self._remote_name,
            model=self._remote_type,
            manufacturer=self._remote_brand,
            suggested_area=self._device_room,
            via_device=(DOMAIN, self._device_uid),
        )

    async def async_press(self) -> None:
        """Send the named IR command through the parent device's local endpoint."""
        parent = self._get_parent()
        await self.coordinator.local_client.async_execute_service_command(
            descriptor=parent,
            command_type="ir",
            command_payload=self._command_name,
        )