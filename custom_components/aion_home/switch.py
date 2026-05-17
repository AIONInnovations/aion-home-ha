"""Switch platform for primary and auxiliary AION Home entities."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
from .entity import AionHomeBaseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Load switch descriptors from the coordinator and create switch entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities(
        AionHomeSwitchEntity(coordinator, descriptor)
        for descriptor in coordinator.get_entities_for_platform("switch")
    )


class AionHomeSwitchEntity(AionHomeBaseEntity, SwitchEntity):
    """Represent both primary switches and simple boolean auxiliary settings."""

    @property
    def is_on(self) -> bool | None:
        """Expose the current boolean state from the normalized descriptor."""
        return bool(self.descriptor.get("state", {}).get("is_on", False))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the primary switch or enable a boolean auxiliary field."""
        await self._async_write_switch_value(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the primary switch or disable a boolean auxiliary field."""
        await self._async_write_switch_value(False)

    async def _async_write_switch_value(self, is_enabled: bool) -> None:
        """Route the switch write to the primary endpoint or the aux settings endpoint."""
        control = self.descriptor.get("control", {})
        if control.get("family") == "primary":
            state_patch = await self.coordinator.local_client.async_execute_primary(
                descriptor=self.descriptor,
                command_value=100 if is_enabled else 0,
            )
        else:
            payload = {control["field"]: "1" if is_enabled else "0"}
            state_patch = await self.coordinator.local_client.async_execute_service_command(
                descriptor=self.descriptor,
                command_type="aux",
                command_payload=payload,
            )

        await self.coordinator.async_apply_entity_patch(self._entity_uid, state_patch)