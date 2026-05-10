"""Helper utilities for AION Home entity normalization and state mapping."""

from __future__ import annotations

from typing import Any
import re


def slugify_value(value: str) -> str:
    """Convert a free-form label into a stable slug used in entity ids."""
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    return normalized.strip("_") or "aion"


def gateway_url_join(base_url: str, path: str) -> str:
    """Join the configured gateway base URL with a fixed API path."""
    return f"{base_url.rstrip('/')}{path}"


def to_bool(value: Any) -> bool:
    """Map the app's mixed string and numeric state values to a boolean."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "on", "open", "yes"}


def normalize_percent(value: Any, default: int = 0) -> int:
    """Normalize a raw percentage-like value into the inclusive 0-100 range."""
    try:
        numeric_value = int(float(value))
    except (TypeError, ValueError):
        numeric_value = default
    return max(0, min(100, numeric_value))


def percent_to_brightness(value: Any) -> int:
    """Convert an AION 0-100 brightness value into a Home Assistant 0-255 value."""
    percent = normalize_percent(value)
    return round((percent / 100) * 255)


def brightness_to_percent(value: Any) -> int:
    """Convert a Home Assistant brightness value into an AION 0-100 value."""
    try:
        brightness = int(value)
    except (TypeError, ValueError):
        brightness = 0
    brightness = max(0, min(255, brightness))
    return round((brightness / 255) * 100)


def reverse_lookup(mapping: dict[str, str], target_value: str, default: str) -> str:
    """Resolve the protocol code that corresponds to a Home Assistant enum value."""
    for code, mapped_value in mapping.items():
        if mapped_value == target_value:
            return code
    return default


def merge_dict(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge a patch into a base dictionary while preserving nested keys."""
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def maybe_json_text(value: Any) -> str:
    """Convert a raw object into a stable string for diagnostic sensor state."""
    if isinstance(value, str):
        return value
    return str(value)