# AION Home Home Assistant Integration

Home Assistant custom integration for controlling AION devices over LAN.

## Repository Structure

```text
aion-home-ha/
├── custom_components/
│   └── aion_home/
│       ├── __init__.py
│       ├── manifest.json
│       ├── local_api.py
│       ├── _aion_protocol.py
│       └── ...
├── hacs.json
├── info.md
└── README.md
```

## Quick Setup

1. Copy `custom_components/aion_home` into your Home Assistant config folder:

	```text
	/config/custom_components/aion_home
	```

2. Restart Home Assistant.
3. Go to **Settings -> Devices & Services -> Add Integration**.
4. Search for **AION Home** and complete the config flow.

## HACS

This repository is structured for HACS custom repository installation with `hacs.json` and `info.md` at the repository root.

## Transparency

Note: The Home Assistant integration layer is fully open-source, while the core LAN cryptography (`_aion_protocol.py`) is obfuscated to protect proprietary hardware IP.