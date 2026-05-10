"""Shared base entity used by all AION Home Home Assistant platforms."""

from __future__ import annotations

from typing import Any
import copy
import logging

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_CONFIG_ENTRY_ID, ATTR_DEVICE_UID, ATTR_ENTITY_UID, DOMAIN
from .coordinator import AionHomeDataUpdateCoordinator


LOGGER = logging.getLogger(__name__)
_UNSET = object()


class AionHomeBaseEntity(CoordinatorEntity[AionHomeDataUpdateCoordinator], Entity):
    """Expose the shared entity metadata, device info, and optimistic service path."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AionHomeDataUpdateCoordinator,
        descriptor: dict[str, Any],
    ) -> None:
        """Store the normalized descriptor used to build the Home Assistant entity."""
        super().__init__(coordinator)
        self._entity_uid = descriptor[ATTR_ENTITY_UID]
        self._attr_unique_id = self._entity_uid

    @property
    def descriptor(self) -> dict[str, Any]:
        """Return the latest descriptor snapshot for this entity."""
        return self.coordinator.get_entity(self._entity_uid) or {}

    @property
    def name(self) -> str | None:
        """Return the user-facing entity name from the gateway descriptor."""
        return self.descriptor.get("name")

    @property
    def available(self) -> bool:
        """Mark the entity unavailable when local connection details are missing or device is offline."""
        local = self.descriptor.get("local", {})
        if not (
            bool(local.get("device_ip"))
            and bool(local.get("device_ssid"))
            and bool(local.get("main_key"))
        ):
            return False
        return self.descriptor.get("local_available", True)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose normalized ids and routing metadata for gateway services and debugging."""
        device = self.descriptor.get("device", {})
        control = self.descriptor.get("control", {})
        attributes = {
            ATTR_ENTITY_UID: self._entity_uid,
            ATTR_DEVICE_UID: device.get(ATTR_DEVICE_UID),
            ATTR_CONFIG_ENTRY_ID: self.coordinator.config_entry.entry_id,
            "home_name": device.get("home_name"),
            "room_name": device.get("room_name"),
            "room_key": device.get("room_key"),
            "category": device.get("category"),
            "control_family": control.get("family"),
        }
        if control.get("description"):
            attributes["description"] = control["description"]
        if control.get("option_descriptions"):
            attributes["option_descriptions"] = control["option_descriptions"]
        if control.get("unsupported_current_value"):
            attributes["unsupported_current_value"] = control[
                "unsupported_current_value"
            ]
        return attributes

    def _build_aux_command_payload(self, value: Any) -> dict[str, Any]:
        """Build either a flat or nested AuxCommands payload from descriptor metadata."""
        control = self.descriptor.get("control", {})
        root_object_field = control.get("root_object_field")
        if isinstance(root_object_field, str) and root_object_field:
            root_object = self._build_grouped_aux_root_object(
                root_object_field,
                control,
            )
            payload_path = self._get_relative_payload_path(
                root_object_field,
                control.get("payload_path"),
            )
            self._set_nested_payload_value(root_object, payload_path, value)
            return {root_object_field: root_object}

        payload_path = control.get("payload_path")
        if isinstance(payload_path, list) and payload_path:
            nested_payload: Any = value
            for path_segment in reversed(payload_path):
                nested_payload = {str(path_segment): nested_payload}
            return nested_payload

        field_name = control.get("field")
        if not field_name:
            raise ValueError("AION auxiliary descriptor is missing its field name.")
        return {str(field_name): value}

    def _build_grouped_aux_root_object(
        self,
        root_object_field: str,
        control: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the full grouped sw/gangs object expected by 4_gang AuxCommands writes."""
        root_object = copy.deepcopy(control.get("root_object_seed", {}))
        if not isinstance(root_object, dict):
            root_object = {}

        self._overlay_grouped_aux_state(root_object_field, root_object)
        return root_object

    def _overlay_grouped_aux_state(
        self,
        root_object_field: str,
        root_object: dict[str, Any],
    ) -> None:
        """Keep grouped payload seeds aligned with the latest entity states before one write."""
        if not self.coordinator.data:
            return

        device_uid = self.descriptor.get("device", {}).get(ATTR_DEVICE_UID)
        if not device_uid:
            return

        for related_descriptor in self.coordinator.data.get("entities", []):
            related_control = related_descriptor.get("control", {})
            if related_descriptor.get("device", {}).get(ATTR_DEVICE_UID) != device_uid:
                continue
            if related_control.get("root_object_field") != root_object_field:
                continue

            raw_value = self._extract_descriptor_raw_control_value(related_descriptor)
            if raw_value is _UNSET:
                continue

            payload_path = self._get_relative_payload_path(
                root_object_field,
                related_control.get("payload_path"),
            )
            if not payload_path:
                continue

            self._set_nested_payload_value(root_object, payload_path, raw_value)

    def _extract_descriptor_raw_control_value(self, descriptor: dict[str, Any]) -> Any:
        """Convert one normalized entity state back into the raw AuxCommands value it writes."""
        control = descriptor.get("control", {})
        state = descriptor.get("state", {})
        platform = descriptor.get("platform")

        if platform == "select":
            current_option = state.get("current_option")
            if current_option is None:
                return _UNSET
            return control.get("option_map", {}).get(current_option, current_option)

        if platform == "switch":
            is_on = state.get("is_on")
            if is_on is None:
                return _UNSET
            if bool(is_on):
                return control.get("on_value", "1")
            return control.get("off_value", "0")

        if platform == "number":
            native_value = state.get("native_value")
            if native_value is None:
                return _UNSET
            return native_value

        return _UNSET

    def _get_relative_payload_path(
        self,
        root_object_field: str,
        payload_path: Any,
    ) -> list[str]:
        """Strip the grouped root field from payload paths so nested writes target one root object."""
        if not isinstance(payload_path, list) or not payload_path:
            return []

        normalized_path = [str(path_segment) for path_segment in payload_path]
        if normalized_path[0] == root_object_field:
            return normalized_path[1:]
        return normalized_path

    def _set_nested_payload_value(
        self,
        target: dict[str, Any],
        payload_path: list[str],
        value: Any,
    ) -> None:
        """Write one nested value into a grouped sw/gangs payload tree."""
        if not payload_path:
            return

        cursor: dict[str, Any] = target
        for path_segment in payload_path[:-1]:
            current_value = cursor.get(path_segment)
            if not isinstance(current_value, dict):
                current_value = {}
                cursor[path_segment] = current_value
            cursor = current_value

        cursor[payload_path[-1]] = value

    @property
    def entity_category(self) -> EntityCategory | None:
        """Map the normalized category string into Home Assistant entity categories."""
        raw_category = self.descriptor.get("entity_category")
        if raw_category == "config":
            return EntityCategory.CONFIG
        if raw_category == "diagnostic":
            return EntityCategory.DIAGNOSTIC
        return None

    @property
    def device_info(self) -> DeviceInfo:
        """Attach every normalized entity to its parent physical AION device."""
        device = self.descriptor.get("device", {})
        device_uid = device.get(ATTR_DEVICE_UID)
        suggested_area = device.get("room_name")
        return DeviceInfo(
            identifiers={(DOMAIN, device_uid)},
            manufacturer="AION",
            model=device.get("category"),
            name=device.get("name"),
            suggested_area=suggested_area,
        )

    async def async_execute_service_command(
        self,
        command_type: str,
        command_payload: Any,
    ) -> None:
        """Execute a raw auxiliary command and apply an optimistic patch if one exists."""
        state_patch = await self.coordinator.local_client.async_execute_service_command(
            descriptor=self.descriptor,
            command_type=command_type,
            command_payload=command_payload,
        )
        await self.coordinator.async_apply_entity_patch(self._entity_uid, state_patch)