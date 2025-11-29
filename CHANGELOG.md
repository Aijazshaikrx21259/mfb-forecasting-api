# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- Alert system for in-app notifications (US #11, #17)
  - Alert CRUD endpoints
  - Alert preferences management
  - Alert generation triggers
  - Alert templates
- Forecast adjustment system (US #18)
  - Manual forecast overrides
  - Approval workflow
  - Adjustment templates
  - Audit trail
- System metrics and performance tracking (US #22)
  - Metrics middleware
  - System metrics endpoint
  - Cost estimation endpoint
- Comprehensive test suite
  - Unit tests for alerts
  - Unit tests for adjustments
  - Unit tests for utilities
  - Test fixtures and mocks
- Documentation
  - API guide
  - Deployment guide
  - Architecture overview
  - Contributing guidelines
- Utility functions
  - Date helpers
  - Input validators
  - Custom exceptions
- CI/CD pipeline
  - GitHub Actions workflow
  - Automated testing
  - Code coverage reporting

### Changed
- Updated README with feature list
- Enhanced requirements.txt with missing dependencies
- Improved error handling

### Fixed
- Various bug fixes and improvements

## [0.1.0] - 2024-11-29

### Added
- Initial release
- Forecasting pipeline (ETS, Croston-SBA, TSB)
- Backtest endpoints
- Data quality management
- Health check endpoint
- Docker support
- Render deployment configuration
