"""Tests for the Ksenia Lares integration entry point (__init__.py).

Covers connection setup/teardown, config-entry migration helpers, and the
one-time entity-registry cleanup/migration logic run during setup. This
module had essentially zero direct test coverage before this file even
though it is the code path that establishes (and tears down) the panel
connection for every install of the integration.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.ksenia_lares.const import CONF_HOST, CONF_PIN, CONF_PLATFORMS, DOMAIN


def _fake_entry(data=None, options=None, entry_id="entry1", title="Ksenia @ 1.2.3.4"):
    entry = MagicMock()
    entry.data = data if data is not None else {CONF_HOST: "1.2.3.4", CONF_PIN: "1234"}
    entry.options = options if options is not None else {}
    entry.entry_id = entry_id
    entry.title = title
    entry.add_update_listener = MagicMock(return_value=MagicMock())
    entry.async_on_unload = MagicMock()
    return entry


def _fake_hass():
    hass = MagicMock()
    hass.data = {}
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    hass.config_entries.async_forward_entry_unload = AsyncMock(return_value=True)
    hass.config_entries.async_reload = AsyncMock()
    hass.config_entries.async_schedule_reload = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()
    return hass


def _reg_entry(entity_id, unique_id, domain, platform=DOMAIN):
    return SimpleNamespace(entity_id=entity_id, unique_id=unique_id, domain=domain, platform=platform)


# ============================================================================
# _compute_new_unique_id / _migrate_ip_based_uid (pure functions)
# ============================================================================


def test_migrate_ip_based_uid_alarm_control_panel():
    from custom_components.ksenia_lares import _migrate_ip_based_uid

    result = _migrate_ip_based_uid("alarm_control_panel", "AA:BB", "alarm_control_panel", {})
    assert result == "AA:BB_alarm_control_panel"


def test_migrate_ip_based_uid_sensor():
    from custom_components.ksenia_lares import _migrate_ip_based_uid

    result = _migrate_ip_based_uid("some_suffix", "AA:BB", "sensor", {})
    assert result == "AA:BB_some_suffix"


def test_migrate_ip_based_uid_switch_zone_bypass():
    from custom_components.ksenia_lares import _migrate_ip_based_uid

    result = _migrate_ip_based_uid("zone_5_bypass", "AA:BB", "switch", {})
    assert result == "AA:BB_zone_bypass_5"


def test_migrate_ip_based_uid_switch_output_uses_cat_map():
    from custom_components.ksenia_lares import _migrate_ip_based_uid

    result = _migrate_ip_based_uid("7", "AA:BB", "switch", {"7": "output"})
    assert result == "AA:BB_output_7"


def test_migrate_ip_based_uid_switch_output_defaults_to_output_when_unknown():
    from custom_components.ksenia_lares import _migrate_ip_based_uid

    result = _migrate_ip_based_uid("99", "AA:BB", "switch", {})
    assert result == "AA:BB_output_99"


def test_migrate_ip_based_uid_light():
    from custom_components.ksenia_lares import _migrate_ip_based_uid

    assert _migrate_ip_based_uid("3", "AA:BB", "light", {}) == "AA:BB_light_3"


def test_migrate_ip_based_uid_cover():
    from custom_components.ksenia_lares import _migrate_ip_based_uid

    assert _migrate_ip_based_uid("3", "AA:BB", "cover", {}) == "AA:BB_cover_3"


def test_migrate_ip_based_uid_button_clear():
    from custom_components.ksenia_lares import _migrate_ip_based_uid

    assert _migrate_ip_based_uid("clear_faults", "AA:BB", "button", {}) == "AA:BB_clear_faults"


def test_migrate_ip_based_uid_button_scenario():
    from custom_components.ksenia_lares import _migrate_ip_based_uid

    assert _migrate_ip_based_uid("5", "AA:BB", "button", {}) == "AA:BB_scenario_5"


def test_migrate_ip_based_uid_unknown_domain_returns_none():
    from custom_components.ksenia_lares import _migrate_ip_based_uid

    assert _migrate_ip_based_uid("5", "AA:BB", "climate", {}) is None


def test_compute_new_unique_id_ip_prefixed():
    from custom_components.ksenia_lares import _compute_new_unique_id

    result = _compute_new_unique_id("1.2.3.4_3", "AA:BB", "1.2.3.4_", "light", {})
    assert result == "AA:BB_light_3"


def test_compute_new_unique_id_domus_sensor_adds_temperature_suffix():
    from custom_components.ksenia_lares import _compute_new_unique_id

    result = _compute_new_unique_id("domus_1", "AA:BB", "1.2.3.4_", "sensor", {})
    assert result == "AA:BB_domus_1_temperature"


def test_compute_new_unique_id_non_ip_sensor_prefix_not_recognized():
    from custom_components.ksenia_lares import _compute_new_unique_id

    result = _compute_new_unique_id("something_else_1", "AA:BB", "1.2.3.4_", "sensor", {})
    assert result is None


def test_compute_new_unique_id_already_mac_based_returns_none():
    from custom_components.ksenia_lares import _compute_new_unique_id

    result = _compute_new_unique_id("random", "AA:BB", "1.2.3.4_", "climate", {})
    assert result is None


# ============================================================================
# _rm_sensors_migrated2binarysensor
# ============================================================================


def test_rm_sensors_migrated2binarysensor_removes_matching_zone_cats():
    from custom_components.ksenia_lares import _rm_sensors_migrated2binarysensor

    entries = [
        _reg_entry("sensor.door_1", "door_1", "sensor"),
        _reg_entry("sensor.siren_1", "siren_1", "sensor"),
        _reg_entry("sensor.temp_1", "domus_1_temperature", "sensor"),
    ]
    ent_reg = MagicMock()
    ent_reg.async_remove = MagicMock()
    hass = _fake_hass()
    entry = _fake_entry()

    with patch("custom_components.ksenia_lares.er.async_get", return_value=ent_reg), patch(
        "custom_components.ksenia_lares.er.async_entries_for_config_entry", return_value=entries
    ):
        _rm_sensors_migrated2binarysensor(hass, entry)

    removed_ids = [c.args[0] for c in ent_reg.async_remove.call_args_list]
    assert "sensor.door_1" in removed_ids
    assert "sensor.siren_1" in removed_ids
    assert "sensor.temp_1" not in removed_ids


def test_rm_sensors_migrated2binarysensor_skips_other_domains():
    from custom_components.ksenia_lares import _rm_sensors_migrated2binarysensor

    entries = [_reg_entry("switch.door_1", "AA:BB_door_1", "switch")]
    ent_reg = MagicMock()
    hass = _fake_hass()
    entry = _fake_entry()

    with patch("custom_components.ksenia_lares.er.async_get", return_value=ent_reg), patch(
        "custom_components.ksenia_lares.er.async_entries_for_config_entry", return_value=entries
    ):
        _rm_sensors_migrated2binarysensor(hass, entry)

    ent_reg.async_remove.assert_not_called()


def test_rm_sensors_migrated2binarysensor_skips_other_platforms():
    from custom_components.ksenia_lares import _rm_sensors_migrated2binarysensor

    entries = [_reg_entry("sensor.door_1", "AA:BB_door_1", "sensor", platform="other_integration")]
    ent_reg = MagicMock()
    hass = _fake_hass()
    entry = _fake_entry()

    with patch("custom_components.ksenia_lares.er.async_get", return_value=ent_reg), patch(
        "custom_components.ksenia_lares.er.async_entries_for_config_entry", return_value=entries
    ):
        _rm_sensors_migrated2binarysensor(hass, entry)

    ent_reg.async_remove.assert_not_called()


# ============================================================================
# _rm_stale_switches
# ============================================================================


def test_rm_stale_switches_removes_matching_uids():
    from custom_components.ksenia_lares import _rm_stale_switches

    entries = [
        _reg_entry("switch.siren", "AA:BB_output_2", "switch"),
        _reg_entry("switch.normal", "AA:BB_output_1", "switch"),
    ]
    ent_reg = MagicMock()
    hass = _fake_hass()
    entry = _fake_entry()

    with patch("custom_components.ksenia_lares.er.async_get", return_value=ent_reg), patch(
        "custom_components.ksenia_lares.er.async_entries_for_config_entry", return_value=entries
    ):
        _rm_stale_switches(hass, entry, {"AA:BB_output_2"}, "hidden output")

    ent_reg.async_remove.assert_called_once_with("switch.siren")


def test_rm_stale_switches_empty_uids_is_noop():
    from custom_components.ksenia_lares import _rm_stale_switches

    hass = _fake_hass()
    entry = _fake_entry()

    # Should not even touch the entity registry when there's nothing to remove
    with patch("custom_components.ksenia_lares.er.async_get") as mock_get:
        _rm_stale_switches(hass, entry, set(), "nothing")
        mock_get.assert_not_called()


# ============================================================================
# _build_hidden_switch_uids / _build_roll_switch_uids
# ============================================================================


@pytest.mark.asyncio
async def test_build_hidden_switch_uids_includes_old_and_new_formats():
    from custom_components.ksenia_lares import _build_hidden_switch_uids

    ws_manager = MagicMock()
    ws_manager.getSwitches = AsyncMock(
        return_value=[
            {"ID": "2", "DES": "Siren", "CAT": "GEN"},
            {"ID": "3", "DES": "Normal Switch", "CAT": "GEN"},
        ]
    )

    uids = await _build_hidden_switch_uids(ws_manager, "AA:BB", "10.0.0.5")

    assert "10.0.0.5_2" in uids
    assert "AA:BB_gen_2" in uids
    assert not any(u.endswith("_3") for u in uids)


@pytest.mark.asyncio
async def test_build_hidden_switch_uids_returns_empty_set_on_error():
    from custom_components.ksenia_lares import _build_hidden_switch_uids

    ws_manager = MagicMock()
    ws_manager.getSwitches = AsyncMock(side_effect=RuntimeError("boom"))

    uids = await _build_hidden_switch_uids(ws_manager, "AA:BB", "1.2.3.4")

    assert uids == set()


@pytest.mark.asyncio
async def test_build_roll_switch_uids_includes_all_formats():
    from custom_components.ksenia_lares import _build_roll_switch_uids

    ws_manager = MagicMock()
    ws_manager.getRolls = AsyncMock(return_value=[{"ID": "9"}])

    uids = await _build_roll_switch_uids(ws_manager, "AA:BB", "1.2.3.4")

    assert uids == {"1.2.3.4_9", "AA:BB_roll_9", "AA:BB_output_9"}


@pytest.mark.asyncio
async def test_build_roll_switch_uids_returns_empty_set_on_error():
    from custom_components.ksenia_lares import _build_roll_switch_uids

    ws_manager = MagicMock()
    ws_manager.getRolls = AsyncMock(side_effect=RuntimeError("boom"))

    uids = await _build_roll_switch_uids(ws_manager, "AA:BB", "1.2.3.4")

    assert uids == set()


# ============================================================================
# _migrate_unique_ids
# ============================================================================


@pytest.mark.asyncio
async def test_migrate_unique_ids_skips_when_no_mac():
    from custom_components.ksenia_lares import _migrate_unique_ids

    hass = _fake_hass()
    entry = _fake_entry()
    ws_manager = MagicMock()

    with patch("custom_components.ksenia_lares.er.async_get") as mock_get:
        await _migrate_unique_ids(hass, entry, None, "1.2.3.4", ws_manager)
        mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_migrate_unique_ids_updates_ip_based_entries():
    from custom_components.ksenia_lares import _migrate_unique_ids

    entries = [_reg_entry("light.kitchen", "1.2.3.4_3", "light")]
    ent_reg = MagicMock()
    ent_reg.async_update_entity = MagicMock()
    hass = _fake_hass()
    entry = _fake_entry()
    ws_manager = MagicMock()
    ws_manager.getSwitches = AsyncMock(return_value=[])

    with patch("custom_components.ksenia_lares.er.async_get", return_value=ent_reg), patch(
        "custom_components.ksenia_lares.er.async_entries_for_config_entry", return_value=entries
    ):
        await _migrate_unique_ids(hass, entry, "AA:BB", "1.2.3.4", ws_manager)

    ent_reg.async_update_entity.assert_called_once_with(
        "light.kitchen", new_unique_id="AA:BB_light_3"
    )


@pytest.mark.asyncio
async def test_migrate_unique_ids_skips_already_migrated():
    from custom_components.ksenia_lares import _migrate_unique_ids

    entries = [_reg_entry("light.kitchen", "AA:BB_light_3", "light")]
    ent_reg = MagicMock()
    hass = _fake_hass()
    entry = _fake_entry()
    ws_manager = MagicMock()
    ws_manager.getSwitches = AsyncMock(return_value=[])

    with patch("custom_components.ksenia_lares.er.async_get", return_value=ent_reg), patch(
        "custom_components.ksenia_lares.er.async_entries_for_config_entry", return_value=entries
    ):
        await _migrate_unique_ids(hass, entry, "AA:BB", "1.2.3.4", ws_manager)

    ent_reg.async_update_entity.assert_not_called()


@pytest.mark.asyncio
async def test_migrate_unique_ids_skips_other_platforms():
    from custom_components.ksenia_lares import _migrate_unique_ids

    entries = [_reg_entry("light.other", "1.2.3.4_3", "light", platform="not_ksenia")]
    ent_reg = MagicMock()
    hass = _fake_hass()
    entry = _fake_entry()
    ws_manager = MagicMock()
    ws_manager.getSwitches = AsyncMock(return_value=[])

    with patch("custom_components.ksenia_lares.er.async_get", return_value=ent_reg), patch(
        "custom_components.ksenia_lares.er.async_entries_for_config_entry", return_value=entries
    ):
        await _migrate_unique_ids(hass, entry, "AA:BB", "1.2.3.4", ws_manager)

    ent_reg.async_update_entity.assert_not_called()


# ============================================================================
# _register_device / _cleanup_ws_manager
# ============================================================================


def test_register_device_with_mac():
    from custom_components.ksenia_lares import _register_device

    device_registry = MagicMock()
    hass = _fake_hass()
    entry = _fake_entry()
    system_info = {"MAC": "AA:BB:CC:DD:EE:FF", "BRAND": "Ksenia", "MODEL": "Lares 4.0"}

    with patch("custom_components.ksenia_lares.dr.async_get", return_value=device_registry):
        _register_device(hass, entry, "1.2.3.4", True, 443, system_info)

    _, kwargs = device_registry.async_get_or_create.call_args
    assert kwargs["identifiers"] == {(DOMAIN, "1.2.3.4")}
    assert kwargs["manufacturer"] == "Ksenia"
    assert kwargs["configuration_url"] == "https://1.2.3.4:443"
    assert kwargs["connections"] is not None


def test_register_device_without_mac_has_no_connections():
    from custom_components.ksenia_lares import _register_device

    device_registry = MagicMock()
    hass = _fake_hass()
    entry = _fake_entry()

    with patch("custom_components.ksenia_lares.dr.async_get", return_value=device_registry):
        _register_device(hass, entry, "1.2.3.4", False, 80, {})

    _, kwargs = device_registry.async_get_or_create.call_args
    assert kwargs["connections"] is None
    assert kwargs["configuration_url"] == "http://1.2.3.4:80"


def test_cleanup_ws_manager_removes_key():
    from custom_components.ksenia_lares import _cleanup_ws_manager

    hass = _fake_hass()
    hass.data[DOMAIN] = {"ws_manager": MagicMock()}

    _cleanup_ws_manager(hass)

    assert "ws_manager" not in hass.data[DOMAIN]


def test_cleanup_ws_manager_noop_when_missing():
    from custom_components.ksenia_lares import _cleanup_ws_manager

    hass = _fake_hass()
    # Should not raise even with no DOMAIN key at all
    _cleanup_ws_manager(hass)


# ============================================================================
# _setup_connection
# ============================================================================


@pytest.mark.asyncio
async def test_setup_connection_success():
    from custom_components.ksenia_lares import _setup_connection

    hass = _fake_hass()
    entry = _fake_entry()
    mock_manager = MagicMock()
    mock_manager.connect = AsyncMock()
    mock_manager.wait_for_initial_data = AsyncMock(return_value=True)
    mock_manager.get_connection_state = MagicMock()

    with patch("custom_components.ksenia_lares.WebSocketManager", return_value=mock_manager):
        result = await _setup_connection(hass, entry, "1.2.3.4", 443, "1234", False, "ksenia")

    assert result is mock_manager
    mock_manager.connect.assert_called_once()
    assert hass.data[DOMAIN]["ws_manager"] is mock_manager


@pytest.mark.asyncio
async def test_setup_connection_uses_secure_when_ssl_true():
    from custom_components.ksenia_lares import _setup_connection

    hass = _fake_hass()
    entry = _fake_entry()
    mock_manager = MagicMock()
    mock_manager.connect = AsyncMock()
    mock_manager.connectSecure = AsyncMock()
    mock_manager.wait_for_initial_data = AsyncMock(return_value=True)

    with patch("custom_components.ksenia_lares.WebSocketManager", return_value=mock_manager):
        await _setup_connection(hass, entry, "1.2.3.4", 443, "1234", True, "ksenia")

    mock_manager.connectSecure.assert_called_once()
    mock_manager.connect.assert_not_called()


@pytest.mark.asyncio
async def test_setup_connection_raises_config_entry_not_ready_when_data_not_ready():
    from custom_components.ksenia_lares import _setup_connection

    hass = _fake_hass()
    entry = _fake_entry()
    mock_manager = MagicMock()
    mock_manager.connect = AsyncMock()
    mock_manager.wait_for_initial_data = AsyncMock(return_value=False)
    mock_manager.get_connection_state = MagicMock(return_value=MagicMock(value="disconnected"))

    with patch("custom_components.ksenia_lares.WebSocketManager", return_value=mock_manager):
        with pytest.raises(ConfigEntryNotReady):
            await _setup_connection(hass, entry, "1.2.3.4", 443, "1234", False, "ksenia")

    # Cleaned up on failure
    assert "ws_manager" not in hass.data.get(DOMAIN, {})


@pytest.mark.asyncio
async def test_setup_connection_raises_config_entry_not_ready_on_connect_exception():
    from custom_components.ksenia_lares import _setup_connection

    hass = _fake_hass()
    entry = _fake_entry()
    mock_manager = MagicMock()
    mock_manager.connect = AsyncMock(side_effect=ConnectionError("refused"))

    with patch("custom_components.ksenia_lares.WebSocketManager", return_value=mock_manager):
        with pytest.raises(ConfigEntryNotReady):
            await _setup_connection(hass, entry, "1.2.3.4", 443, "1234", False, "ksenia")


@pytest.mark.asyncio
async def test_setup_connection_propagates_cancelled_error_and_cleans_up():
    from custom_components.ksenia_lares import _setup_connection

    hass = _fake_hass()
    entry = _fake_entry()
    mock_manager = MagicMock()
    mock_manager.connect = AsyncMock(side_effect=asyncio.CancelledError())

    with patch("custom_components.ksenia_lares.WebSocketManager", return_value=mock_manager):
        with pytest.raises(asyncio.CancelledError):
            await _setup_connection(hass, entry, "1.2.3.4", 443, "1234", False, "ksenia")

    assert "ws_manager" not in hass.data.get(DOMAIN, {})


# ============================================================================
# _async_update_listener
# ============================================================================


@pytest.mark.asyncio
async def test_async_update_listener_reloads_entry():
    from custom_components.ksenia_lares import _async_update_listener

    hass = _fake_hass()
    entry = _fake_entry()

    await _async_update_listener(hass, entry)

    hass.config_entries.async_reload.assert_called_once_with(entry.entry_id)


# ============================================================================
# async_setup_entry (full flow)
# ============================================================================


def _mock_ws_manager_for_setup():
    manager = MagicMock()
    manager.connect = AsyncMock()
    manager.connectSecure = AsyncMock()
    manager.wait_for_initial_data = AsyncMock(return_value=True)
    manager.getSystemVersion = AsyncMock(return_value={"MAC": "AA:BB:CC", "BRAND": "Ksenia"})
    manager.getSwitches = AsyncMock(return_value=[])
    manager.getRolls = AsyncMock(return_value=[])
    return manager


@pytest.mark.asyncio
async def test_async_setup_entry_missing_host_returns_false():
    from custom_components.ksenia_lares import async_setup_entry

    hass = _fake_hass()
    entry = _fake_entry(data={CONF_PIN: "1234"})  # no host

    result = await async_setup_entry(hass, entry)

    assert result is False


@pytest.mark.asyncio
async def test_async_setup_entry_missing_pin_returns_false():
    from custom_components.ksenia_lares import async_setup_entry

    hass = _fake_hass()
    entry = _fake_entry(data={CONF_HOST: "1.2.3.4"})  # no pin

    result = await async_setup_entry(hass, entry)

    assert result is False


@pytest.mark.asyncio
async def test_async_setup_entry_happy_path_forwards_platforms():
    from custom_components.ksenia_lares import async_setup_entry

    hass = _fake_hass()
    entry = _fake_entry(
        data={CONF_HOST: "1.2.3.4", CONF_PIN: "1234", CONF_PLATFORMS: ["light", "binary_sensor"]}
    )
    manager = _mock_ws_manager_for_setup()

    with patch("custom_components.ksenia_lares.WebSocketManager", return_value=manager), patch(
        "custom_components.ksenia_lares.dr.async_get", return_value=MagicMock()
    ), patch("custom_components.ksenia_lares.er.async_get", return_value=MagicMock()), patch(
        "custom_components.ksenia_lares.er.async_entries_for_config_entry", return_value=[]
    ):
        result = await async_setup_entry(hass, entry)

    assert result is True
    hass.config_entries.async_forward_entry_setups.assert_called_once()
    forwarded_platforms = hass.config_entries.async_forward_entry_setups.call_args[0][1]
    assert "light" in forwarded_platforms
    assert "binary_sensor" in forwarded_platforms
    assert hass.data[DOMAIN]["mac"] == "AA:BB:CC"


@pytest.mark.asyncio
async def test_async_setup_entry_auto_adds_binary_sensor_when_sensor_enabled():
    from custom_components.ksenia_lares import async_setup_entry

    hass = _fake_hass()
    entry = _fake_entry(data={CONF_HOST: "1.2.3.4", CONF_PIN: "1234", CONF_PLATFORMS: ["sensor"]})
    manager = _mock_ws_manager_for_setup()

    with patch("custom_components.ksenia_lares.WebSocketManager", return_value=manager), patch(
        "custom_components.ksenia_lares.dr.async_get", return_value=MagicMock()
    ), patch("custom_components.ksenia_lares.er.async_get", return_value=MagicMock()), patch(
        "custom_components.ksenia_lares.er.async_entries_for_config_entry", return_value=[]
    ):
        result = await async_setup_entry(hass, entry)

    assert result is True
    hass.config_entries.async_update_entry.assert_called_once()
    new_data = hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert "binary_sensor" in new_data[CONF_PLATFORMS]


@pytest.mark.asyncio
async def test_async_setup_entry_propagates_config_entry_not_ready():
    from custom_components.ksenia_lares import async_setup_entry

    hass = _fake_hass()
    entry = _fake_entry()
    manager = _mock_ws_manager_for_setup()
    manager.wait_for_initial_data = AsyncMock(return_value=False)
    manager.get_connection_state = MagicMock(return_value=MagicMock(value="disconnected"))

    with patch("custom_components.ksenia_lares.WebSocketManager", return_value=manager):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, entry)


@pytest.mark.asyncio
async def test_async_setup_entry_generic_exception_returns_false():
    from custom_components.ksenia_lares import async_setup_entry

    hass = _fake_hass()
    entry = _fake_entry()
    manager = _mock_ws_manager_for_setup()
    manager.getSystemVersion = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("custom_components.ksenia_lares.WebSocketManager", return_value=manager):
        result = await async_setup_entry(hass, entry)

    assert result is False


@pytest.mark.asyncio
async def test_async_setup_entry_cancelled_error_propagates():
    from custom_components.ksenia_lares import async_setup_entry

    hass = _fake_hass()
    entry = _fake_entry()
    manager = _mock_ws_manager_for_setup()
    # Default entry has no explicit SSL flag, so async_setup_entry defaults use_ssl=True
    # (DEFAULT_SSL) and dispatches to connectSecure(), not connect().
    manager.connectSecure = AsyncMock(side_effect=asyncio.CancelledError())

    with patch("custom_components.ksenia_lares.WebSocketManager", return_value=manager):
        with pytest.raises(asyncio.CancelledError):
            await async_setup_entry(hass, entry)


# ============================================================================
# async_unload_entry
# ============================================================================


@pytest.mark.asyncio
async def test_async_unload_entry_stops_manager_and_unloads_platforms():
    from custom_components.ksenia_lares import async_unload_entry

    hass = _fake_hass()
    entry = _fake_entry(data={CONF_HOST: "1.2.3.4", CONF_PIN: "1234", CONF_PLATFORMS: ["light"]})
    manager = MagicMock()
    manager.stop = AsyncMock()
    hass.data[DOMAIN] = {"ws_manager": manager}

    result = await async_unload_entry(hass, entry)

    assert result is True
    manager.stop.assert_called_once()
    assert "ws_manager" not in hass.data[DOMAIN]
    hass.config_entries.async_forward_entry_unload.assert_called_once()


@pytest.mark.asyncio
async def test_async_unload_entry_handles_missing_ws_manager():
    from custom_components.ksenia_lares import async_unload_entry

    hass = _fake_hass()
    entry = _fake_entry(data={CONF_HOST: "1.2.3.4", CONF_PIN: "1234", CONF_PLATFORMS: ["light"]})
    hass.data[DOMAIN] = {}

    result = await async_unload_entry(hass, entry)

    assert result is True


@pytest.mark.asyncio
async def test_async_unload_entry_returns_true_even_on_stop_error():
    from custom_components.ksenia_lares import async_unload_entry

    hass = _fake_hass()
    entry = _fake_entry(data={CONF_HOST: "1.2.3.4", CONF_PIN: "1234", CONF_PLATFORMS: ["light"]})
    manager = MagicMock()
    manager.stop = AsyncMock(side_effect=RuntimeError("boom"))
    hass.data[DOMAIN] = {"ws_manager": manager}

    result = await async_unload_entry(hass, entry)

    assert result is True
    # ws_manager popped even though stop() raised
    assert "ws_manager" not in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_async_unload_entry_returns_true_on_unexpected_exception():
    from custom_components.ksenia_lares import async_unload_entry

    hass = MagicMock()
    hass.data = {}
    entry = _fake_entry()
    # Force an unexpected exception deep in the unload path
    hass.config_entries.async_forward_entry_unload = AsyncMock(side_effect=RuntimeError("boom"))
    with patch(
        "custom_components.ksenia_lares.asyncio.gather", side_effect=RuntimeError("boom")
    ):
        result = await async_unload_entry(hass, entry)

    assert result is True


@pytest.mark.asyncio
async def test_async_unload_entry_cancels_pending_setup_task():
    from custom_components.ksenia_lares import _SETUP_TASKS, async_unload_entry

    hass = _fake_hass()
    entry = _fake_entry(data={CONF_HOST: "1.2.3.4", CONF_PIN: "1234", CONF_PLATFORMS: []})

    async def _never_finishes():
        await asyncio.sleep(100)

    task = asyncio.create_task(_never_finishes())
    _SETUP_TASKS[entry.entry_id] = task

    result = await async_unload_entry(hass, entry)

    assert result is True
    assert entry.entry_id not in _SETUP_TASKS
    assert task.cancelled() or task.done()
