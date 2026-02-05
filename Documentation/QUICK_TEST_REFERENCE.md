# Quick Reference: Running Tests

## Installation

### Using venv (Recommended)
```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

### Docker/Container
```bash
pip install -r requirements-dev.txt
```

## Running Tests

### Script
```bash
./scripts/run_tests.sh
```

### All Tests (Simple)
```bash
pytest tests/ -q
```

### All Tests (Verbose)
```bash
pytest tests/ -v
```

### With Coverage Report
```bash
pytest tests/ --cov=custom_components/ksenia_lares --cov-report=term-missing
pytest tests/ --cov=custom_components/ksenia_lares --cov-report=html
```

### Run and Watch for Changes
```bash
pytest tests/ --cov=custom_components/ksenia_lares -v --tb=short
```

### Specific Test File
```bash
pytest tests/test_addon_core.py
```

### Specific Test Function
```bash
pytest tests/test_addon_core.py::test_ksenia_switch_entity_initialization
```

### Run Tests with Simulator
```bash
# Terminal 1: Start simulator
python tool_simulator_mockup/server.py

# Terminal 2: Run tests (tests will use simulator if available)
pytest tests/test_addon_core.py -v
```

### Verbose Debugging
```bash
# Show detailed traceback
pytest tests/ --tb=long

# Stop on first failure
pytest tests/ -x

# Show print/logging output
pytest tests/ -v -s

# Use Python debugger on failure
pytest tests/ --pdb
```

## Key Fixtures

All available in `conftest.py`:

- `mock_ws_manager` - Full WebSocket mock
- `mock_websocket` - Raw WebSocket mock
- `mock_hass` - Home Assistant mock
- `sample_partition_data` - Real partition states
- `sample_zone_data` - Real zone states
- `sample_output_data` - Real output states
- `sample_scenarios_data` - Real scenarios
- `sample_system_version` - System info

## Coverage Report

Generate HTML report:
```bash
./run_tests.sh --coverage
open htmlcov/index.html
```
