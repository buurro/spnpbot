#!/bin/bash
# Convenience script to run all checks locally before committing

set -e  # Exit on error

echo "🔍 Running all checks..."
echo ""

echo "📦 Installing dependencies..."
uv sync
echo ""

echo "🎨 Running ruff linter..."
uv run ruff check .
echo "✅ Ruff linter passed"
echo ""

echo "✨ Running ruff formatter..."
uv run ruff format --check .
echo "✅ Ruff formatter passed"
echo ""

echo "🔬 Running ty type checker..."
uv run ty check .
echo "✅ Type checking passed"
echo ""

echo "🧪 Running tests with coverage..."
uv run pytest -v
echo "✅ Tests and coverage passed"
echo ""

echo "🗄️  Checking database migrations..."
# Use .env.test for alembic commands (pydantic-settings will load it)
ENV_FILE=.env.test uv run alembic upgrade head > /dev/null 2>&1
ENV_FILE=.env.test uv run alembic check
echo "✅ Migrations are up to date"
echo ""

echo "✨ All checks passed! Ready to commit. ✨"
