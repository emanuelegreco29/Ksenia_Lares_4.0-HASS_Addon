# Ksenia Lares 4.0 Integration for Home Assistant

![GitHub last commit](https://img.shields.io/github/last-commit/emanuelegreco29/Ksenia_Lares_4.0-HASS_Addon)
![GitHub License](https://img.shields.io/github/license/emanuelegreco29/Ksenia_Lares_4.0-HASS_Addon)

This **unofficial** integration allows you to connect your HomeAssistant to the [Ksenia Lares 4.0](https://www.kseniasecurity.com/en/insights/control-panel-ksenia-lares-4-0-the-most-complete-iot-platform-for-home-automation.html) control panel and add all your devices.

## Compatible Devices
| Device | Compatibility |
|:-----------------------|:------------------------------------:|
| Lights | ✅ |
| Roller Blinds | ✅ |
| Window Shutters | ✅ |
| Buttons | ⚠️ |
| Switches | ✅ |
| Scenarios | ⚠️ |
| Sensors | ✅ |

#### Legend
⛔ - Not Compatible; ⚠️ - Work In Progress; ✅ - Compatible

#### ⚠️ Warning ⚠️
If any of the devices listed is not compatible, or if some devices listed as "compatible" are not working as intended, please open an issue. Collaboration is more than welcome, if somebody wants to implement new functions or contribute in any form to the integration, feel free to send a pull request.

## Installation
To install, simply clone this repository or download it locally. Then, add the 'ksenia_lares' folder to your 'custom_components' folder and restart HomeAssistant.
Proceed to add the integration as you would with any other integration.

![Screenshot from 2025-03-01 14-09-38](https://github.com/user-attachments/assets/280f2f83-8de6-43a8-ae22-8c3f094ad219)

When prompted, insert:
- The (local) IP address of your Ksenia Control Panel
- The user PIN to access the Ksenia Control Panel. I highly encourage you to use a user PIN, **without admin permissions** and (if you wish) without access to the home security system
- Check the "SSL" box if you want HomeAssistant to communicate using a **secure connection**. In case of network error, and only in that case, un-check the box
- Check all the devices that you want to add to HomeAssistant (by default, the integration will scan for all compatible devices)

![Screenshot from 2025-03-01 14-09-54](https://github.com/user-attachments/assets/0fabd464-99ef-4953-bbf1-131e50402b25)

## Credits
Big thanks to [@gvisconti1983](https://github.com/gvisconti1983) for the crc functions and to [@realnot16](https://github.com/realnot16) for the WebSocket library, which has been reworked and updated by me.
