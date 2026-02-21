"""Switch entities for Ksenia Lares integration."""

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory

from .const import DOMAIN
from .websocketmanager import ConnectionState

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Ksenia Lares switch entities.

    Creates switches for:
    - Outputs (generic switches, sirens disabled by default)
    - Zone bypass controls (for zones that support bypass)
    """
    try:
        ws_manager = hass.data[DOMAIN]["ws_manager"]
        device_info = hass.data[DOMAIN].get("device_info")
        entities = []

        # Add output switches
        output_count = len(entities)
        await _add_output_switches(ws_manager, device_info, entities)
        initial_output_count = len(entities) - output_count

        # Add zone bypass switches
        await _add_zone_bypass_switches(ws_manager, device_info, entities)

        async_add_entities(entities, update_before_add=True)
        _LOGGER.info(f"Initial switch setup: {initial_output_count} output switches")

        # Track discovered switch IDs and set up listener-based discovery
        # Only track switch_id from KseniaSwitchEntity objects, not zone bypass switches
        discovered_switch_ids = {e.switch_id for e in entities if hasattr(e, "switch_id")}

        async def discover_via_switches_listener(data_list):
            """Listener-based discovery for switches.

            Calls getSwitches() which already filters by CAT!=LIGHT and merges state.
            """
            try:
                # Get complete list of switches (already filtered and merged with state)
                switches = await ws_manager.getSwitches()

                new_entities = []
                for switch in switches:
                    switch_id = switch.get("ID")
                    if switch_id not in discovered_switch_ids:
                        name = (
                            switch.get("DES")
                            or switch.get("LBL")
                            or switch.get("NM")
                            or f"Switch {switch_id}"
                        )
                        new_entities.append(
                            KseniaSwitchEntity(ws_manager, switch_id, name, switch, device_info)
                        )
                        discovered_switch_ids.add(switch_id)

                if new_entities:
                    _LOGGER.info(f"Discovery found {len(new_entities)} new switch(es)")
                    await async_add_entities(new_entities, update_before_add=True)
            except Exception as e:
                _LOGGER.debug(f"Error during switch discovery: {e}")

        # Register discovery listener
        ws_manager.register_listener("switches", discover_via_switches_listener)

    except Exception as e:
        _LOGGER.error("Error setting up switches: %s", e, exc_info=True)


async def _add_output_switches(ws_manager, device_info, entities):
    """Add output switches (lights, sirens, etc.)."""
    switches = await ws_manager.getSwitches()
    _LOGGER.debug("Found %d output switches", len(switches))

    for switch in switches:
        switch_id = switch.get("ID")
        name = switch.get("DES") or switch.get("LBL") or switch.get("NM") or f"Switch {switch_id}"
        entities.append(KseniaSwitchEntity(ws_manager, switch_id, name, switch, device_info))


async def _add_zone_bypass_switches(ws_manager, device_info, entities):
    """Add zone bypass control switches."""
    zones = await ws_manager.getSensor("ZONES")
    bypass_zones = [z for z in zones if z.get("BYP_EN") == "T"]
    _LOGGER.debug("Found %d zones with bypass enabled", len(bypass_zones))

    for zone in bypass_zones:
        zone_id = zone.get("ID")
        zone_name = zone.get("DES") or zone.get("LBL") or zone.get("NM") or f"Zone {zone_id}"
        entities.append(KseniaZoneBypassSwitch(ws_manager, zone_id, zone_name, zone, device_info))


class KseniaSwitchEntity(SwitchEntity):
    """Switch entity for Ksenia outputs."""

    def __init__(self, ws_manager, switch_id, name, switch_data, device_info=None):
        self.ws_manager = ws_manager
        self.switch_id = switch_id
        self._name = name
        self._state = switch_data.get("STA", "off").lower() == "on"
        self._available = True
        self._device_info = device_info
        # Disable siren switch by default for safety
        self._attr_entity_registry_enabled_default = not (
            "siren" in name.lower() or "sirena" in name.lower()
        )
        # Store complete raw data for debugging and transparency
        self._raw_data = dict(switch_data)

    async def async_added_to_hass(self):
        """Subscribe to realtime output updates."""
        self.ws_manager.register_listener("switches", self._handle_realtime_update)

    async def _handle_realtime_update(self, data_list):
        """Process realtime STATUS_OUTPUTS updates."""
        for data in data_list:
            if str(data.get("ID")) == str(self.switch_id):
                self._state = data.get("STA", "off").lower() == "on"
                self._raw_data.update(data)
                self.async_write_ha_state()
                break

    @property
    def unique_id(self):
        """Returns a unique ID for the switch."""
        return f"{self.ws_manager._ip}_{self.switch_id}"

    @property
    def device_info(self):
        """Return device information about this entity."""
        return self._device_info

    @property
    def entity_category(self):
        """Return the entity category for this switch."""
        # Switches are controls/outputs, so no category (they're primary controls)
        return None

    @property
    def name(self):
        """Returns the name of the switch."""
        return self._name

    @property
    def is_on(self):
        """Returns the state of the switch."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Returns the extra state attributes of the switch."""
        return {"raw_data": self._raw_data}

    """
    Turn on the switch.
    """

    async def async_turn_on(self, **kwargs):
        """Turn on the switch."""
        state = self.ws_manager.get_connection_state()
        if state != ConnectionState.CONNECTED:
            _LOGGER.error("WebSocket not connected, cannot turn on switch %s", self.switch_id)
            self._available = False
            return

        await self.ws_manager.turnOnOutput(self.switch_id)
        self._state = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn off the switch."""
        state = self.ws_manager.get_connection_state()
        if state != ConnectionState.CONNECTED:
            _LOGGER.error("WebSocket not connected, cannot turn off switch %s", self.switch_id)
            self._available = False
            return

        await self.ws_manager.turnOffOutput(self.switch_id)
        self._state = False
        self.async_write_ha_state()

    """
    Update the state of the switch.
    """

    async def async_update(self):
        switches = await self.ws_manager.getSwitches()
        for switch in switches:
            if str(switch.get("ID")) == str(self.switch_id):
                self._state = switch.get("STA", "off").lower() == "on"
                # Merge update into raw_data to preserve all fields
                self._raw_data.update(switch)
                break

    @property
    def should_poll(self) -> bool:
        """Output switches use periodic polling for multi-client reconciliation."""
        return True


class KseniaZoneBypassSwitch(SwitchEntity):
    """Switch entity to control zone bypass status."""

    _attr_has_entity_name = True
    _attr_translation_key = "zone_bypass"

    def __init__(self, ws_manager, zone_id, name, zone_data, device_info=None):
        """Initialize the zone bypass switch."""
        self.ws_manager = ws_manager
        self.zone_id = zone_id
        self._attr_translation_placeholders = {"zone_name": name}
        self._available = True
        self._device_info = device_info
        # Parse bypass status: NO/N means not bypassed, anything else (AUTO, MAN_M, MAN_T) means bypassed
        byp_val = zone_data.get("BYP", "NO")
        self._state = byp_val.upper() not in ["NO", "N"]
        self._raw_data = dict(zone_data)

    async def async_added_to_hass(self):
        """Register listener for zone updates."""
        self.ws_manager.register_listener("zones", self._handle_realtime_update)

    async def _handle_realtime_update(self, data_list):
        """Handle real-time zone updates."""
        for data in data_list:
            if str(data.get("ID")) == str(self.zone_id):
                # Only update bypass state when BYP is present; otherwise keep current state
                if "BYP" in data:
                    byp_val = str(data.get("BYP", "NO"))
                    self._state = byp_val.upper() not in ["NO", "N"]
                self._raw_data.update(data)
                self.async_write_ha_state()
                break

    @property
    def unique_id(self):
        """Returns a unique ID for the zone bypass switch."""
        return f"{self.ws_manager._ip}_zone_{self.zone_id}_bypass"

    @property
    def device_info(self):
        """Return device information about this entity."""
        return self._device_info

    @property
    def entity_category(self):
        """Return the entity category for this switch."""
        return EntityCategory.CONFIG

    @property
    def is_on(self):
        """Returns True if zone is bypassed."""
        return self._state

    @property
    def icon(self):
        """Return icon for bypass switch."""
        return "mdi:shield-off" if self._state else "mdi:shield-check"

    @property
    def extra_state_attributes(self):
        """Returns the extra state attributes of the switch."""
        return {"raw_data": self._raw_data}

    async def async_turn_on(self, **kwargs):
        """Bypass the zone."""
        state = self.ws_manager.get_connection_state()
        if state != ConnectionState.CONNECTED:
            _LOGGER.error("WebSocket not connected, cannot bypass zone %s", self.zone_id)
            self._available = False
            return

        success = await self.ws_manager.bypass_zone(self.zone_id, "MAN_M")
        if success:
            self._state = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Unbypass the zone."""
        state = self.ws_manager.get_connection_state()
        if state != ConnectionState.CONNECTED:
            _LOGGER.error("WebSocket not connected, cannot unbypass zone %s", self.zone_id)
            self._available = False
            return

        success = await self.ws_manager.bypass_zone(self.zone_id, "NO")
        if success:
            self._state = False
            self.async_write_ha_state()

    @property
    def should_poll(self) -> bool:
        """Zone bypass switches use periodic polling for multi-client reconciliation."""
        return True

    async def async_update(self):
        """Refresh zone bypass state from cached data."""
        # Get cached zone configuration data
        zones = self.ws_manager.get_cached_data("ZONES")
        if not zones:
            return
        for zone in zones:
            if str(zone.get("ID")) == str(self.zone_id):
                if "BYP" in zone:
                    byp_val = str(zone.get("BYP", "NO"))
                    self._state = byp_val.upper() not in ["NO", "N"]
                self._raw_data.update(zone)
                break
