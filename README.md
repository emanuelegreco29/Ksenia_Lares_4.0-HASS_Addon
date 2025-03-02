# Ksenia Lares 4.0 Integration for Home Assistant

![GitHub last commit](https://img.shields.io/github/last-commit/emanuelegreco29/Ksenia_Lares_4.0-HASS_Addon)
![License Badge](https://img.shields.io/badge/license-Creative%20Commons-green)


<a href="https://www.buymeacoffee.com/lelegreco29" target="_blank">
    <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 50px !important;width: 200px !important;">
</a>

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
### 1. HACS installation (best method)
1. Make sure you have installed HACS to Home Assistant: [HACS install guide](https://hacs.xyz/docs/setup/download).
2. Open HACS, click **Custom repositories** in the top-right menu, Repository input: `https://github.com/emanuelegreco29/Ksenia_Lares_4.0-HASS_Addon`, Category select **Integration**.
3. **Restart Home Assistant**.
4. You can now search for `Ksenia Lares 4.0` in HACS and install through there.

### 2. Manual installation
To install, simply clone this repository or download it locally. Then, add the `ksenia_lares` folder to your `custom_components` folder and restart HomeAssistant.
Proceed to add the integration as you would with any other integration.

## Setup

![Screenshot from 2025-03-01 14-09-38](https://github.com/user-attachments/assets/280f2f83-8de6-43a8-ae22-8c3f094ad219)

When prompted, insert:
- The (local) IP address of your Ksenia Control Panel
- The user PIN to access the Ksenia Control Panel. I highly encourage you to use a user PIN, **without admin permissions** and (if you wish) without access to the home security system
- Check the "SSL" box if you want HomeAssistant to communicate using a **secure connection**. In case of network error, and only in that case, un-check the box
- Check all the devices that you want to add to HomeAssistant (by default, the integration will scan for all compatible devices)

![Screenshot from 2025-03-01 14-09-54](https://github.com/user-attachments/assets/0fabd464-99ef-4953-bbf1-131e50402b25)

## Credits
Big thanks to [@gvisconti1983](https://github.com/gvisconti1983) for the crc functions and to [@realnot16](https://github.com/realnot16) for the WebSocket library, which has been reworked and updated by me.
