"""Unit tests for T2IManager — factory, queue behavior, adapter switching."""

import time
from pathlib import Path

import pytest

from t2i.t2i_manager import T2IManager, T2IAdapterFactory
from test.mocks import MockT2IAdapter


class TestT2IAdapterFactoryRegistry:
    def test_all_registered_adapters_present(self):
        assert "comfyui" in T2IAdapterFactory._adapters
        assert "stable diffusion" in T2IAdapterFactory._adapters

    def test_unknown_adapter_raises(self):
        with pytest.raises(ValueError, match="Unsupported T2I adapter"):
            T2IAdapterFactory.create_adapter("nonexistent-t2i")

    def test_factory_can_be_injected_with_mock(self):
        """Register a mock adapter in the factory dict and create via factory."""
        T2IAdapterFactory._adapters["mock-t2i"] = MockT2IAdapter
        try:
            adapter = T2IAdapterFactory.create_adapter("mock-t2i")
            assert isinstance(adapter, MockT2IAdapter)
        finally:
            del T2IAdapterFactory._adapters["mock-t2i"]


class TestT2IManagerWithMock:
    def test_init_starts_worker(self, mock_t2i_adapter):
        mgr = T2IManager(t2i_adapter=mock_t2i_adapter)
        assert mgr.worker_thread.is_alive()
        mgr.shutdown()

    def test_set_adapter(self, mock_t2i_adapter):
        mgr = T2IManager(t2i_adapter=mock_t2i_adapter)
        new_adapter = MockT2IAdapter()
        mgr.set_t2i_adapter(new_adapter)
        assert mgr.t2i_adapter is new_adapter
        mgr.shutdown()

    def test_t2i_calls_adapter_and_writes_file(self, mock_t2i_adapter, tmp_path):
        mgr = T2IManager(t2i_adapter=mock_t2i_adapter)
        result = mgr.t2i(prompt="A beautiful sunset")
        assert result is not None
        assert Path(result).exists()
        assert len(mock_t2i_adapter.call_history) == 1
        assert mock_t2i_adapter.call_history[0]["prompt"] == "A beautiful sunset"
        mgr.shutdown()

    def test_t2i_no_adapter_returns_none(self):
        mgr = T2IManager(t2i_adapter=None)
        result = mgr.t2i(prompt="test")
        assert result is None
        mgr.shutdown()

    def test_t2i_cycles_cache_index(self, mock_t2i_adapter):
        mgr = T2IManager(t2i_adapter=mock_t2i_adapter)
        mgr.cache_num = 3
        for i in range(5):
            mgr.t2i(prompt=f"Prompt {i}")
        assert mgr.index == 5
        mgr.shutdown()

    def test_switch_model_delegates(self, mock_t2i_adapter):
        mgr = T2IManager(t2i_adapter=mock_t2i_adapter)
        mgr.switch_model({"model": "sdxl"})
        assert any("switch_model" in str(c) for c in mock_t2i_adapter.call_history)
        mgr.shutdown()

    def test_switch_model_no_adapter_noop(self):
        mgr = T2IManager(t2i_adapter=None)
        mgr.switch_model({"model": "x"})  # should not raise
        mgr.shutdown()

    def test_shutdown_terminates_worker(self, mock_t2i_adapter):
        mgr = T2IManager(t2i_adapter=mock_t2i_adapter)
        mgr.shutdown()
        mgr.worker_thread.join(timeout=2)
        assert not mgr.worker_thread.is_alive()

    def test_init_creates_cache_dir(self, mock_t2i_adapter):
        mgr = T2IManager(t2i_adapter=mock_t2i_adapter)
        assert mgr.image_cache_dir.exists()
        mgr.shutdown()

    def test_queue_generation_processes_via_t2i(self, mock_t2i_adapter):
        """queue_generation puts a task; the worker calls t2i() to handle it."""
        mgr = T2IManager(t2i_adapter=mock_t2i_adapter)
        mgr.queue_generation(prompt="Queued generation", extra_param="value")
        time.sleep(0.2)
        assert len(mock_t2i_adapter.call_history) >= 1
        mgr.shutdown()
