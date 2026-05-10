"""Local LAN client that wraps transport while delegating the private protocol core."""

from __future__ import annotations

from typing import Any
import logging

from aiohttp import ClientError, ClientSession, ClientTimeout
from homeassistant.exceptions import HomeAssistantError

from ._aion_protocol import AionProtocolCore, AionProtocolError
from .const import FAN_MODE_MAP, HVAC_MODE_MAP, SESSION_TTL_MS
from .helpers import to_bool

LOGGER = logging.getLogger(__name__)

_REQUIRED_LOCAL_FIELDS = frozenset({"device_ip", "device_ssid", "ssid_suffix", "main_key"})
_MISSING = object()


class AionLocalError(HomeAssistantError):
    """Represent a local command or session failure against an AION device."""


class AionLocalClient:
    """Send LAN requests while keeping the HA-facing client API stable."""

    def __init__(self, session: ClientSession) -> None:
        """Store the shared HTTP session and the private protocol engine."""
        self._session = session
        self._protocol = AionProtocolCore()
        self._session_cache: dict[str, dict[str, Any]] = {}

    def _invalidate_session(self, local: dict[str, Any], reason: str) -> None:
        """Drop one cached LAN session after a crypto or auth failure poisons it."""
        device_ssid = str(local.get("device_ssid", ""))
        if not device_ssid:
            return

        self._session_cache.pop(device_ssid, None)



    async def async_execute_primary(
        self,
        descriptor: dict[str, Any],
        command_value: int | str,
    ) -> dict[str, Any] | None:
        """Send a primary on/off/level/position command using the main GET endpoint."""
        local = self._get_local_info(descriptor)
        session_state = await self._async_get_session(local)
        request = self._build_operation_request(
            operation="primary",
            descriptor=descriptor,
            local=local,
            session_state=session_state,
            command_payload=command_value,
        )
        await self._async_send_request(local, request)
        return self._build_primary_patch(descriptor, command_value)

    async def async_execute_service_command(
        self,
        descriptor: dict[str, Any],
        command_type: str,
        command_payload: Any,
    ) -> dict[str, Any] | None:
        """Route a raw auxiliary service request to the matching AION endpoint."""
        normalized_type = command_type.strip().lower()

        if normalized_type == "aux":
            payload = self._normalize_dict_payload(command_payload, "aux")
            await self.async_execute_aux(descriptor, payload)
            return self._build_aux_patch(descriptor, payload)

        if normalized_type == "ir":
            await self.async_execute_ir(descriptor, command_payload)
            return None

        if normalized_type == "ac":
            patch = await self.async_execute_ac(descriptor, command_payload)
            return patch

        if normalized_type == "restart":
            await self.async_execute_restart(descriptor)
            return None

        raise AionLocalError(f"Unsupported command type: {command_type}")

    async def async_execute_aux(
        self,
        descriptor: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        """Send a batched auxiliary settings payload through the AuxCommands endpoint."""
        local = self._get_local_info(descriptor)
        session_state = await self._async_get_session(local)
        request = self._build_operation_request(
            operation="aux",
            descriptor=descriptor,
            local=local,
            session_state=session_state,
            command_payload=payload,
        )
        await self._async_send_request(local, request)

    async def async_execute_ir(
        self,
        descriptor: dict[str, Any],
        command_payload: Any,
    ) -> None:
        """Send an IR command using either a named gateway command or a raw payload."""
        local = self._get_local_info(descriptor)
        session_state = await self._async_get_session(local)
        request = self._build_operation_request(
            operation="ir",
            descriptor=descriptor,
            local=local,
            session_state=session_state,
            command_payload=command_payload,
        )
        await self._async_send_request(local, request)

    async def async_execute_ac(
        self,
        descriptor: dict[str, Any],
        command_payload: Any,
    ) -> dict[str, Any] | None:
        """Send an AC state payload after merging it with the current AC state."""
        local = self._get_local_info(descriptor)
        session_state = await self._async_get_session(local)
        request = self._build_operation_request(
            operation="ac",
            descriptor=descriptor,
            local=local,
            session_state=session_state,
            command_payload=command_payload,
        )
        await self._async_send_request(local, request)
        return self._build_ac_patch(request["merged_ac_state"])

    async def async_execute_restart(self, descriptor: dict[str, Any]) -> None:
        """Send the device restart request through the dedicated restart endpoint."""
        local = self._get_local_info(descriptor)
        session_state = await self._async_get_session(local)
        request = self._build_operation_request(
            operation="restart",
            descriptor=descriptor,
            local=local,
            session_state=session_state,
        )
        await self._async_send_request(local, request)

    async def async_fetch_local_state(
        self,
        descriptor: dict[str, Any],
    ) -> Any:
        """Fetch the current device state from the local state endpoint."""
        local = self._get_local_info(descriptor)
        session_state = await self._async_get_session(local)
        request = self._build_operation_request(
            operation="state",
            descriptor=descriptor,
            local=local,
            session_state=session_state,
        )
        response_text = await self._async_send_request(local, request)
        return self._parse_local_state_response(response_text)

    def _build_operation_request(
        self,
        operation: str,
        descriptor: dict[str, Any],
        local: dict[str, Any],
        session_state: dict[str, Any],
        command_payload: Any = None,
    ) -> dict[str, Any]:
        """Translate protocol-core failures into Home Assistant-facing local errors."""
        try:
            return self._protocol.build_operation_request(
                operation,
                descriptor,
                local,
                session_state,
                command_payload
            )
        except AionProtocolError as error:
            raise AionLocalError(str(error)) from error

    def _build_init_request(self, local: dict[str, Any]) -> dict[str, Any]:
        """Build the LAN session-init request while normalizing protocol failures."""
        try:
            return self._protocol.build_init_request(local)
        except AionProtocolError as error:
            raise AionLocalError(str(error)) from error

    def _finalize_session(
        self,
        response_text: str,
        init_request: dict[str, Any],
    ) -> dict[str, Any]:
        """Finish the session handshake and translate private protocol failures."""
        try:
            return self._protocol.finalize_session(response_text, init_request)
        except AionProtocolError as error:
            raise AionLocalError(str(error)) from error

    def _parse_local_state_response(self, response_text: str) -> Any:
        """Parse a decrypted local-state payload while shielding HA callers from protocol errors."""
        try:
            return self._protocol.parse_local_state_response(response_text)
        except AionProtocolError as error:
            raise AionLocalError(str(error)) from error

    def _normalize_dict_payload(
        self,
        command_payload: Any,
        payload_type: str,
    ) -> dict[str, Any]:
        """Validate direct HA-facing payloads before they are routed into the protocol core."""
        if not isinstance(command_payload, dict):
            raise AionLocalError(f"{payload_type} payload must be a JSON object.")
        return command_payload

    def _get_local_info(self, descriptor: dict[str, Any]) -> dict[str, Any]:
        """Extract and validate the local connection details required for LAN execution."""
        local = descriptor.get("local", {})
        if not _REQUIRED_LOCAL_FIELDS.issubset(local.keys()):
            LOGGER.error(
                "AION local descriptor is missing connection details: entity_uid=%s keys=%s",
                descriptor.get("entity_uid"),
                sorted(local.keys()),
            )
            raise AionLocalError("Entity is missing local connection details.")
        return local

    async def _async_get_session(self, local: dict[str, Any]) -> dict[str, Any]:
        """Reuse a valid Z session when possible or perform a fresh init handshake."""
        cache_key = local["device_ssid"]
        current_session = self._session_cache.get(cache_key)
        if self._protocol.is_session_fresh(current_session, SESSION_TTL_MS):
            return current_session

        fresh_session = await self._async_init_session(local)
        self._session_cache[cache_key] = fresh_session
        return fresh_session

    async def _async_init_session(self, local: dict[str, Any]) -> dict[str, Any]:
        """Establish a fresh Z session using the device main key and init endpoint."""
        init_request = self._build_init_request(local)
        response_text = await self._async_send_request(local, init_request)
        try:
            return self._finalize_session(response_text, init_request)
        except AionLocalError as error:
            self._invalidate_session(local, str(error))
            raise

    async def _async_send_request(
        self,
        local: dict[str, Any],
        request: dict[str, Any],
    ) -> str:
        """Send a fully prepared protocol request through the shared transport path."""
        return await self._async_encrypted_get(
            local=local,
            endpoint=str(request["endpoint"]),
            plaintext=str(request["plaintext"]),
            encryption_key=str(request["encryption_key"]),
            decryption_key=str(request["decryption_key"]),
        )

    async def _async_encrypted_get(
        self,
        local: dict[str, Any],
        endpoint: str,
        plaintext: str,
        encryption_key: str,
        decryption_key: str,
    ) -> str:
        """Encrypt a GET payload, call the device, and decrypt the response envelope."""
        try:
            encrypted_request = self._protocol.build_encrypted_request(
                plaintext,
                encryption_key,
            )
        except AionProtocolError as error:
            raise AionLocalError(str(error)) from error

        url = (
            f"http://{local['device_ip']}/{local['device_ssid']}/{endpoint}"
            f"?d={encrypted_request['encoded_cipher']}&v={encrypted_request['iv_hex']}"
        )

        timeout = ClientTimeout(total=5)
        try:
            async with self._session.get(
                url,
                headers={
                    "Content-Type": "application/json",
                    "Connection": "close",
                },
                timeout=timeout,
            ) as response:
                raw_response = await response.text()
                if response.status < 200 or response.status >= 300:
                    try:
                        self._protocol.parse_encrypted_response(
                            raw_response,
                            decryption_key,
                        )
                    except AionProtocolError as error:
                        self._invalidate_session(local, str(error))
                    LOGGER.error(
                        "AION local request failed: status=%s endpoint=%s payload_length=%s",
                        response.status,
                        endpoint,
                        len(plaintext),
                    )
                    raise AionLocalError(f"Device request failed with HTTP {response.status}.")

                try:
                    return self._protocol.parse_encrypted_response(
                        raw_response,
                        decryption_key,
                    )
                except AionProtocolError as error:
                    self._invalidate_session(local, str(error))
                    raise AionLocalError(str(error)) from error
        except AionLocalError:
            raise
        except (ClientError, OSError) as error:
            # Treat any network-level failure as a clean device-unreachable error so
            # callers always see AionLocalError and never a raw aiohttp exception.
            raise AionLocalError(
                f"Device unreachable at {local.get('device_ip')}: {error}"
            ) from error

    def _build_primary_patch(
        self,
        descriptor: dict[str, Any],
        command_value: int | str,
    ) -> dict[str, Any] | None:
        """Build a best-effort optimistic state patch after a successful primary command."""
        platform = descriptor.get("platform")
        numeric_value: int | None
        try:
            numeric_value = int(command_value)
        except (TypeError, ValueError):
            numeric_value = None

        if platform == "switch":
            return {"is_on": numeric_value is not None and numeric_value > 0}

        if platform == "light":
            brightness = numeric_value if numeric_value is not None else 0
            return {
                "is_on": brightness > 0,
                "brightness_percent": brightness,
            }

        if platform == "cover" and numeric_value is not None:
            if numeric_value == 200 or command_value == "stop":
                return None
            return {"position": numeric_value, "is_closed": numeric_value == 0}

        if platform == "lock" and numeric_value is not None:
            return {"is_locked": numeric_value == 0}

        return None

    def _build_aux_patch(
        self,
        descriptor: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Update simple config entities optimistically after a successful aux write."""
        control = descriptor.get("control", {})
        field_value = self._extract_aux_payload_value(payload, control)
        if field_value is _MISSING:
            return None

        if descriptor.get("platform") == "number":
            return {"native_value": float(field_value)}
        if descriptor.get("platform") == "switch":
            return {"is_on": to_bool(field_value)}
        if descriptor.get("platform") == "select":
            option_map = control.get("option_map", {})
            reverse_option_map = {
                self._normalize_option_lookup_key(raw_value): label
                for label, raw_value in option_map.items()
            }
            return {
                "current_option": reverse_option_map.get(
                    self._normalize_option_lookup_key(field_value),
                    str(field_value),
                )
            }

        return None

    def _extract_aux_payload_value(
        self,
        payload: dict[str, Any],
        control: dict[str, Any],
    ) -> Any:
        """Resolve the written aux value from either a flat field or a nested payload path."""
        payload_path = control.get("payload_path")
        if isinstance(payload_path, list) and payload_path:
            nested_value: Any = payload
            for path_segment in payload_path:
                if not isinstance(nested_value, dict) or path_segment not in nested_value:
                    return _MISSING
                nested_value = nested_value[path_segment]
            return nested_value

        field_name = control.get("field")
        if field_name and field_name in payload:
            return payload[field_name]

        return _MISSING

    def _normalize_option_lookup_key(self, value: Any) -> str:
        """Normalize raw option values so optimistic select patches can map them back to labels."""
        if isinstance(value, str):
            return value.strip()
        return str(value)

    def _build_ac_patch(
        self,
        ac_state: dict[str, Any],
    ) -> dict[str, Any]:
        """Translate a merged AC state into the climate attributes used by HA."""
        is_on = to_bool(ac_state.get("p", "1"))
        # When p=0 the AC is off — reflect HVACMode.OFF regardless of the saved mode (m).
        hvac_mode = (
            "off"
            if not is_on
            else HVAC_MODE_MAP.get(str(ac_state.get("m", "1")), "cool")
        )
        return {
            "ac_state": ac_state,
            "hvac_mode": hvac_mode,
            "fan_mode": FAN_MODE_MAP.get(str(ac_state.get("f", "0")), "auto"),
            "target_temperature": float(ac_state.get("t", 24)),
            "is_on": is_on,
        }