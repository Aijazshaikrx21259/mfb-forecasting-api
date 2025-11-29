# Testing Guide

## Running Tests

### Quick Start
```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=term --cov-report=html

# Run specific test file
pytest tests/test_alerts.py -v

# Run specific test
pytest tests/test_alerts.py::test_create_alert -v
```

### Using Scripts
```bash
# Bash
./scripts/run_tests.sh

# PowerShell
.\scripts\run_tests.ps1
```

## Test Structure

```
tests/
├── conftest.py           # Shared fixtures
├── test_health.py        # Health endpoint tests
├── test_security.py      # Authentication tests
├── test_config.py        # Configuration tests
├── test_alerts.py        # Alert system tests
├── test_adjustments.py   # Adjustment tests
└── test_utils.py         # Utility function tests
```

## Writing Tests

### Unit Tests
```python
import pytest
from app.services.alert_service import AlertService

@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_alert(mock_db_connection):
    """Test creating an alert."""
    service = AlertService(mock_db_connection)
    # Test implementation
```

### Integration Tests
```python
@pytest.mark.integration
def test_alert_endpoint(test_client, api_headers):
    """Test alert endpoint integration."""
    response = test_client.post(
        "/api/alerts",
        json={"user_id": "test"},
        headers=api_headers
    )
    assert response.status_code == 201
```

## Fixtures

### Available Fixtures
- `test_client` - FastAPI test client
- `mock_db_connection` - Mocked database connection
- `mock_db_pool` - Mocked connection pool
- `api_headers` - Headers with test API key
- `test_settings` - Test configuration

### Creating Custom Fixtures
```python
@pytest.fixture
def sample_alert():
    """Create sample alert data."""
    return {
        "user_id": "test123",
        "alert_type": "FORECAST_READY",
        "title": "Test Alert",
        "message": "Test message"
    }
```

## Mocking

### Database Mocking
```python
from unittest.mock import AsyncMock

mock_db_connection.fetchrow = AsyncMock(return_value={
    "id": 1,
    "name": "test"
})
```

### Service Mocking
```python
from unittest.mock import patch

with patch('app.services.alert_service.AlertService') as mock:
    mock.return_value.create_alert.return_value = alert_response
    # Test code
```

## Coverage

### Viewing Coverage
```bash
# Generate HTML report
pytest --cov=app --cov-report=html

# Open in browser
open htmlcov/index.html  # Mac/Linux
start htmlcov/index.html # Windows
```

### Coverage Goals
- Overall: > 80%
- Critical paths: > 90%
- New features: 100%

## Test Markers

- `@pytest.mark.unit` - Unit tests
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.slow` - Slow-running tests
- `@pytest.mark.asyncio` - Async tests

### Running Specific Markers
```bash
# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration

# Skip slow tests
pytest -m "not slow"
```

## Continuous Integration

Tests run automatically on:
- Push to main branch
- Pull requests
- GitHub Actions workflow

See `.github/workflows/test.yml` for CI configuration.

## Troubleshooting

### Common Issues

**Import errors**
```bash
# Ensure dependencies installed
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

**Database connection errors**
```bash
# Tests use mocked connections
# No real database needed for unit tests
```

**Async test failures**
```bash
# Ensure pytest-asyncio installed
pip install pytest-asyncio
```

## Best Practices

1. **Test naming** - Use descriptive names: `test_create_alert_with_valid_data`
2. **One assertion per test** - Keep tests focused
3. **Mock external dependencies** - Don't hit real APIs/databases
4. **Clean up** - Use fixtures for setup/teardown
5. **Fast tests** - Unit tests should run in milliseconds
6. **Readable** - Tests are documentation

## Resources

- [pytest documentation](https://docs.pytest.org/)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/)
