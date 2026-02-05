"""Ksenia Lares Integration Test Suite

This package contains comprehensive integration tests for the Ksenia Lares 4.0 Home Assistant addon.

Test Modules:
- test_websocket_manager: WebSocket connection and reconnection tests
- test_sensor: Sensor entity tests (alarm trigger status, last alarm event, etc.)
- test_switch: Switch/output control tests
- test_light: Light entity tests
- test_cover: Cover/roller shutter tests
- test_button: Button/action tests
- test_scenarios: Scenario execution tests
- test_config_flow: Configuration flow tests
- test_integration: End-to-end integration tests

Running Tests:
    pytest tests/                          # Run all tests
    pytest tests/ --cov=custom_components.ksenia_lares  # With coverage
    ./run_tests.sh --coverage              # Using helper script
    pytest tests/test_sensor.py            # Run specific module
    pytest tests/test_sensor.py::test_alarm_trigger_status_sensor_not_triggered  # Run specific test

For more information, see tests/README.md and TESTING.md
"""

__version__ = "1.0.0"
