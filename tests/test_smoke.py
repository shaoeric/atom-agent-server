"""Import and unit tests without Redis."""

from agent_backend.runtime_spike import verify_imports


def test_runtime_spike_import():
    verify_imports()
