"""Sensor platform for AION diagnostic entities."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
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
    """Load sensor descriptors from the coordinator and create sensor entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities(
        AionHomeSensorEntity(coordinator, descriptor)
        for descriptor in coordinator.get_entities_for_platform("sensor")
    )


class AionHomeSensorEntity(AionHomeBaseEntity, SensorEntity):
    """Represent diagnostic AION fields such as device switch settings."""

    _MAX_NATIVE_VALUE_LENGTH = 255

    @property
    def native_value(self) -> str | None:
        """Expose the raw diagnostic sensor value from the gateway descriptor."""
        raw_value = self.descriptor.get("state", {}).get("native_value")
        if raw_value is None:
            return None
        raw_text = str(raw_value)
        if len(raw_text) <= self._MAX_NATIVE_VALUE_LENGTH:
            return raw_text
        return "diagnostic_state_available"

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose the full diagnostic payload in attributes when it is too long for state."""
        attributes = dict(super().extra_state_attributes)
        raw_value = self.descriptor.get("state", {}).get("native_value")

        if raw_value is None:
            return attributes

        raw_text = str(raw_value)
        if len(raw_text) > self._MAX_NATIVE_VALUE_LENGTH:
            attributes["diagnostic_state"] = raw_text

        return attributes