#!/usr/bin/env bash

export ENV_FILE=.env.test
export DATABASE_URL="sqlite:///check.db"

rm -f check.db

uv run alembic upgrade head
uv run alembic check
