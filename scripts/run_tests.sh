#!/bin/bash
# Script to run tests with coverage

set -e

echo "Running tests with coverage..."
pytest tests/ -v --cov=app --cov-report=term --cov-report=html

echo ""
echo "Coverage report generated in htmlcov/index.html"
echo ""
echo "Test summary:"
pytest tests/ --tb=no -q
