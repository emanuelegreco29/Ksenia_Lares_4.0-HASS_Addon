"""Light entities for Ksenia Lares integration."""

import asyncio
import logging
import time
from contextlib import suppress

from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_FLASH, LightEntity
from homeassistant.components.light.const import ColorMode, LightEntityFeature
from homeassistant.util.color import brightness_to_value, value_to_brightness

from .const import DOMAIN
from .helpers import KseniaEntity, build_unique_id, get_entity_name

_LOGGER = logging.getLogger(__name__)

BRIGHTNESS_SCALE = (1, 100)

FLASH_DURATIONS = {
    "short": 0.5,
    "long": 2.0,
}


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Ksenia Lares light entities.

    Creates light entities for all outputs configured as lights.
    Supports on/off control, brightness and flashing.
    """
    try:
        ws_manager = hass.data[DOMAIN][config_entry.entry_id]["ws_manager"]
        device_info = hass.data[DOMAIN][config_entry.entry_id].get("device_info")
        base_id = hass.data[DOMAIN][config_entry.entry_id].get("mac") or ws_manager.ip

        lights = await ws_manager.getLights()
        _LOGGER.debug("Found %d lights", len(lights))

        entities = [KseniaLightEntity(ws_manager, light, device_info, base_id) for light in lights]
        async_add_entities(entities, update_before_add=True)

        # Track discovered light IDs and set up listener-based discovery
        discovered_light_ids = {e._id for e in entities}

        async def discover_via_lights_listener(data_list):
            """Listener-based discovery for lights.

            Calls getLights() which already filters by CAT==LIGHT and merges state.
            """
            try:
                # Get complete list of lights (already filtered and merged with state)
                lights = await ws_manager.getLights()

                new_entities = []
                for light in lights:
                    light_id = light.get("ID")
                    if light_id not in discovered_light_ids:
                        new_entities.append(
                            KseniaLightEntity(ws_manager, light, device_info, base_id)
                        )
                        discovered_light_ids.add(light_id)

                if new_entities:
                    _LOGGER.info(f"Discovery found {len(new_entities)} new light(s)")
                    async_add_entities(new_entities, update_before_add=True)
            except Exception as e:
                _LOGGER.debug(f"Error during light discovery: {e}")

        # Register discovery listener
        ws_manager.register_listener("lights", discover_via_lights_listener)

    except Exception as e:
        _LOGGER.error("Error setting up lights: %s", e, exc_info=True)


class KseniaLightEntity(KseniaEntity, LightEntity):
    """Light entity for Ksenia Lares system."""

    _attr_has_entity_name = True
    _attr_supported_features = LightEntityFeature.FLASH

    def __init__(self, ws_manager, light_data, device_info=None, base_id=None):
        self.ws_manager = ws_manager
        self._id = light_data.get("ID")
        self._base_id = base_id or ws_manager.ip
        _LOGGER.debug("Initializing KseniaLightEntity with data: %s", light_data)
        # Use the name given by Ksenia, otherwise "Light <ID>"
        self._attr_name = get_entity_name(light_data, self._id, f"Light {self._id}")
        # Determine if the light is dimmable based on the "MOD" field
        self._is_dimmable = light_data.get("MOD") == "AN"
        self._state = light_data.get("STA", "off").lower() == "on"
        self._pending_command = None
        self._device_info = device_info
        # Task used for an active flash.
        self._flash_task = None
        # Store complete raw data for debugging and transparency
        self._raw_data = dict(light_data)

    async def async_added_to_hass(self):
        """Subscribe to realtime light updates."""
        await super().async_added_to_hass()
        self.ws_manager.register_listener("lights", self._handle_realtime_update)

    async def async_will_remove_from_hass(self):
        """Cancel active flash when the entity is removed."""
        await self._cancel_flash()
        await super().async_will_remove_from_hass()

    async def _cancel_flash(self):
        """Cancel any active flash operation."""
        if self._flash_task is None:
            return
        task = self._flash_task
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._flash_task = None

    async def _handle_realtime_update(self, data_list):
        """Process realtime STATUS_OUTPUTS updates for this light."""
        for data in data_list:
            if data.get("ID") != self._id:
                continue

            _LOGGER.debug("[light] Entity %s update: %s", self._id, data)
            if "STA" not in data:
                self._raw_data.update(data)
                self.async_write_ha_state()
                break
            remote_state = data["STA"].lower() == "on"
            # If there's a recent pending command, keep the local state.
            if self._pending_command is not None:
                _, timestamp = self._pending_command
                if time.time() - timestamp < 2:
                    return
                self._pending_command = None
            self._state = remote_state
            self._raw_data.update(data)
            self.async_write_ha_state()

    @property
    def unique_id(self):
        """Returns a unique ID for the light."""
        return build_unique_id(self._base_id, "light", self._id)

    @property
    def is_on(self):
        """Returns True if the light is on."""
        return self._state

    @property
    def supported_color_modes(self):
        """Returns the supported color modes of the light
        (BRIGHTNESS and ONOFF if dimmable, only ONOFF otherwise)."""
        if self._is_dimmable:
            return {ColorMode.BRIGHTNESS}

        return {ColorMode.ONOFF}

    @property
    def color_mode(self):
        """Returns the color mode of the light
        (BRIGHTNESS if dimmable, ONOFF otherwise)."""
        if self._is_dimmable:
            return ColorMode.BRIGHTNESS

        return ColorMode.ONOFF

    @property
    def brightness(self):
        """Returns the brightness of the light (0-255) if dimmable,
        None otherwise."""
        if not self._is_dimmable:
            return None
        try:
            pos = int(self._raw_data.get("POS", 0))
        except (TypeError, ValueError):
            return None
        return value_to_brightness(BRIGHTNESS_SCALE, pos)

    @property
    def extra_state_attributes(self):
        """Return the extra state attributes of the light."""
        return {"raw_data": self._raw_data}

    async def async_turn_on(self, **kwargs):
        """Turn on the light, optionally flashing it."""
        if not self.ws_manager.available:
            _LOGGER.error("WebSocket not connected, cannot turn on light %s", self._id)
            return

        if ATTR_FLASH in kwargs and kwargs.get(ATTR_FLASH) is not None:
            await self._start_flash(kwargs.get(ATTR_FLASH, "short"))
            return

        # A normal turn_on command supersedes an active flash.
        await self._cancel_flash()

        # Handle brightness if provided and the light is dimmable.
        if ATTR_BRIGHTNESS in kwargs and self._is_dimmable:
            level = round(brightness_to_value(BRIGHTNESS_SCALE, kwargs[ATTR_BRIGHTNESS]))
            await self.ws_manager.turnOnOutput(self._id, brightness=level)
            self._raw_data["POS"] = str(level)
        else:  # Otherwise just turn it on
            await self.ws_manager.turnOnOutput(self._id)

        self._state = True
        self._pending_command = ("on", time.time())
        self.async_write_ha_state()

    async def _start_flash(self, flash="short"):
        """Start a flash, cancelling any existing flash."""
        duration = FLASH_DURATIONS.get(flash)

        if duration is None:
            _LOGGER.warning("Unsupported flash mode %r for light %s", flash, self._id)
            return

        # If another flash is running, cancel it first.
        await self._cancel_flash()
        self._flash_task = asyncio.create_task(self._async_flash(duration, flash))
        try:
            await self._flash_task
        except asyncio.CancelledError:
            # Cancellation is expected when another command supersedes
            # the flash.
            _LOGGER.debug("Flash cancelled for light %s", self._id)
        finally:
            if self._flash_task is asyncio.current_task():
                self._flash_task = None

    async def _async_flash(self, duration, flash="short"):
        """Flash the light and restore its previous state."""
        previous_state = self._state
        previous_level = None
        if self._is_dimmable:
            try:
                previous_level = int(self._raw_data.get("POS", 0))
            except (TypeError, ValueError):
                previous_level = None

        _LOGGER.debug(
            "Starting %s flash for light %s: duration=%.1fs, previous_state=%s, previous_brightness=%s",
            flash,
            self._id,
            duration,
            previous_state,
            previous_level,
        )
        with suppress(asyncio.CancelledError):
            if self._is_dimmable:
                # Make the flash visible by temporarily going to 100%.
                await self.ws_manager.turnOnOutput(self._id, brightness=BRIGHTNESS_SCALE[1])
                self._raw_data["POS"] = str(BRIGHTNESS_SCALE[1])
            else:
                await self.ws_manager.turnOnOutput(self._id)
            self._state = True
            self.async_write_ha_state()
            await asyncio.sleep(duration)
        # The flash completed normally, so restore the original state.
        if previous_state:
            if self._is_dimmable and previous_level is not None:
                await self.ws_manager.turnOnOutput(self._id, brightness=previous_level)
                self._raw_data["POS"] = str(previous_level)
            else:
                await self.ws_manager.turnOnOutput(self._id)
            self._state = True
            self._pending_command = (
                "on",
                time.time(),
            )
        else:
            await self.ws_manager.turnOffOutput(self._id)
            self._state = False
            self._pending_command = ("off", time.time())

            # Keep the previous brightness in the raw state.
            # This is important because an OFF dimmable light can still
            # have a remembered brightness.
            if self._is_dimmable and previous_level is not None:
                self._raw_data["POS"] = str(previous_level)
        self.async_write_ha_state()
        _LOGGER.debug("Completed %s flash for light %s", flash, self._id)

    async def async_turn_off(self, **kwargs):
        """Turn off the light."""
        if not self.ws_manager.available:
            _LOGGER.error("WebSocket not connected, cannot turn off light %s", self._id)
            return

        # A normal turn_off command supersedes an active flash.
        await self._cancel_flash()
        await self.ws_manager.turnOffOutput(self._id)
        self._state = False
        self._pending_command = ("off", time.time())
        self.async_write_ha_state()
