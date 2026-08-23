"""Tests for the cover (roller blind) platform: setup, discovery, and entity edge cases.

test_addon_core.py already covers basic init/position/open/close. This file
targets async_setup_entry, the listener-based late-discovery flow, and the
realtime-update edge cases (missing POS, pending-command suppression window,
invalid POS parsing) that had no coverage.
"""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ksenia_lares.const import DOMAIN
from custom_components.ksenia_lares.cover import KseniaRollEntity, async_setup_entry


def _hass_with_ws_manager(ws_manager):
    hass = MagicMock()
    hass.data = {DOMAIN: {"ws_manager": ws_manager, "device_info": None, "mac": "AA:BB:CC"}}
    return hass


# ============================================================================
# async_setup_entry
# ============================================================================


@pytest.mark.asyncio
async def test_async_setup_entry_creates_entity_per_roll():
    ws_manager = MagicMock()
    ws_manager.getRolls = AsyncMock(return_value=[{"ID": "1", "DES": "Blind", "POS": "50"}])
    hass = _hass_with_ws_manager(ws_manager)
    async_add_entities = MagicMock()

    await async_setup_entry(hass, MagicMock(), async_add_entities)

    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args[0][0]
    assert len(entities) == 1
    assert entities[0]._roll_id == "1"


@pytest.mark.asyncio
async def test_async_setup_entry_registers_discovery_listener():
    ws_manager = MagicMock()
    ws_manager.getRolls = AsyncMock(return_value=[])
    ws_manager.register_listener = MagicMock()
    hass = _hass_with_ws_manager(ws_manager)

    await async_setup_entry(hass, MagicMock(), MagicMock())

    ws_manager.register_listener.assert_called_once()
    assert ws_manager.register_listener.call_args[0][0] == "covers"


@pytest.mark.asyncio
async def test_discovery_listener_adds_only_new_covers():
    ws_manager = MagicMock()
    ws_manager.getRolls = AsyncMock(return_value=[{"ID": "1", "DES": "Blind 1", "POS": "0"}])
    ws_manager.register_listener = MagicMock()
    hass = _hass_with_ws_manager(ws_manager)
    async_add_entities = MagicMock()

    await async_setup_entry(hass, MagicMock(), async_add_entities)
    discovery_callback = ws_manager.register_listener.call_args[0][1]

    # Second call to getRolls() now returns an additional cover
    ws_manager.getRolls = AsyncMock(
        return_value=[
            {"ID": "1", "DES": "Blind 1", "POS": "0"},
            {"ID": "2", "DES": "Blind 2", "POS": "0"},
        ]
    )
    async_add_entities.reset_mock()

    await discovery_callback([])

    async_add_entities.assert_called_once()
    new_entities = async_add_entities.call_args[0][0]
    assert len(new_entities) == 1
    assert new_entities[0]._roll_id == "2"


@pytest.mark.asyncio
async def test_discovery_listener_noop_when_no_new_covers():
    ws_manager = MagicMock()
    ws_manager.getRolls = AsyncMock(return_value=[{"ID": "1", "DES": "Blind", "POS": "0"}])
    ws_manager.register_listener = MagicMock()
    hass = _hass_with_ws_manager(ws_manager)
    async_add_entities = MagicMock()

    await async_setup_entry(hass, MagicMock(), async_add_entities)
    discovery_callback = ws_manager.register_listener.call_args[0][1]
    async_add_entities.reset_mock()

    await discovery_callback([])

    async_add_entities.assert_not_called()


@pytest.mark.asyncio
async def test_discovery_listener_swallows_exceptions():
    ws_manager = MagicMock()
    ws_manager.getRolls = AsyncMock(return_value=[])
    ws_manager.register_listener = MagicMock()
    hass = _hass_with_ws_manager(ws_manager)

    await async_setup_entry(hass, MagicMock(), MagicMock())
    discovery_callback = ws_manager.register_listener.call_args[0][1]

    ws_manager.getRolls = AsyncMock(side_effect=RuntimeError("boom"))

    # Should not raise
    await discovery_callback([])


@pytest.mark.asyncio
async def test_async_setup_entry_handles_exception_gracefully():
    ws_manager = MagicMock()
    ws_manager.getRolls = AsyncMock(side_effect=RuntimeError("boom"))
    hass = _hass_with_ws_manager(ws_manager)
    async_add_entities = MagicMock()

    # Should not raise
    await async_setup_entry(hass, MagicMock(), async_add_entities)

    async_add_entities.assert_not_called()


# ============================================================================
# KseniaRollEntity realtime update edge cases
# ============================================================================


@pytest.mark.asyncio
async def test_handle_realtime_update_without_pos_only_updates_raw_data():
    ws_manager = MagicMock()
    entity = KseniaRollEntity(ws_manager, "1", "Blind", {"ID": "1", "POS": "50"})
    entity.async_write_ha_state = MagicMock()

    await entity._handle_realtime_update([{"ID": "1", "OTHER": "field"}])

    assert entity._position == "50"  # unchanged from constructor (no POS in this update)
    entity.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_handle_realtime_update_invalid_pos_sets_none():
    ws_manager = MagicMock()
    entity = KseniaRollEntity(ws_manager, "1", "Blind", {"ID": "1", "POS": "50"})
    entity.async_write_ha_state = MagicMock()

    await entity._handle_realtime_update([{"ID": "1", "POS": "not_a_number"}])

    assert entity._position is None


@pytest.mark.asyncio
async def test_handle_realtime_update_suppressed_during_pending_command_window():
    ws_manager = MagicMock()
    entity = KseniaRollEntity(ws_manager, "1", "Blind", {"ID": "1", "POS": "0"})
    entity.async_write_ha_state = MagicMock()
    entity._pending_command = ("open", time.time())

    await entity._handle_realtime_update([{"ID": "1", "POS": "100"}])

    # Update is dropped while pending command is still "fresh" (< 2s old)
    assert entity._position == "0"
    entity.async_write_ha_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_realtime_update_applies_after_pending_command_expires():
    ws_manager = MagicMock()
    entity = KseniaRollEntity(ws_manager, "1", "Blind", {"ID": "1", "POS": "0"})
    entity.async_write_ha_state = MagicMock()
    entity._pending_command = ("open", time.time() - 10)  # stale, > 2s old

    await entity._handle_realtime_update([{"ID": "1", "POS": "100"}])

    assert entity._position == 100
    assert entity._pending_command is None
    entity.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_handle_realtime_update_ignores_other_ids():
    ws_manager = MagicMock()
    entity = KseniaRollEntity(ws_manager, "1", "Blind", {"ID": "1", "POS": "0"})
    entity.async_write_ha_state = MagicMock()

    await entity._handle_realtime_update([{"ID": "999", "POS": "100"}])

    assert entity._position == "0"
    entity.async_write_ha_state.assert_not_called()


# ============================================================================
# Availability guards on commands
# ============================================================================


@pytest.mark.asyncio
async def test_open_cover_noop_when_unavailable():
    ws_manager = MagicMock()
    ws_manager.available = False
    ws_manager.raiseCover = AsyncMock()
    entity = KseniaRollEntity(ws_manager, "1", "Blind", {"ID": "1", "POS": "0"})

    await entity.async_open_cover()

    ws_manager.raiseCover.assert_not_called()


@pytest.mark.asyncio
async def test_close_cover_noop_when_unavailable():
    ws_manager = MagicMock()
    ws_manager.available = False
    ws_manager.lowerCover = AsyncMock()
    entity = KseniaRollEntity(ws_manager, "1", "Blind", {"ID": "1", "POS": "0"})

    await entity.async_close_cover()

    ws_manager.lowerCover.assert_not_called()


@pytest.mark.asyncio
async def test_stop_cover_noop_when_unavailable():
    ws_manager = MagicMock()
    ws_manager.available = False
    ws_manager.stopCover = AsyncMock()
    entity = KseniaRollEntity(ws_manager, "1", "Blind", {"ID": "1", "POS": "0"})

    await entity.async_stop_cover()

    ws_manager.stopCover.assert_not_called()


@pytest.mark.asyncio
async def test_stop_cover_calls_manager_when_available():
    ws_manager = MagicMock()
    ws_manager.available = True
    ws_manager.stopCover = AsyncMock()
    entity = KseniaRollEntity(ws_manager, "1", "Blind", {"ID": "1", "POS": "50"})
    entity.async_write_ha_state = MagicMock()

    await entity.async_stop_cover()

    ws_manager.stopCover.assert_called_once_with("1")


@pytest.mark.asyncio
async def test_set_cover_position_noop_when_unavailable():
    ws_manager = MagicMock()
    ws_manager.available = False
    ws_manager.setCoverPosition = AsyncMock()
    entity = KseniaRollEntity(ws_manager, "1", "Blind", {"ID": "1", "POS": "0"})

    await entity.async_set_cover_position(position=50)

    ws_manager.setCoverPosition.assert_not_called()


@pytest.mark.asyncio
async def test_set_cover_position_noop_without_position_kwarg():
    ws_manager = MagicMock()
    ws_manager.available = True
    ws_manager.setCoverPosition = AsyncMock()
    entity = KseniaRollEntity(ws_manager, "1", "Blind", {"ID": "1", "POS": "0"})

    await entity.async_set_cover_position()

    ws_manager.setCoverPosition.assert_not_called()


@pytest.mark.asyncio
async def test_set_cover_position_calls_manager_with_position():
    ws_manager = MagicMock()
    ws_manager.available = True
    ws_manager.setCoverPosition = AsyncMock()
    entity = KseniaRollEntity(ws_manager, "1", "Blind", {"ID": "1", "POS": "0"})
    entity.async_write_ha_state = MagicMock()

    await entity.async_set_cover_position(position=75)

    ws_manager.setCoverPosition.assert_called_once_with("1", 75)


# ============================================================================
# Misc properties
# ============================================================================


def test_is_closed_true_at_zero():
    entity = KseniaRollEntity(MagicMock(), "1", "Blind", {"ID": "1", "POS": "0"})
    entity._position = 0
    assert entity.is_closed is True


def test_is_closed_false_when_open():
    entity = KseniaRollEntity(MagicMock(), "1", "Blind", {"ID": "1", "POS": "50"})
    entity._position = 50
    assert entity.is_closed is False


def test_extra_state_attributes_includes_raw_data():
    entity = KseniaRollEntity(MagicMock(), "1", "Blind", {"ID": "1", "POS": "0", "DES": "Blind"})
    assert entity.extra_state_attributes["raw_data"]["DES"] == "Blind"


def test_supported_features_includes_position():
    from homeassistant.components.cover import CoverEntityFeature

    entity = KseniaRollEntity(MagicMock(), "1", "Blind", {"ID": "1", "POS": "0"})
    assert entity.supported_features & CoverEntityFeature.SET_POSITION
    assert entity.supported_features & CoverEntityFeature.OPEN
    assert entity.supported_features & CoverEntityFeature.CLOSE
    assert entity.supported_features & CoverEntityFeature.STOP
