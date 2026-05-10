# AION Home

Control AION devices from Home Assistant using the AION custom integration.

This integration provides local device control and Home Assistant-native entities for supported AION hardware.

## Setup

1. Install the repository through HACS as a custom integration.
2. Restart Home Assistant after installation.
3. Open **Settings -> Devices & Services**.
4. Click **Add Integration** and select **AION Home**.
5. Follow the on-screen setup flow.

## Transparency

Note: The Home Assistant integration layer is fully open-source, while the core LAN cryptography (_aion_protocol.py) is obfuscated to protect proprietary hardware IP.