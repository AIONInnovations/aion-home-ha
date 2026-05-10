"""Cover platform for AION shutter devices."""

from __future__ import annotations

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverEntity,
    CoverEntityFeature,
)
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
    """Load cover descriptors from the coordinator and create cover entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities(
        AionHomeCoverEntity(coordinator, descriptor)
        for descriptor in coordinator.get_entities_for_platform("cover")
    )


class AionHomeCoverEntity(AionHomeBaseEntity, CoverEntity):
    """Represent an AION shutter that accepts level and stop commands locally."""

    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    @property
    def current_cover_position(self) -> int | None:
        """Expose the last normalized shutter position from the gateway payload."""
        return int(self.descriptor.get("state", {}).get("position", 0))

    @property
    def is_closed(self) -> bool | None:
        """Mark the cover as closed when its normalized position is zero."""
        return bool(self.descriptor.get("state", {}).get("is_closed", False))

    async def async_open_cover(self, **kwargs) -> None:
        """Open the shutter fully using the primary LAN command contract."""
        state_patch = await self.coordinator.local_client.async_execute_primary(
            descriptor=self.descriptor,
            command_value=100,
        )
        await self.coordinator.async_apply_entity_patch(self._entity_uid, state_patch)

    async def async_close_cover(self, **kwargs) -> None:
        """Close the shutter fully using the primary LAN command contract."""
        state_patch = await self.coordinator.local_client.async_execute_primary(
            descriptor=self.descriptor,
            command_value=0,
        )
        await self.coordinator.async_apply_entity_patch(self._entity_uid, state_patch)

    async def async_stop_cover(self, **kwargs) -> None:
        """Stop a moving shutter using the firmware's literal stop command."""
        await self.coordinator.local_client.async_execute_primary(
            descriptor=self.descriptor,
            command_value="stop",
        )

    async def async_set_cover_position(self, **kwargs) -> None:
        """Move the shutter to a specific percentage position snapped to the nearest 10."""
        position = int(kwargs[ATTR_POSITION])
        # Firmware only accepts discrete 10-step levels (0, 10, 20, … 100).
        snapped_position = max(0, min(100, round(position / 10) * 10))
        state_patch = await self.coordinator.local_client.async_execute_primary(
            descriptor=self.descriptor,
            command_value=snapped_position,
        )
        await self.coordinator.async_apply_entity_patch(self._entity_uid, state_patch)