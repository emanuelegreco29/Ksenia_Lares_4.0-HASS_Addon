"""Tests for the config/reconfigure flow: host validation, connection testing,
and the user/reconfigure steps' success and error paths.

test_addon_core.py already covers the options flow (Arm Home/Night scenario
selection, scan interval validation). This file covers the initial
KseniaConfigFlow (add/reconfigure a device), which had zero direct coverage.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ksenia_lares.config_flow import (
    KseniaConfigFlow,
    KseniaOptionsFlowHandler,
)
from custom_components.ksenia_lares.const import CONF_HOST, CONF_PIN, CONF_PORT, CONF_SSL
from custom_components.ksenia_lares.websocketmanager import AuthenticationError


def _user_input(**overrides):
    data = {
        CONF_HOST: "192.168.1.50",
        CONF_PIN: "123456",
        CONF_PORT: 443,
        CONF_SSL: True,
        "brand": "ksenia",
        "platforms": ["light"],
    }
    data.update(overrides)
    return data


# ============================================================================
# _validate_host
# ============================================================================


def test_validate_host_accepts_valid_ipv4():
    assert KseniaConfigFlow._validate_host("192.168.1.1") is True


def test_validate_host_rejects_hostname():
    assert KseniaConfigFlow._validate_host("not-an-ip") is False


def test_validate_host_rejects_none():
    assert KseniaConfigFlow._validate_host(None) is False


# ============================================================================
# _test_connection
# ============================================================================


@pytest.mark.asyncio
async def test_test_connection_success_returns_empty_errors():
    flow = KseniaConfigFlow()
    mock_manager = MagicMock()
    mock_manager.connectSecure = AsyncMock()
    mock_manager.stop = AsyncMock()

    with patch(
        "custom_components.ksenia_lares.config_flow.WebSocketManager", return_value=mock_manager
    ):
        errors = await flow._test_connection(_user_input())

    assert errors == {}
    mock_manager.stop.assert_called_once()


@pytest.mark.asyncio
async def test_test_connection_uses_plain_connect_when_ssl_false():
    flow = KseniaConfigFlow()
    mock_manager = MagicMock()
    mock_manager.connect = AsyncMock()
    mock_manager.connectSecure = AsyncMock()
    mock_manager.stop = AsyncMock()

    with patch(
        "custom_components.ksenia_lares.config_flow.WebSocketManager", return_value=mock_manager
    ):
        await flow._test_connection(_user_input(**{CONF_SSL: False}))

    mock_manager.connect.assert_called_once()
    mock_manager.connectSecure.assert_not_called()


@pytest.mark.asyncio
async def test_test_connection_auth_failure_returns_invalid_pin_error():
    flow = KseniaConfigFlow()
    mock_manager = MagicMock()
    mock_manager.connectSecure = AsyncMock(side_effect=AuthenticationError("bad pin"))
    mock_manager.stop = AsyncMock()

    with patch(
        "custom_components.ksenia_lares.config_flow.WebSocketManager", return_value=mock_manager
    ):
        errors = await flow._test_connection(_user_input())

    assert errors == {CONF_PIN: "invalid_pin"}


@pytest.mark.asyncio
async def test_test_connection_generic_failure_returns_cannot_connect():
    flow = KseniaConfigFlow()
    mock_manager = MagicMock()
    mock_manager.connectSecure = AsyncMock(side_effect=ConnectionError("refused"))
    mock_manager.stop = AsyncMock()

    with patch(
        "custom_components.ksenia_lares.config_flow.WebSocketManager", return_value=mock_manager
    ):
        errors = await flow._test_connection(_user_input())

    assert errors == {"base": "cannot_connect"}


@pytest.mark.asyncio
async def test_test_connection_always_stops_manager_even_on_failure():
    flow = KseniaConfigFlow()
    mock_manager = MagicMock()
    mock_manager.connectSecure = AsyncMock(side_effect=RuntimeError("boom"))
    mock_manager.stop = AsyncMock()

    with patch(
        "custom_components.ksenia_lares.config_flow.WebSocketManager", return_value=mock_manager
    ):
        await flow._test_connection(_user_input())

    mock_manager.stop.assert_called_once()


# ============================================================================
# async_step_user
# ============================================================================


@pytest.mark.asyncio
async def test_async_step_user_shows_form_when_no_input():
    flow = KseniaConfigFlow()

    result = await flow.async_step_user(user_input=None)

    assert result["type"] == "form"
    assert result["step_id"] == "user"


@pytest.mark.asyncio
async def test_async_step_user_invalid_host_shows_error():
    flow = KseniaConfigFlow()

    result = await flow.async_step_user(user_input=_user_input(**{CONF_HOST: "not-an-ip"}))

    assert result["type"] == "form"
    assert result["errors"][CONF_HOST] == "invalid_host"


@pytest.mark.asyncio
async def test_async_step_user_creates_entry_on_success():
    flow = KseniaConfigFlow()
    mock_manager = MagicMock()
    mock_manager.connectSecure = AsyncMock()
    mock_manager.stop = AsyncMock()

    with patch(
        "custom_components.ksenia_lares.config_flow.WebSocketManager", return_value=mock_manager
    ):
        result = await flow.async_step_user(user_input=_user_input())

    assert result["type"] == "create_entry"
    assert result["title"] == "Ksenia @ 192.168.1.50"


@pytest.mark.asyncio
async def test_async_step_user_connection_failure_redisplays_form_with_input():
    flow = KseniaConfigFlow()
    mock_manager = MagicMock()
    mock_manager.connectSecure = AsyncMock(side_effect=ConnectionError("refused"))
    mock_manager.stop = AsyncMock()

    with patch(
        "custom_components.ksenia_lares.config_flow.WebSocketManager", return_value=mock_manager
    ):
        result = await flow.async_step_user(user_input=_user_input())

    assert result["type"] == "form"
    assert result["errors"]["base"] == "cannot_connect"


# ============================================================================
# async_step_reconfigure
# ============================================================================


@pytest.mark.asyncio
async def test_async_step_reconfigure_aborts_when_entry_not_found():
    flow = KseniaConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config_entries.async_get_entry = MagicMock(return_value=None)
    flow.context = {"entry_id": "missing"}

    result = await flow.async_step_reconfigure(user_input=None)

    assert result["type"] == "abort"
    assert result["reason"] == "entry_not_found"


@pytest.mark.asyncio
async def test_async_step_reconfigure_invalid_host_shows_error():
    flow = KseniaConfigFlow()
    config_entry = MagicMock()
    config_entry.data = _user_input()
    flow.hass = MagicMock()
    flow.hass.config_entries.async_get_entry = MagicMock(return_value=config_entry)
    flow.context = {"entry_id": "e1"}

    result = await flow.async_step_reconfigure(
        user_input=_user_input(**{CONF_HOST: "not-an-ip"})
    )

    assert result["type"] == "form"
    assert result["errors"][CONF_HOST] == "invalid_host"


@pytest.mark.asyncio
async def test_async_step_reconfigure_success_updates_and_reloads():
    flow = KseniaConfigFlow()
    config_entry = MagicMock()
    config_entry.data = _user_input()
    config_entry.entry_id = "e1"
    flow.hass = MagicMock()
    flow.hass.config_entries.async_get_entry = MagicMock(return_value=config_entry)
    flow.hass.config_entries.async_update_entry = MagicMock()
    flow.hass.config_entries.async_reload = AsyncMock()
    flow.context = {"entry_id": "e1"}

    mock_manager = MagicMock()
    mock_manager.connectSecure = AsyncMock()
    mock_manager.stop = AsyncMock()

    with patch(
        "custom_components.ksenia_lares.config_flow.WebSocketManager", return_value=mock_manager
    ):
        result = await flow.async_step_reconfigure(user_input=_user_input())

    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    flow.hass.config_entries.async_update_entry.assert_called_once()
    flow.hass.config_entries.async_reload.assert_called_once_with("e1")


# ============================================================================
# async_get_options_flow
# ============================================================================


def test_async_get_options_flow_returns_handler_instance():
    result = KseniaConfigFlow.async_get_options_flow(MagicMock())

    assert isinstance(result, KseniaOptionsFlowHandler)
