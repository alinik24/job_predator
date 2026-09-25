"""Pytest configuration and fixtures."""
import os

# Set environment variables BEFORE any imports happen
# This must run at module level, not in a fixture
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DATABASE_URL_SYNC", "sqlite:///:memory:")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("NEO4J_PASSWORD", "test-password")
