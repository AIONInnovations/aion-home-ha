"""Climate platform for AION AC remotes."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature
from homeassistant.components.climate.const import HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN, FAN_MODE_MAP, HVAC_MODE_MAP
from .entity import AionHomeBaseEntity
from .helpers import reverse_lookup


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Load climate descriptors from the coordinator and create climate entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities(
        AionHomeClimateEntity(coordinator, descriptor)
        for descriptor in coordinator.get_entities_for_platform("climate")
    )


class AionHomeClimateEntity(AionHomeBaseEntity, ClimateEntity):
    """Represent an AION AC remote using the full AC JSON command payload."""

    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        # Adds dedicated on/off power buttons to the climate card (HA 2024.2+).
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 16.0
    _attr_max_temp = 30.0
    _attr_target_temperature_step = 1.0

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Expose the normalized HVAC mode from the gateway descriptor."""
        raw_mode = self.descriptor.get("state", {}).get("hvac_mode", HVACMode.COOL)
        return HVACMode(raw_mode)

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Expose the supported HVAC modes from the normalized control metadata."""
        raw_modes = self.descriptor.get("control", {}).get(
            "hvac_modes",
            list(HVAC_MODE_MAP.values()),
        )
        return [HVACMode(raw_mode) for raw_mode in raw_modes if raw_mode in HVACMode._value2member_map_]

    @property
    def target_temperature(self) -> float | None:
        """Expose the normalized AC target temperature."""
        return float(self.descriptor.get("state", {}).get("target_temperature", 24.0))

    @property
    def fan_mode(self) -> str | None:
        """Expose the normalized AC fan mode string."""
        return self.descriptor.get("state", {}).get("fan_mode", "auto")

    @property
    def fan_modes(self) -> list[str] | None:
        """Expose the supported AC fan modes from the gateway descriptor."""
        return self.descriptor.get("control", {}).get(
            "fan_modes",
            list(FAN_MODE_MAP.values()),
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Write a new HVAC mode by patching the AION AC state object."""
        if hvac_mode == HVACMode.OFF:
            # Off is controlled by p=0 only — do not change the saved mode (m).
            ac_patch = {"p": "0"}
        else:
            ac_patch = {
                "p": "1",
                "m": reverse_lookup(HVAC_MODE_MAP, hvac_mode.value, "1"),
            }
        state_patch = await self.coordinator.local_client.async_execute_service_command(
            descriptor=self.descriptor,
            command_type="ac",
            command_payload=ac_patch,
        )
        await self.coordinator.async_apply_entity_patch(self._entity_uid, state_patch)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Write a new AC target temperature to the local AC action endpoint."""
        target_temperature = kwargs.get("temperature")
        if target_temperature is None:
            return
        # Firmware expects t as a string (mirrors the app's .toString() call).
        state_patch = await self.coordinator.local_client.async_execute_service_command(
            descriptor=self.descriptor,
            command_type="ac",
            command_payload={"t": str(int(target_temperature)), "p": "1"},
        )
        await self.coordinator.async_apply_entity_patch(self._entity_uid, state_patch)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Write a new AC fan mode to the local AC action endpoint."""
        state_patch = await self.coordinator.local_client.async_execute_service_command(
            descriptor=self.descriptor,
            command_type="ac",
            command_payload={"f": reverse_lookup(FAN_MODE_MAP, fan_mode, "0"), "p": "1"},
        )
        await self.coordinator.async_apply_entity_patch(self._entity_uid, state_patch)

    async def async_turn_on(self) -> None:
        """Power on the AC using the last known mode and state object."""
        state_patch = await self.coordinator.local_client.async_execute_service_command(
            descriptor=self.descriptor,
            command_type="ac",
            command_payload={"p": "1"},
        )
        await self.coordinator.async_apply_entity_patch(self._entity_uid, state_patch)

    async def async_turn_off(self) -> None:
        """Power off the AC without mutating the remaining saved AC state fields."""
        state_patch = await self.coordinator.local_client.async_execute_service_command(
            descriptor=self.descriptor,
            command_type="ac",
            command_payload={"p": "0"},
        )
        await self.coordinator.async_apply_entity_patch(self._entity_uid, state_patch)