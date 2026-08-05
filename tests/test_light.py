"""Tests for the light platform: setup, listener-based discovery, and realtime-update edge cases."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ksenia_lares.const import DOMAIN
from custom_components.ksenia_lares.light import KseniaLightEntity, async_setup_entry


def _hass_with_ws_manager(ws_manager):
    hass = MagicMock()
    hass.data = {DOMAIN: {"ws_manager": ws_manager, "device_info": None, "mac": "AA:BB:CC"}}
    return hass


# ============================================================================
# async_setup_entry
# ============================================================================


@pytest.mark.asyncio
async def test_async_setup_entry_creates_entity_per_light():
    ws_manager = MagicMock()
    ws_manager.getLights = AsyncMock(return_value=[{"ID": "1", "DES": "Kitchen", "STA": "off"}])
    ws_manager.register_listener = MagicMock()
    hass = _hass_with_ws_manager(ws_manager)
    async_add_entities = MagicMock()

    await async_setup_entry(hass, MagicMock(), async_add_entities)

    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args[0][0]
    assert len(entities) == 1
    assert entities[0]._id == "1"


@pytest.mark.asyncio
async def test_discovery_listener_adds_only_new_lights():
    ws_manager = MagicMock()
    ws_manager.getLights = AsyncMock(return_value=[{"ID": "1", "DES": "Kitchen", "STA": "off"}])
    ws_manager.register_listener = MagicMock()
    hass = _hass_with_ws_manager(ws_manager)
    async_add_entities = MagicMock()

    await async_setup_entry(hass, MagicMock(), async_add_entities)
    discovery_callback = ws_manager.register_listener.call_args[0][1]

    ws_manager.getLights = AsyncMock(
        return_value=[
            {"ID": "1", "DES": "Kitchen", "STA": "off"},
            {"ID": "2", "DES": "Hallway", "STA": "off"},
        ]
    )
    async_add_entities.reset_mock()

    await discovery_callback([])

    async_add_entities.assert_called_once()
    new_entities = async_add_entities.call_args[0][0]
    assert len(new_entities) == 1
    assert new_entities[0]._id == "2"


@pytest.mark.asyncio
async def test_discovery_listener_swallows_exceptions():
    ws_manager = MagicMock()
    ws_manager.getLights = AsyncMock(return_value=[])
    ws_manager.register_listener = MagicMock()
    hass = _hass_with_ws_manager(ws_manager)

    await async_setup_entry(hass, MagicMock(), MagicMock())
    discovery_callback = ws_manager.register_listener.call_args[0][1]

    ws_manager.getLights = AsyncMock(side_effect=RuntimeError("boom"))

    await discovery_callback([])  # should not raise


@pytest.mark.asyncio
async def test_async_setup_entry_handles_exception_gracefully():
    ws_manager = MagicMock()
    ws_manager.getLights = AsyncMock(side_effect=RuntimeError("boom"))
    hass = _hass_with_ws_manager(ws_manager)
    async_add_entities = MagicMock()

    await async_setup_entry(hass, MagicMock(), async_add_entities)

    async_add_entities.assert_not_called()


# ============================================================================
# KseniaLightEntity realtime update
# ============================================================================


@pytest.mark.asyncio
async def test_handle_realtime_update_without_sta_only_updates_raw_data():
    ws_manager = MagicMock()
    entity = KseniaLightEntity(ws_manager, {"ID": "1", "STA": "off"})
    entity.async_write_ha_state = MagicMock()

    await entity._handle_realtime_update([{"ID": "1", "OTHER": "field"}])

    assert entity.is_on is False
    entity.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_handle_realtime_update_suppressed_during_pending_window():
    ws_manager = MagicMock()
    entity = KseniaLightEntity(ws_manager, {"ID": "1", "STA": "off"})
    entity.async_write_ha_state = MagicMock()
    entity._pending_command = ("on", time.time())

    await entity._handle_realtime_update([{"ID": "1", "STA": "on"}])

    # Realtime says "on" but local pending command should win within the window;
    # since entity's own local state was already True from async_turn_on, this
    # verifies the update path returns early without writing state.
    entity.async_write_ha_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_realtime_update_applies_after_pending_window_expires():
    ws_manager = MagicMock()
    entity = KseniaLightEntity(ws_manager, {"ID": "1", "STA": "off"})
    entity.async_write_ha_state = MagicMock()
    entity._pending_command = ("on", time.time() - 10)

    await entity._handle_realtime_update([{"ID": "1", "STA": "on"}])

    assert entity.is_on is True
    assert entity._pending_command is None
    entity.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_handle_realtime_update_ignores_other_ids():
    ws_manager = MagicMock()
    entity = KseniaLightEntity(ws_manager, {"ID": "1", "STA": "off"})
    entity.async_write_ha_state = MagicMock()

    await entity._handle_realtime_update([{"ID": "999", "STA": "on"}])

    assert entity.is_on is False
    entity.async_write_ha_state.assert_not_called()


# ============================================================================
# Availability guards / color mode
# ============================================================================


@pytest.mark.asyncio
async def test_turn_on_noop_when_unavailable():
    ws_manager = MagicMock()
    ws_manager.available = False
    ws_manager.turnOnOutput = AsyncMock()
    entity = KseniaLightEntity(ws_manager, {"ID": "1", "STA": "off"})

    await entity.async_turn_on()

    ws_manager.turnOnOutput.assert_not_called()


@pytest.mark.asyncio
async def test_turn_off_noop_when_unavailable():
    ws_manager = MagicMock()
    ws_manager.available = False
    ws_manager.turnOffOutput = AsyncMock()
    entity = KseniaLightEntity(ws_manager, {"ID": "1", "STA": "on"})

    await entity.async_turn_off()

    ws_manager.turnOffOutput.assert_not_called()


def test_color_mode_is_onoff():
    from homeassistant.components.light.const import ColorMode

    entity = KseniaLightEntity(MagicMock(), {"ID": "1", "STA": "off"})

    assert entity.color_mode == ColorMode.ONOFF
    assert entity.supported_color_modes == {ColorMode.ONOFF}


def test_name_fallback_when_no_des():
    entity = KseniaLightEntity(MagicMock(), {"ID": "7", "STA": "off"})

    assert entity._attr_name == "Light 7"
