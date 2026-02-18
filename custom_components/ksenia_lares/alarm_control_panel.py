"""Alarm control panel entity for Ksenia Lares integration.

Single device-level alarm entity managing all partitions via scenarios.
Scenarios are discovered from SCENARIOS configuration using CAT (category) field.
"""

import logging
from datetime import timedelta

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
)
from homeassistant.components.alarm_control_panel.const import (
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _build_scenario_map(scenarios):
    """Build scenario CAT→ID mapping from scenarios.

    Args:
        scenarios: List of scenario dictionaries from SCENARIOS

    Returns:
        Dictionary mapping CAT values to scenario IDs
        Example: {"DISARM": "1", "ARM": "2", "PARTIAL": "3"}
    """
    mapping = {}
    for scenario in scenarios:
        cat = scenario.get("CAT", "").upper()
        scenario_id = scenario.get("ID")
        if cat and scenario_id:
            mapping[cat] = str(scenario_id)
    _LOGGER.debug("Scenario mapping from CAT field: %s", mapping)
    return mapping


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Ksenia Lares alarm control panel entity.

    Creates single device-level alarm control panel entity managing all partitions
    via scenarios. Scenarios are discovered from configuration using CAT field.
    """
    try:
        ws_manager = hass.data[DOMAIN]["ws_manager"]
        device_info = hass.data[DOMAIN].get("device_info")

        # Discover scenarios and build CAT-based mapping
        scenarios = await ws_manager.getScenarios()
        scenario_map = _build_scenario_map(scenarios)

        if not scenario_map:
            _LOGGER.error(
                "No scenarios with CAT field found. "
                "Available CAT values should be: DISARM, ARM, PARTIAL"
            )
            return

        # Create single alarm panel entity for entire device
        entity = KseniaAlarmControlPanel(ws_manager, scenario_map, device_info)
        async_add_entities([entity], update_before_add=True)
    except Exception as e:
        _LOGGER.error("Error setting up alarm control panel: %s", e, exc_info=True)


class KseniaAlarmControlPanel(AlarmControlPanelEntity):
    """Alarm control panel entity for Ksenia Lares device.

    Manages all partitions as a single device entity using scenarios.
    Scenarios are discovered from device configuration using CAT field.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "alarm_control_panel"

    def __init__(self, ws_manager, scenario_map, device_info=None):
        """Initialize the alarm control panel.

        Args:
            ws_manager: WebSocketManager instance
            scenario_map: Dictionary mapping scenario CAT→ID
                Example: {"DISARM": "1", "ARM": "2", "PARTIAL": "3"}
            device_info: Device information for grouping entities
        """
        self.ws_manager = ws_manager
        self._scenarios = scenario_map
        self._device_info = device_info
        self._state = AlarmControlPanelState.DISARMED
        self._system_status = {}  # Track system status from STATUS_SYSTEM
        self._partitions_status = []  # Track partition status from STATUS_PARTITIONS

    async def async_added_to_hass(self):
        """Subscribe to system and partition status realtime updates."""
        _LOGGER.debug("[KseniaACP] Registering listener for 'systems' realtime updates")
        self.ws_manager.register_listener("systems", self._handle_system_status_update)
        _LOGGER.debug("[KseniaACP] Registering listener for 'partitions' realtime updates")
        self.ws_manager.register_listener("partitions", self._handle_partition_status_update)
        _LOGGER.debug("[KseniaACP] Listeners registered successfully")

        # Load initial partition data from cache if available
        try:
            partitions = self.ws_manager.get_cached_data("STATUS_PARTITIONS")
            if partitions:
                self._partitions_status = partitions
                _LOGGER.debug(f"[KseniaACP] Loaded initial partition data from cache: {partitions}")
        except Exception as e:
            _LOGGER.debug(f"[KseniaACP] Could not load initial partition data: {e}")

    async def _handle_system_status_update(self, system_list):
        """Handle realtime system status changes.

        Uses ARM field from STATUS_SYSTEM to determine alarm state.

        Args:
            system_list: List of system status dictionaries from WebSocket
        """
        _LOGGER.debug(
            f"[KseniaACP] _handle_system_status_update called with {len(system_list) if system_list else 0} systems"
        )
        if system_list and len(system_list) > 0:
            _LOGGER.debug(f"[KseniaACP] System data: {system_list[0]}")
            self._system_status.update(system_list[0])
            self._compute_state_from_system()
            _LOGGER.debug(f"[KseniaACP] Computed state: {self._state}")
            self.async_write_ha_state()
        else:
            _LOGGER.debug("[KseniaACP] No system list provided to handler")

    async def _handle_partition_status_update(self, partitions_list):
        """Handle realtime partition status changes.

        Monitors partition alarm status (AST field) for alarm states.
        Partition ARM can be: D, IA, DA, IT, OT (no AL/AM per protocol).

        CRITICAL: Must compute state on partition updates to detect alarm triggers
        immediately through the AST field check in _has_partition_alarm().

        Args:
            partitions_list: List of partition status dictionaries from WebSocket
        """
        _LOGGER.debug(
            f"[KseniaACP] _handle_partition_status_update called with {len(partitions_list) if partitions_list else 0} partitions"
        )
        if partitions_list:
            self._partitions_status = partitions_list
            _LOGGER.debug(f"[KseniaACP] Partition data: {partitions_list}")
            # CRITICAL: Compute state to detect partition alarms (AST field)
            # This must happen immediately when partition updates arrive, not deferred
            self._compute_state_from_system()
            _LOGGER.debug(f"[KseniaACP] Computed state after partition update: {self._state}")
            self.async_write_ha_state()
        else:
            _LOGGER.debug("[KseniaACP] No partition data in update")

    def _compute_state_from_system(self):
        """Compute alarm state from system status.

        Evaluates system ARM state, partition alarms, and zone bypass status
        to determine overall alarm control panel state.

        Uses system status (from STATUS_SYSTEM) plus partition alarm status (AST)
        and zone bypass status to determine overall alarm control panel state.
        """
        arm_state = self._get_arm_state_code()
        has_bypassed_zones = self._has_bypassed_zones()
        partition_alarm_active = self._has_partition_alarm()

        # Determine state based on arm state and conditions
        # IMPORTANT: Check disarmed state FIRST before alarm state
        if arm_state == "D":
            self._state = AlarmControlPanelState.DISARMED
        elif partition_alarm_active:
            self._state = AlarmControlPanelState.TRIGGERED
            _LOGGER.info(
                "ALARM TRIGGERED - Partition alarm detected, alarm control panel state set to TRIGGERED"
            )
        elif self._is_delay_active(arm_state):
            self._state = AlarmControlPanelState.PENDING
        elif has_bypassed_zones and arm_state in ("T", "P"):
            self._state = AlarmControlPanelState.ARMED_CUSTOM_BYPASS
        elif arm_state == "T":
            self._state = AlarmControlPanelState.ARMED_AWAY
        elif arm_state == "P":
            self._state = AlarmControlPanelState.ARMED_HOME
        else:
            # Unrecognized ARM.S code - keep current state rather than
            # defaulting to DISARMED which causes false state flips
            _LOGGER.debug(
                "Unrecognized ARM.S code '%s', keeping current state: %s",
                arm_state,
                self._state,
            )

        arm_data = self._system_status.get("ARM", {})
        _LOGGER.debug(
            "Alarm state computed: %s (ARM.S=%s, ARM.D=%s, partition_alarm=%s, bypassed_zones=%s)",
            self._state,
            arm_state,
            arm_data.get("D", "Unknown") if isinstance(arm_data, dict) else "N/A",
            partition_alarm_active,
            has_bypassed_zones,
        )

    def _get_arm_state_code(self) -> str:
        """Extract ARM.S code from system status.

        Returns:
            ARM state code string, defaults to "D" (disarmed)
        """
        arm_data = self._system_status.get("ARM", {})
        if isinstance(arm_data, dict):
            return arm_data.get("S", "")
        return ""

    def _is_delay_active(self, arm_state: str) -> bool:
        """Check if entry or exit delay is active.

        Args:
            arm_state: ARM.S code from STATUS_SYSTEM

        Returns:
            True if delay is active (entry/exit delay in STATUS_SYSTEM)

        Supported delay states (per protocol specification):
            - T_IN: Fully armed with entry delay active
            - P_IN: Partially armed with entry delay active
            - T_OUT: Fully armed with exit delay active
            - P_OUT: Partially armed with exit delay active
        """
        return arm_state in ("T_IN", "P_IN", "T_OUT", "P_OUT")

    def _has_partition_alarm(self) -> bool:
        """Check if any partition has active or memory alarm.

        Uses AST (Alarm Status) field to detect alarms:
        - AL: Ongoing alarm
        - AM: Alarm memory (recent alarm, now cleared)

        Returns:
            True if any partition reports alarm state via AST field
        """
        for partition in self._partitions_status:
            partition_ast = partition.get("AST", "OK")
            # Only check AST field for alarm states, not ARM field
            # ARM field only contains armed modes (D, IA, DA, IT, OT), never alarm states
            if partition_ast in ("AL", "AM"):
                _LOGGER.debug(
                    f"[KseniaACP] Partition {partition.get('ID')} alarm detected: AST={partition_ast}"
                )
                return True
        return False

    def _has_bypassed_zones(self) -> bool:
        """Check if any zones are bypassed.

        Checks both INFO field and individual zone bypass status.

        Returns:
            True if any zone is bypassed
        """
        # Check INFO field first
        info_flags = self._system_status.get("INFO", [])
        if "BYP_ZONE" in info_flags:
            return True

        # Check individual zone bypass status
        zones = self.ws_manager.get_cached_data("STATUS_ZONES")
        for zone in zones:
            zone_byp = zone.get("BYP", "NO")
            if zone_byp in ("AUTO", "MAN_M", "MAN_T"):
                return True
        return False

    @property
    def unique_id(self):
        """Return unique ID for the entity."""
        return f"{self.ws_manager._ip}_alarm_control_panel"

    @property
    def device_info(self):
        """Return device information about this entity."""
        return self._device_info

    @property
    def alarm_state(self):
        """Return the current alarm state."""
        return self._state

    @property
    def code_format(self) -> CodeFormat:
        """Return the code format for PIN entry.

        Ksenia uses 6-digit numeric PIN.
        """
        return CodeFormat.NUMBER

    @property
    def code_arm_required(self) -> bool:
        """Return whether code is required for arm actions.

        Ksenia requires PIN to arm/disarm for security.
        """
        return True

    @property
    def supported_features(self) -> AlarmControlPanelEntityFeature:
        """Return supported features based on configured scenarios.

        Dynamically adds ARM_AWAY and ARM_HOME based on available scenarios
        with corresponding CAT (category) values.
        """
        features = AlarmControlPanelEntityFeature(0)

        if self._scenarios.get("ARM"):
            features |= AlarmControlPanelEntityFeature.ARM_AWAY

        if self._scenarios.get("PARTIAL"):
            features |= AlarmControlPanelEntityFeature.ARM_HOME

        return features

    @property
    def should_poll(self) -> bool:
        """Poll periodically as fallback for missed realtime updates."""
        return True

    @property
    def scan_interval(self):
        """Poll every 60 seconds as fallback."""
        return timedelta(seconds=60)

    async def async_update(self):
        """Fallback polling to ensure state is current.

        Requests latest system and partition status if realtime update missed.
        HA will automatically call async_write_ha_state() after this method returns.
        """
        try:
            # Fetch fresh system status to ensure exit/entry delays are reflected
            # This is critical because the device may not broadcast STATUS_SYSTEM updates
            # during countdown periods
            system_data = await self.ws_manager.getSensor("STATUS_SYSTEM")
            if system_data and len(system_data) > 0:
                self._system_status.update(system_data[0])

            # Also fetch partition status to detect alarm states
            # Partition alarm status is only available in STATUS_PARTITIONS
            try:
                partitions = self.ws_manager.get_cached_data("STATUS_PARTITIONS")
                if partitions:
                    self._partitions_status = partitions
            except Exception as partition_err:
                _LOGGER.debug(f"Could not fetch partition status during polling: {partition_err}")

            if system_data:
                self._compute_state_from_system()
                _LOGGER.debug(f"Polling update: alarm state = {self._state}")
            else:
                _LOGGER.debug("No system status available in polling update")
        except Exception as e:
            _LOGGER.debug(f"Polling update failed for alarm panel: {e}", exc_info=True)

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Disarm all partitions.

        Args:
            code: PIN code required to disarm (user-entered, dynamic)

        Raises:
            ValueError: If code is not provided
            Exception: If DISARM scenario not configured or execution fails
        """
        if code is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="pin_required_disarm",
            )

        scenario_id = self._scenarios.get("DISARM")
        if not scenario_id:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="scenario_missing",
                translation_placeholders={"cat": "DISARM"},
            )

        try:
            _LOGGER.debug("Disarming all partitions via scenario %s", scenario_id)
            # Pass user-entered PIN to create separate authenticated session
            success = await self.ws_manager.executeScenario_with_login(scenario_id, pin=code)

            if success:
                _LOGGER.info("All partitions disarmed successfully")
            else:
                _LOGGER.error("Failed to disarm partitions")
                detail = self.ws_manager.get_last_command_error_detail()
                if detail == "WRONG_PIN":
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="wrong_pin",
                    )
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="disarm_failed",
                )

        except HomeAssistantError:
            raise
        except Exception as e:
            _LOGGER.error("Error disarming partitions: %s", e)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="disarm_failed",
            ) from e

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Arm all partitions in away mode.

        Args:
            code: PIN code required to arm (user-entered, dynamic)

        Raises:
            ValueError: If code is not provided
            Exception: If ARM scenario not configured or execution fails
        """
        if code is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="pin_required_arm",
            )

        scenario_id = self._scenarios.get("ARM")
        if not scenario_id:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="scenario_missing",
                translation_placeholders={"cat": "ARM"},
            )

        try:
            _LOGGER.debug("Arming all partitions in away mode via scenario %s", scenario_id)
            # Pass user-entered PIN to create separate authenticated session
            success = await self.ws_manager.executeScenario_with_login(scenario_id, pin=code)

            if success:
                _LOGGER.info("All partitions armed in away mode")
            else:
                _LOGGER.error("Failed to arm partitions in away mode")
                detail = self.ws_manager.get_last_command_error_detail()
                if detail == "WRONG_PIN":
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="wrong_pin",
                    )
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="arm_away_failed",
                )

        except HomeAssistantError:
            raise
        except Exception as e:
            _LOGGER.error("Error arming partitions in away mode: %s", e)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="arm_away_failed",
            ) from e

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Arm all partitions in home/stay mode.

        Home mode typically uses partial arming where volume protection
        (motion sensors) is disabled while perimeter protection remains active.
        Users can manually bypass zones if needed.

        Args:
            code: PIN code required to arm (user-entered, dynamic)

        Raises:
            ValueError: If code is not provided
            Exception: If PARTIAL scenario not configured or execution fails
        """
        if code is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="pin_required_arm",
            )

        scenario_id = self._scenarios.get("PARTIAL")
        if not scenario_id:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="scenario_missing",
                translation_placeholders={"cat": "PARTIAL"},
            )

        try:
            _LOGGER.debug("Arming all partitions in home mode via scenario %s", scenario_id)
            # Pass user-entered PIN to create separate authenticated session
            success = await self.ws_manager.executeScenario_with_login(scenario_id, pin=code)

            if success:
                _LOGGER.info("All partitions armed in home mode")
            else:
                _LOGGER.error("Failed to arm partitions in home mode")
                detail = self.ws_manager.get_last_command_error_detail()
                if detail in ("LOGIN_KO", "WRONG_PIN"):
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="wrong_pin_check",
                    )
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="arm_home_failed",
                )

        except HomeAssistantError:
            raise
        except Exception as e:
            _LOGGER.error("Error arming partitions in home mode: %s", e)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="arm_home_failed",
            ) from e

    @property
    def icon(self):
        """Return icon based on alarm state."""
        icon_map = {
            AlarmControlPanelState.DISARMED: "mdi:shield-off",
            AlarmControlPanelState.ARMED_AWAY: "mdi:shield-check",
            AlarmControlPanelState.ARMED_HOME: "mdi:shield-home",
            AlarmControlPanelState.ARMED_NIGHT: "mdi:shield-moon",
            AlarmControlPanelState.ARMED_VACATION: "mdi:shield-star",
            AlarmControlPanelState.ARMED_CUSTOM_BYPASS: "mdi:shield-half",
            AlarmControlPanelState.TRIGGERED: "mdi:alarm-light",
            AlarmControlPanelState.PENDING: "mdi:alarm-light-outline",
        }
        return icon_map.get(self._state, "mdi:shield")

    @property
    def extra_state_attributes(self):
        """Return additional state attributes from system status.

        Attributes show user-friendly information:
        - device_status: Device's own description (e.g., "Partially Armed with Exit Delay Active")
        - alarm_condition: Current alarm condition (No Alarm, Ongoing Alarm, Alarm Memory)
        - bypassed_zones: List of zones that are manually bypassed with type
        - partition_status: Status of each partition
        """
        arm_data = self._system_status.get("ARM", {})
        device_description = (
            arm_data.get("D", "Unknown") if isinstance(arm_data, dict) else "Unknown"
        )

        # Map alarm status to readable string
        ast_status = self._system_status.get("AST", "Unknown")
        ast_map = {"OK": "No Alarm", "AL": "Ongoing Alarm", "AM": "Alarm Memory"}
        readable_alarm_status = ast_map.get(ast_status, ast_status)

        # Get bypassed zones from realtime data
        bypassed_zones = []
        try:
            zones = self.ws_manager.get_cached_data("STATUS_ZONES")
            for zone in zones:
                zone_byp = zone.get("BYP", "NO")
                if zone_byp != "NO":  # Zone is bypassed
                    zone_id = zone.get("ID", "Unknown")
                    zone_label = zone.get("LBL", "") or zone.get("DES", f"Zone {zone_id}")
                    bypass_type = "Manual" if zone_byp in ("MAN_M", "MAN_T") else "Auto"
                    bypassed_zones.append(f"{zone_label} ({bypass_type})")
        except Exception as e:
            _LOGGER.debug(f"Error loading bypassed zones for attributes: {e}")

        # Get partition status from realtime data
        partition_status = {}
        try:
            partitions = self.ws_manager.get_cached_data("STATUS_PARTITIONS")
            for part in partitions:
                part_id = part.get("ID", "Unknown")
                part_arm = part.get("ARM", "Unknown")
                # Map partition ARM codes to readable descriptions
                arm_map = {
                    "D": "Disarmed",
                    "IA": "Armed",
                    "DA": "Arming (exit delay)",
                    "IT": "Entry delay active",
                    "OT": "Exit delay active",
                    "AL": "Alarm triggered",
                    "AM": "Alarm memory",
                }
                readable_arm = arm_map.get(part_arm, part_arm)
                partition_status[f"partition_{part_id}"] = readable_arm
        except Exception as e:
            _LOGGER.debug(f"Error loading partition status for attributes: {e}")

        return {
            "device_status": device_description,  # Device's description
            "alarm_condition": readable_alarm_status,  # No Alarm / Ongoing Alarm / Alarm Memory
            "bypassed_zones": (
                bypassed_zones if bypassed_zones else "None"
            ),  # List of bypassed zones with type
            "partition_status": partition_status,  # Status of each partition
            "scenarios_available": list(self._scenarios.keys()),
            "connection_state": (
                self.ws_manager.get_connection_state().name
                if self.ws_manager.get_connection_state()
                else "unknown"
            ),
        }
