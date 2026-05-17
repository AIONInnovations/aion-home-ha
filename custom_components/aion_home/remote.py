"""Remote platform for AION IR entities."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.components.remote import RemoteEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
from .entity import AionHomeBaseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Load remote descriptors from the coordinator and create remote entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    descriptors = coordinator.get_entities_for_platform("remote")

    # Pre-register every IR hub device so sub-remote entities can safely reference
    # it via via_device without triggering the "non-existing via_device" warning.
    device_reg = dr.async_get(hass)
    registered_hub_uids: set[str] = set()
    for descriptor in descriptors:
        device = descriptor.get("device", {})
        control = descriptor.get("control", {})
        device_uid: str = device.get("device_uid", "")
        remote_id: str = control.get("remote_id", "")
        if remote_id and device_uid and device_uid not in registered_hub_uids:
            device_reg.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, device_uid)},
                manufacturer="AION",
                model="IR Hub",
                name=device.get("device_name", "IR Hub"),
                suggested_area=device.get("room_name", ""),
            )
            registered_hub_uids.add(device_uid)

    async_add_entities(
        AionHomeRemoteEntity(coordinator, descriptor)
        for descriptor in descriptors
    )


class AionHomeRemoteEntity(AionHomeBaseEntity, RemoteEntity):
    """Represent an AION IR remote that exposes send_command to Home Assistant."""

    @property
    def device_info(self) -> DeviceInfo:
        """Place the remote entity on the same virtual sub-remote device as its buttons.

        Mirrors the virtual device uid used by AionHomeIRCommandButton so all entities
        for one sub-remote share a single HA device card.
        """
        device = self.descriptor.get("device", {})
        control = self.descriptor.get("control", {})
        device_uid: str = device.get("device_uid", "")
        remote_id: str = control.get("remote_id", "")
        virtual_uid: str = (
            f"{device_uid}::ir_{remote_id}" if remote_id else device_uid
        )
        return DeviceInfo(
            identifiers={(DOMAIN, virtual_uid)},
            name=self.descriptor.get("name", ""),
            model=control.get("remote_type") or "IR Remote",
            manufacturer=control.get("brand") or "AION",
            suggested_area=device.get("room_name", ""),
            via_device=(DOMAIN, device_uid) if remote_id else None,
        )

    @property
    def is_on(self) -> bool | None:
        """Keep IR remotes available even though they are stateless senders."""
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose available IR command names so automations can discover them."""
        base = super().extra_state_attributes or {}
        control = self.descriptor.get("control", {})
        command_list = control.get("command_list", [])
        return {**base, "available_commands": command_list}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """No-op — IR remotes are always available; HA requires this to exist."""

    async def async_turn_off(self, **kwargs: Any) -> None:
        """No-op — IR remotes are always available; HA requires this to exist."""

    async def async_send_command(
        self,
        command: Iterable[str] | str,
        **kwargs: Any,
    ) -> None:
        """Send one or more named IR commands through the dedicated local endpoint."""
        commands = [command] if isinstance(command, str) else list(command)
        for single_command in commands:
            await self.coordinator.local_client.async_execute_service_command(
                descriptor=self.descriptor,
                command_type="ir",
                command_payload=single_command,
            )