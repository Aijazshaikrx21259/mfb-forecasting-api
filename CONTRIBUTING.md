# Contributing to MFB Forecasting API

## Development Setup

1. **Clone the repository**
```bash
git clone https://github.com/Aijazshaikrx21259/mfb-forecasting-api.git
cd mfb-forecasting-api
```

2. **Create virtual environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

4. **Set up environment variables**
```bash
cp .env.example .env
# Edit .env with your configuration
```

5. **Run tests**
```bash
pytest tests/ -v
```

6. **Start development server**
```bash
uvicorn app.main:app --reload
```

## Code Style

- Follow PEP 8 guidelines
- Use type hints for all function parameters and return values
- Write docstrings for all public functions and classes
- Keep functions focused and under 50 lines when possible

## Testing

- Write tests for all new features
- Maintain test coverage above 80%
- Use pytest fixtures for common test data
- Mock external dependencies (database, APIs)

## Commit Messages

Follow conventional commits format:

- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `test:` - Test additions or changes
- `refactor:` - Code refactoring
- `chore:` - Maintenance tasks

Example: `feat: add alert system for forecast notifications`

## Pull Request Process

1. Create a feature branch from `main`
2. Make your changes with clear commit messages
3. Add tests for new functionality
4. Update documentation as needed
5. Run tests and ensure they pass
6. Submit PR with description of changes

## Code Review

All PRs require review before merging. Reviewers will check:

- Code quality and style
- Test coverage
- Documentation
- Performance implications
- Security considerations

## Questions?

Open an issue or contact the maintainers.
