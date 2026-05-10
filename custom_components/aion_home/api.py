"""Gateway API client for pairing exchange and bootstrap sync."""

from __future__ import annotations

from typing import Any
import logging

from aiohttp import ClientSession, ClientTimeout
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_HA_ACCESS_TOKEN,
    HEADER_GATEWAY_API_KEY,
    PAIR_EXCHANGE_PATH,
    SYNC_BOOTSTRAP_PATH,
)

LOGGER = logging.getLogger(__name__)


class AionGatewayError(HomeAssistantError):
    """Represent a non-authentication failure returned by the AION gateway."""


class AionGatewayAuthError(AionGatewayError):
    """Represent revoked, expired, or invalid gateway credentials."""


class AionGatewayPairingError(AionGatewayError):
    """Represent a pairing-specific 4xx error with a machine-readable code."""

    # Codes that trigger a retryable same-QR error in the config flow.
    RETRYABLE_CODES = frozenset({"link_not_found", "pairing_missing_usid"})
    # Codes that require a fresh QR because the token has already been consumed.
    CONSUMED_CODE = "pairing_consumed"

    def __init__(self, code: str) -> None:
        """Store the machine-readable error code returned by the gateway."""
        super().__init__(code)
        self.code = code


class AionGatewayApi:
    """Wrap the HTTP contract used by the custom integration and the gateway."""

    def __init__(
        self,
        session: ClientSession,
        gateway_url: str,
        gateway_api_key: str,
        ha_access_token: str | None = None,
    ) -> None:
        """Store the gateway credentials used for future requests."""
        self._session = session
        self._gateway_url = gateway_url.rstrip("/")
        self._gateway_api_key = gateway_api_key
        self._ha_access_token = ha_access_token

    @property
    def gateway_url(self) -> str:
        """Expose the configured gateway base URL."""
        return self._gateway_url

    @property
    def gateway_api_key(self) -> str:
        """Expose the configured API Gateway key required by the gateway."""
        return self._gateway_api_key

    @property
    def ha_access_token(self) -> str | None:
        """Expose the long-lived Home Assistant access token issued by the gateway."""
        return self._ha_access_token

    def update_access_token(self, ha_access_token: str) -> None:
        """Persist a freshly exchanged Home Assistant access token in memory."""
        self._ha_access_token = ha_access_token

    def _build_request_url(self, path: str) -> str:
        """Resolve both the fixed sync endpoint URL and legacy base URLs into a request URL."""
        if self._gateway_url.endswith(SYNC_BOOTSTRAP_PATH):
            return f"{self._gateway_url[: -len(SYNC_BOOTSTRAP_PATH)]}{path}"

        if self._gateway_url.endswith(PAIR_EXCHANGE_PATH):
            return f"{self._gateway_url[: -len(PAIR_EXCHANGE_PATH)]}{path}"

        return f"{self._gateway_url}{path}"

    async def async_exchange_pairing(
        self,
        pairing_token: str,
        ha_id: str,
        instance_name: str,
        machine_type: str = "unknown",
    ) -> dict[str, Any]:
        """Exchange an app-created pairing record for a long-lived gateway token."""
        return await self._async_request(
            method="POST",
            path=PAIR_EXCHANGE_PATH,
            body={
                "pairing_token": pairing_token,
                "ha_id": ha_id,
                "instance_name": instance_name,
                "machine_type": machine_type,
            },
        )

    async def async_fetch_bootstrap(self) -> dict[str, Any]:
        """Fetch the latest normalized entity snapshot from the gateway."""
        if not self._ha_access_token:
            raise AionGatewayAuthError("Home Assistant access token is missing.")

        return await self._async_request(
            method="GET",
            path=SYNC_BOOTSTRAP_PATH,
            bearer_token=self._ha_access_token,
        )

    async def _async_request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        bearer_token: str | None = None,
    ) -> dict[str, Any]:
        """Send a gateway request and normalize HTTP failures into HA exceptions."""
        headers = {
            HEADER_GATEWAY_API_KEY: self._gateway_api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        if bearer_token:
            headers["x-aion-auth"] = f"Bearer {bearer_token}"

        url = self._build_request_url(path)
        timeout = ClientTimeout(total=15)

        async with self._session.request(
            method=method,
            url=url,
            json=body,
            headers=headers,
            timeout=timeout,
        ) as response:
            if response.status >= 400:
                # Try to parse a machine-readable error code from the JSON body.
                # The gateway returns { "error": { "code": "...", "message": "..." } }
                error_code: str | None = None
                error_message: str | None = None
                try:
                    error_body = await response.json(content_type=None)
                    if isinstance(error_body, dict):
                        error_payload = error_body.get("error", {})
                        if isinstance(error_payload, dict):
                            error_code = error_payload.get("code")
                            error_message = error_payload.get("message")
                except Exception:  # noqa: BLE001 — JSON parse is best-effort
                    pass

                LOGGER.error(
                    "AION gateway request failed: method=%s path=%s status=%s code=%s message=%s",
                    method,
                    path,
                    response.status,
                    error_code or "unknown",
                    error_message or "unknown",
                )

                # Pairing-specific codes surface as AionGatewayPairingError so
                # the config flow can distinguish retryable vs consumed states.
                if error_code in (
                    AionGatewayPairingError.CONSUMED_CODE,
                    *AionGatewayPairingError.RETRYABLE_CODES,
                    "pairing_ha_mismatch",
                    "link_ha_mismatch", 
                ):
                    raise AionGatewayPairingError(error_code)

                if response.status in {401, 403, 410}:
                    raise AionGatewayAuthError(error_code or str(response.status))

                raise AionGatewayError(error_code or str(response.status))

            payload = await response.json(content_type=None)
            if not isinstance(payload, dict):
                LOGGER.error(
                    "AION gateway request returned a non-object payload: method=%s path=%s payload_type=%s",
                    method,
                    path,
                    type(payload).__name__,
                )
                raise AionGatewayError("Gateway response must be a JSON object.")
            return payload