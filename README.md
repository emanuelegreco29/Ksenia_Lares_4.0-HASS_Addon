# Ksenia Lares 4.0 Integration for Home Assistant

![GitHub last commit](https://img.shields.io/github/last-commit/emanuelegreco29/Ksenia_Lares_4.0-HASS_Addon)
![License Badge](https://img.shields.io/badge/license-Creative%20Commons-green)


<a href="https://www.buymeacoffee.com/lelegreco29" target="_blank">
    <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 50px !important;width: 200px !important;">
</a>

This **unofficial** integration allows you to connect your HomeAssistant to the [Ksenia Lares 4.0](https://www.kseniasecurity.com/en/insights/control-panel-ksenia-lares-4-0-the-most-complete-iot-platform-for-home-automation.html) control panel and add all your devices. I am **NOT** affiliated with Ksenia in any way, this integration was made for personal use only.

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
| Scenarios | ⚠️ |
| Sensors | ⚠️ (see below) |
| Partitions | ⚠️ |

#### Legend
⛔ - Not Implemented; ⚠️ - Work In Progress; ✅ - Implemented

### Compatible Sensors
- DOMUS (environmental)
- Power Lines
- Alarm System
- Zone-based:
    - Door
    - Window
    - Magnetic Contact (PMC)
    - Internal Movement

#### ⚠️ Warning ⚠️
If any of the devices listed is not compatible, or if some devices listed as "compatible" are not working as intended, please open an issue. Collaboration is more than welcome, if somebody wants to implement new functions or contribute in any form to the integration, feel free to send a pull request.

## Installation
### 1. HACS installation (best method)
#### Automatic Installation via HACS
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=emanuelegreco29&repository=Ksenia_Lares_4.0-HASS_Addonl&category=integration)

[![Add Integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=ksenia_lares)

#### Manual Installation via HACS
1. Make sure you have installed HACS to Home Assistant: [HACS install guide](https://hacs.xyz/docs/setup/download).
2. Open HACS, click **Custom repositories** in the top-right menu, Repository input: `https://github.com/emanuelegreco29/Ksenia_Lares_4.0-HASS_Addon`, Category select **Integration**.
   
![archivi](https://github.com/user-attachments/assets/b75f74d5-2f1d-45b5-9a94-d8db81f7f821)
![intg](https://github.com/user-attachments/assets/c5f591b5-19a1-49bf-8b91-041dbe1642dd)

3. **Restart Home Assistant**.
4. You can now search for `Ksenia Lares 4.0` in HACS and install through there.

![kkk](https://github.com/user-attachments/assets/bc088136-22f5-4b11-b903-2c9719617360)

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

![jklkljkl](https://github.com/user-attachments/assets/6e3cf343-bf33-4c72-9523-4f04dc99f18e)

## Credits
Big thanks to [@gvisconti1983](https://github.com/gvisconti1983) for the crc functions and to [@realnot16](https://github.com/realnot16) for the WebSocket library, which has been reworked and updated by me.
