"""Select platform for option-based AION auxiliary settings."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
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
    """Load select descriptors from the coordinator and create select entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities(
        AionHomeSelectEntity(coordinator, descriptor)
        for descriptor in coordinator.get_entities_for_platform("select")
    )


class AionHomeSelectEntity(AionHomeBaseEntity, SelectEntity):
    """Represent an option-based AION auxiliary setting."""

    @property
    def options(self) -> list[str]:
        """Expose the allowed options declared by the normalized descriptor."""
        control = self.descriptor.get("control", {})
        return list(control.get("options") or control.get("option_map", {}).keys())

    @property
    def current_option(self) -> str | None:
        """Expose the current selected option from the normalized descriptor."""
        return self.descriptor.get("state", {}).get("current_option")

    async def async_select_option(self, option: str) -> None:
        """Write the selected option back through the AuxCommands endpoint."""
        control = self.descriptor.get("control", {})
        raw_value = control.get("option_map", {}).get(option, option)
        state_patch = await self.coordinator.local_client.async_execute_service_command(
            descriptor=self.descriptor,
            command_type="aux",
            command_payload=self._build_aux_command_payload(raw_value),
        )
        if state_patch is None:
            state_patch = {}
        state_patch["current_option"] = option
        await self.coordinator.async_apply_entity_patch(self._entity_uid, state_patch)