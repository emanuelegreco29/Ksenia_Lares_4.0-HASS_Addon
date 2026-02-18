# Ksenia Lares 4.0 Integration for Home Assistant

![GitHub last commit](https://img.shields.io/github/last-commit/emanuelegreco29/Ksenia_Lares_4.0-HASS_Addon)
![License Badge](https://img.shields.io/badge/license-Creative%20Commons-green)


<a href="https://www.buymeacoffee.com/lelegreco29" target="_blank">
    <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 50px !important;width: 200px !important;">
</a>

This **unofficial** integration allows you to connect your HomeAssistant to the [Ksenia Lares 4.0](https://www.kseniasecurity.com/en/insights/control-panel-ksenia-lares-4-0-the-most-complete-iot-platform-for-home-automation.html) control panel and add all your devices. This integration, me or any contributor, are **NOT** affiliated with Ksenia Security S.p.A in any way.

## Compatible Devices
| Device | Compatibility |
|:-----------------------|:------------------------------------:|
| Alarm System | ✅ |
| Lights | ✅ |
| Roller Blinds | ✅ |
| Window Shutters | ✅ |
| Garage Shutters | ✅ |
| Buttons | ✅ |
| Switches | ✅ |
| Scenarios | ✅ |
| Sensors | ⚠️ (see below) |
| Partitions | ✅ |

#### Legend
⛔ - Not Implemented; ⚠️ - Work In Progress; ✅ - Implemented

#### ⚠️ Warning ⚠️
If any of the devices listed is not compatible, or if some devices listed as "compatible" are not working as intended, please open an issue. Collaboration is more than welcome, if somebody wants to implement new functions or contribute in any form to the integration, feel free to open a pull request.

## Installation
### HACS installation
Make sure to have [HACS](https://www.hacs.xyz/docs/use/download/download/) installed on your Home Assistant.
#### Automatic Installation via HACS

[![Add Integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=ksenia_lares)

Simply click the button above, you will be redirected to HomeAssistant. Then you can proceed with setup.

## Setup
When setting up the integration, you will be greeted with this setup page:

<img width="610" height="690" alt="flow" src="https://github.com/user-attachments/assets/f57a9052-d5e8-49e3-9892-27d93fba6b2d" />

When prompted, insert:
- The local IP address of your Ksenia Control Panel
- The user PIN to access the Ksenia Control Panel. I highly encourage you to use a user PIN, **without admin permissions** and (if you wish) without access to the home security system. Alternatively, you can create a **dedicated user** for HomeAssistant
- Tick the "SSL" box if you want HomeAssistant to communicate using a **secure connection**. In case of network error, and only in that case, un-check the box
- Check all the devices that you want to add to HomeAssistant (by default, the integration will scan for all compatible devices)

After the integration finds all the entities, you should be able to see it in your Integrations page:

<img width="1032" height="331" alt="image" src="https://github.com/user-attachments/assets/3312aa50-440b-4f88-a6e2-83fca844b607" />

## Troubleshooting

### Download Diagnostics

The easiest way to get a complete snapshot of your integration's state:

1. Go to **Settings** > **Devices & Services**
2. Find the **Ksenia Lares 4.0** integration and click on it
3. Click on the device (e.g., "Ksenia Lares")
4. Click the **three dots** (⋮) in the top right corner
5. Select **Download diagnostics**

This downloads a JSON file containing:
- All entities with their current states and attributes (including `raw_data`)
- WebSocket connection status
- System information from your Ksenia panel
- Complete data for all device types
- Configuration settings

This file is perfect for sharing when reporting issues, as it contains everything needed to understand your setup without exposing sensitive credentials.

### Enable Debug Logging

For real-time troubleshooting and to capture dynamic behavior:

1. Go to **Settings** > **Devices & Services**
2. Find the **Ksenia Lares 4.0** integration
3. Click the **three dots** (⋮) in the top right corner
4. Select **Enable debug logging**
5. Reproduce the issue
6. Click the three dots again and select **Disable debug logging**
7. Download the logs to share when reporting issues

Debug logs will show detailed WebSocket communication, including:
- All incoming/outgoing messages
- Initial data acquisition
- Status updates for all device types
- Command responses

This information is helpful when reporting issues or troubleshooting connection problems.

## Credits
Big thanks to [@gvisconti1983](https://github.com/gvisconti1983) for the crc functions and to [@realnot16](https://github.com/realnot16) for the WebSocket library, which has been reworked and updated by me.
