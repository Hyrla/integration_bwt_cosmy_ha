# BWT Cosmy - Home Assistant
BWT Cosmy robot cleaner integration for Home Assistant through Bluetooth.

![Home Assistant Cosmy integration](image.png)

## Features
- Control your BWT Cosmy robot via Bluetooth
- On/Off switch entity
- Status reporting (On/Off, cleaning time remaining)
- UI-based setup (no YAML required)
- Multi-language config flow (English, French)
- Automatic discovery of the robot via Bluetooth

## Requirements
- Home Assistant 2023.6 or newer recommended
- Bluetooth adapter or proxy supported by your system

## Installation
1. Install [HACS](https://www.hacs.xyz/docs/use/download/download/) (if not already installed).
2. Add `https://github.com/Hyrla/integration_bwt_cosmy_ha` as a custom repository on HACS and search for "BWT Cosmy" integration to install it.
3. Go to **Settings > Devices & Services**, your BWT Cosmy robot should appear automatically on top of the page if the Bluetooth adapter is working and in range.
4. If it doesn't appear, you can manually add it by clicking on **Add Integration** and searching for "BWT Cosmy". Enter the robot's Bluetooth MAC address (e.g. `48:70:1E:67:3E:55`) and a name for the device.

## Usage
- Use the switch entity to turn the robot ON or OFF.
- The entity will show the remaining cleaning time.

## Troubleshooting
- Make sure your Bluetooth adapter is working and accessible to Home Assistant.
- The robot's station must be powered and in range. **The Cosmy Bluetooth antenna is really really weak**.
- If you have issues, check the Home Assistant logs for errors from `bwt_cosmy`. (``cat home-assistant.log | grep bwt_cosmy``)

## Links
- [GitHub](https://github.com/Hyrla/integration_bwt_cosmy_ha)
- [Issue Tracker](https://github.com/Hyrla/integration_bwt_cosmy_ha/issues)

## Supported Robot Models
- BWT Cosmy 100
- Other (if you have a different model, please report it) *Cosmy 150 and 200 may work, but I don't have them to test*

## AI usage disclaimer
This integration was developed with the help of AI tools.

*Edit: it was 100% vibe coded*