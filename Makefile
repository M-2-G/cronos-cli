.PHONY: help install run dev clean test

help:  ## Show available commands
	@echo "Cronos CLI - Available commands:"
	@echo ""
	@echo "  make install   Install dependencies via uv"
	@echo "  make run       Run the application"
	@echo "  make dev       Install and run"
	@echo "  make clean     Clean generated files (.venv, __pycache__, data)"
	@echo "  make test      Run tests"
	@echo "  make help      Show this help"

install:  ## Install dependencies via uv
	uv sync

run:  ## Run the application
	uv run cronos-cli

dev: install run  ## Install and run

clean:  ## Clean generated files
	rm -rf .venv
	rm -rf data/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

test:  ## Run tests
	uv run pytest tests/ -v
