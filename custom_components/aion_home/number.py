"""Number platform for AION numeric auxiliary settings such as shutter timers."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity
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
    """Load number descriptors from the coordinator and create number entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities(
        AionHomeNumberEntity(coordinator, descriptor)
        for descriptor in coordinator.get_entities_for_platform("number")
    )


class AionHomeNumberEntity(AionHomeBaseEntity, NumberEntity):
    """Represent a numeric AION auxiliary field exposed as a Home Assistant number."""

    @property
    def native_value(self) -> float | None:
        """Expose the last normalized numeric value from the gateway descriptor."""
        return float(self.descriptor.get("state", {}).get("native_value", 0))

    @property
    def native_min_value(self) -> float:
        """Expose the configured minimum value allowed by the gateway descriptor."""
        return float(self.descriptor.get("control", {}).get("min", 0))

    @property
    def native_max_value(self) -> float:
        """Expose the configured maximum value allowed by the gateway descriptor."""
        return float(self.descriptor.get("control", {}).get("max", 100))

    @property
    def native_step(self) -> float:
        """Expose the configured step value allowed by the gateway descriptor."""
        return float(self.descriptor.get("control", {}).get("step", 1))

    async def async_set_native_value(self, value: float) -> None:
        """Write the numeric auxiliary field back through the AuxCommands endpoint."""
        field_name = self.descriptor.get("control", {}).get("field")
        state_patch = await self.coordinator.local_client.async_execute_service_command(
            descriptor=self.descriptor,
            command_type="aux",
            command_payload={field_name: str(int(value))},
        )
        await self.coordinator.async_apply_entity_patch(self._entity_uid, state_patch)