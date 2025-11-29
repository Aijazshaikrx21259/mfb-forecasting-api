# PowerShell script to run tests with coverage

Write-Host "Running tests with coverage..." -ForegroundColor Green
pytest tests/ -v --cov=app --cov-report=term --cov-report=html

Write-Host ""
Write-Host "Coverage report generated in htmlcov/index.html" -ForegroundColor Cyan
Write-Host ""
Write-Host "Test summary:" -ForegroundColor Green
pytest tests/ --tb=no -q
