# BWT Cosmy - Home Assistant
BWT Cosmy robot cleaner integration for Home Assistant through Bluetooth.

## Features
- Control your BWT Cosmy robot via Bluetooth (BLE)
- On/Off switch entity
- Status reporting (ON/OFF, cleaning time remaining)
- UI-based setup (no YAML required)
- Multi-language config flow (English, French)

## Requirements
- Home Assistant 2023.6 or newer recommended
- Bluetooth adapter or proxy supported by your system

## Manuel installation
1. Copy the `custom_components/bwt_cosmy` folder to your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Go to **Settings > Devices & Services > Add Integration** and search for "BWT Cosmy".
4. Enter your Cosmy BLE address (e.g. `AA:BB:CC:DD:EE:FF`) and (optionally) a timeout.
5. The Cosmy switch entity will appear in Home Assistant.

## Usage
- Use the switch entity to turn the robot ON or OFF.
- The entity will show the remaining cleaning time (if available).
- You can change the timeout via the integration options.

## Troubleshooting
- Make sure your Bluetooth adapter is working and accessible to Home Assistant.
- The robot must be powered and in range.
- If you have issues, check the Home Assistant logs for errors from `bwt_cosmy`.

## Links
- [GitHub](https://github.com/Hyrla/integration_bwt_cosmy_ha)
- [Issue Tracker](https://github.com/Hyrla/integration_bwt_cosmy_ha/issues)

## AI usage disclaimer
This integration was developed with the help of AI tools.