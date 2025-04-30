.PHONY: setup test lint format docs clean

# Python version
PYTHON = python3.11

# Virtual environment
VENV = .venv
VENV_BIN = $(VENV)/bin

# Setup
setup:
	@echo "Installing Uv..."
	@curl -LsSf https://astral.sh/uv/install.sh | sh
	@echo "Creating virtual environment..."
	@uv venv
	@echo "Installing dependencies..."
	@. .venv/bin/activate && uv pip install -e .[dev]
	@echo "Setup complete! Activate your virtual environment with: . .venv/bin/activate"

install:
	@. .venv/bin/activate && uv pip install -e .[dev]

# Testing
test:
	@. .venv/bin/activate && python -m pytest -v -s tests/

test-cov:
	@. .venv/bin/activate && python -m pytest --cov=querymate --cov-report=term-missing tests/

# Linting and formatting
lint:
	@. .venv/bin/activate && ruff check querymate/ tests/
	@. .venv/bin/activate && mypy querymate/ tests/

format:
	@. .venv/bin/activate && black querymate/ tests/
	@. .venv/bin/activate && isort querymate/ tests/
	@. .venv/bin/activate && ruff format querymate/ tests/

# Documentation
docs:
	@. .venv/bin/activate && sphinx-build -b html docs/ docs/_build/html

# Clean
clean:
	rm -rf $(VENV)
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf .ruff_cache
	rm -rf docs/_build
	rm -rf *.egg-info
	rm -rf dist
	rm -rf build

# All checks
all-checks: lint test-cov

all: setup lint format test docs

# Default target
.DEFAULT_GOAL := help
help:
	@echo "Available targets:"
	@echo "  setup        - Set up the development environment"
	@echo "  install      - Install packages"
	@echo "  test         - Run tests"
	@echo "  test-cov     - Run tests with coverage"
	@echo "  lint         - Run linters"
	@echo "  format       - Format code"
	@echo "  docs         - Build documentation"
	@echo "  clean        - Clean up"
	@echo "  all-checks   - Run all checks"
