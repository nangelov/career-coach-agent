"""Shared pytest fixtures and test-environment bootstrap.

The required settings fields (``HF_API_TOKEN``, ``DATABASE_URL``,
``JWT_SECRET_KEY`` — see ``app.config``) have no defaults and would raise on
``Settings()`` instantiation at import time. We seed harmless **dummy** values
here so the app can be imported and unit-tested without real secrets or a live
database. These are non-secret placeholders — never put real credentials here;
CI and production inject the real values via environment / HF Space Secrets.

This module runs before test collection, so the env is set before any test
module executes ``from app.main import app``.
"""

from __future__ import annotations

import os

# Use setdefault so a developer's real .env / shell values still win locally.
os.environ.setdefault("HF_API_TOKEN", "test-token")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/career_coach_test"
)
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-not-used-in-prod")
