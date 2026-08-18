import os

import pytest


@pytest.fixture(autouse=True)
def forbid_real_gemini(monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", os.getenv("PYTEST_CURRENT_TEST", "pytest"))
