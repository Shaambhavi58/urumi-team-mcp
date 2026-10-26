"""Tests use an isolated temporary DB and initialize before user fixtures."""

import os
import tempfile
from pathlib import Path

import pytest

_test_root = tempfile.TemporaryDirectory(prefix="urumi-tests-")
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(_test_root.name) / "tests.db")


@pytest.fixture(scope="session", autouse=True)
def database_schema():
    from app.database import init_database

    init_database()
