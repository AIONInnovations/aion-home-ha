"""QR payload helpers used by the AION Home config flow."""

from __future__ import annotations

import base64
from io import BytesIO
import json

from .const import QR_PAYLOAD_VERSION, QR_PROVIDER


def build_pairing_payload(
    gateway_url: str,
    pairing_token: str,
    ha_id: str,
    instance_name: str,
) -> str:
    """Build the compact JSON payload expected by the mobile app scanner."""
    payload = {
        "t": "pair",
        "token": pairing_token,
        "ha_id": ha_id,
        "v": QR_PAYLOAD_VERSION,
        "provider": QR_PROVIDER,
        "gateway_url": gateway_url.rstrip("/"),
        "instance_name": instance_name,
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def render_pairing_qr_markdown(pairing_payload: str) -> str:
    """Render a markdown block that embeds the QR code without exposing raw secret data."""
    try:
        import qrcode
    except ImportError:
        # Keep config flow loadable even when the optional QR dependency is missing.
        # The pairing payload still renders as text, so the user can recover by
        # scanning it elsewhere or reinstalling the missing dependency.
        return (
            "QR rendering is currently unavailable, but the pairing payload is ready:\n\n"
            f"```json\n{pairing_payload}\n```\n\n"
            "Open the AION Home app, go to Profile > Assistants > Home Assistant, and "
            "continue pairing from there."
        )

    qr_code = qrcode.QRCode(border=2, box_size=6)
    qr_code.add_data(pairing_payload)
    qr_code.make(fit=True)

    image = qr_code.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded_image = base64.b64encode(buffer.getvalue()).decode("ascii")

    return (
        "In the AION Home app, open Profile > Assistants > Home Assistant.\n"
        "Tap Scan QR and scan this code.\n\n"
        f"![AION pairing QR](data:image/png;base64,{encoded_image})\n\n"
        "After the app shows success, return here and click Submit."
    )