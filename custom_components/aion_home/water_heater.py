"""Water heater platform for AION IR remotes (Water Heater)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import AionHomeDataUpdateCoordinator

# In-memory target temperature defaults — no persistence (IR has no feedback).
_DEFAULT_TEMPERATURE = 40.0
_MIN_TEMPERATURE = 30.0
_MAX_TEMPERATURE = 80.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a water_heater entity for each IR sub-remote of type Water Heater."""
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    entities = [
        AionIRWaterHeater(coordinator, descriptor)
        for descriptor in coordinator.get_entities_for_platform("water_heater")
        if descriptor.get("control", {}).get("family") == "ir"
    ]
    # LOGGER.info(\n    #     \"[AION][water_heater] setup_entry: registering %d entities\", len(entities)\n    # )
    async_add_entities(entities)


class AionIRWaterHeater(
    CoordinatorEntity[AionHomeDataUpdateCoordinator], WaterHeaterEntity
):
    """
    Represent an IR-controlled water heater.

    Power, Temp Up, and Temp Down are mapped to HA services.
    Temperature changes are tracked in-memory only — IR has no state feedback.
    set_temperature fires Temp Up / Temp Down N times based on the delta.
    """

    _attr_has_entity_name = True
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.ON_OFF
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = _MIN_TEMPERATURE
    _attr_max_temp = _MAX_TEMPERATURE
    _attr_target_temperature_step = 1.0
    _attr_current_temperature = None
    _attr_operation_list = ["on", "off"]

    def __init__(
        self,
        coordinator: AionHomeDataUpdateCoordinator,
        descriptor: dict[str, Any],
    ) -> None:
        """Store entity uid and initialise optimistic target temperature."""
        super().__init__(coordinator)
        self._entity_uid: str = descriptor["entity_uid"]
        self._attr_unique_id = self._entity_uid
        self._attr_name: str = descriptor.get("name", "")

        device = descriptor.get("device", {})
        control = descriptor.get("control", {})
        self._device_uid: str = device.get("device_uid", "")
        self._device_room: str = device.get("room_name", "")
        self._remote_id: str = control.get("remote_id", "")
        self._remote_type: str = control.get("remote_type") or "IR Water Heater"
        self._remote_brand: str = control.get("brand") or "AION"
        self._virtual_device_uid: str = (
            f"{self._device_uid}::ir_{self._remote_id}"
            if self._remote_id
            else self._device_uid
        )
        # Optimistic temperature — tracked in memory, not persisted.
        self._target_temperature: float = _DEFAULT_TEMPERATURE

    @property
    def _descriptor(self) -> dict[str, Any]:
        """Return the live descriptor from the coordinator cache."""
        return self.coordinator.get_entity(self._entity_uid) or {}

    @property
    def available(self) -> bool:
        """Available when the parent device has a reachable local connection."""
        desc = self._descriptor
        local = desc.get("local", {})
        if not (
            bool(local.get("device_ip"))
            and bool(local.get("device_ssid"))
            and bool(local.get("main_key"))
        ):
            return False
        return desc.get("local_available", True)

    @property
    def device_info(self) -> DeviceInfo:
        """Attach this entity to its sub-remote's virtual device card."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._virtual_device_uid)},
            name=self._attr_name,
            model=self._remote_type,
            manufacturer=self._remote_brand,
            suggested_area=self._device_room,
            via_device=(DOMAIN, self._device_uid) if self._remote_id else None,
        )

    @property
    def target_temperature(self) -> float:
        """Return the optimistic in-memory target temperature."""
        return self._target_temperature

    @property
    def current_operation(self) -> str:
        """Always unknown — IR provides no power state feedback."""
        return "on"

    def _get_service_command(self, service: str) -> str | None:
        """
        Look up the IR command label mapped to a given HA service name.

        Returns None if no mapping exists for this service on this remote type.
        """
        control = self._descriptor.get("control", {})
        return control.get("ha_service_map", {}).get(service)

    async def _fire(self, service: str) -> None:
        """Fire the IR command associated with a given HA service name."""
        command_label = self._get_service_command(service)
        if not command_label:
            return
        await self.coordinator.local_client.async_execute_service_command(
            descriptor=self._descriptor,
            command_type="ir",
            command_payload=command_label,
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Send Power IR command to turn the water heater on."""
        await self._fire("turn_on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Send Power IR command to turn the water heater off."""
        await self._fire("turn_off")

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """
        Adjust temperature by firing Temp Up or Temp Down N times.

        Computes the signed delta between the requested temperature and the
        in-memory target, clamps it to [-20, +20] presses, then fires the
        appropriate IR command once per degree step.
        """
        new_temp = kwargs.get("temperature")
        if new_temp is None:
            return

        new_temp = float(new_temp)
        delta = round(new_temp - self._target_temperature)

        if delta == 0:
            return

        # Clamp to a safe number of IR presses to avoid runaway sequences.
        MAX_STEPS = 20
        if abs(delta) > MAX_STEPS:
            delta = MAX_STEPS if delta > 0 else -MAX_STEPS

        service = "increase_temperature" if delta > 0 else "decrease_temperature"
        for _ in range(abs(delta)):
            await self._fire(service)

        # Update the optimistic in-memory temperature.
        self._target_temperature = new_temp
        self.async_write_ha_state()
