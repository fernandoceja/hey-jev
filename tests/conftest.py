"""Every test runs with the Mac hardware guard installed."""
import pytest

from tests.mac_guard import install


@pytest.fixture(autouse=True)
def block_real_mac_hardware(monkeypatch):
    install(monkeypatch)
