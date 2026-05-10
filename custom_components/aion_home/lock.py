"""Lock platform for AION door lock devices."""

from __future__ import annotations

from homeassistant.components.lock import LockEntity
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
    """Load lock descriptors from the coordinator and create lock entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities(
        AionHomeLockEntity(coordinator, descriptor)
        for descriptor in coordinator.get_entities_for_platform("lock")
    )


class AionHomeLockEntity(AionHomeBaseEntity, LockEntity):
    """Represent an AION door lock using the same primary LAN command endpoint."""

    @property
    def is_locked(self) -> bool | None:
        """Expose the normalized locked state from the gateway descriptor."""
        return bool(self.descriptor.get("state", {}).get("is_locked", False))

    async def async_lock(self, **kwargs) -> None:
        """Lock the door using the firmware's primary close command."""
        state_patch = await self.coordinator.local_client.async_execute_primary(
            descriptor=self.descriptor,
            command_value=0,
        )
        await self.coordinator.async_apply_entity_patch(self._entity_uid, state_patch)

    async def async_unlock(self, **kwargs) -> None:
        """Unlock the door using the firmware's primary open command."""
        state_patch = await self.coordinator.local_client.async_execute_primary(
            descriptor=self.descriptor,
            command_value=1,
        )
        await self.coordinator.async_apply_entity_patch(self._entity_uid, state_patch)