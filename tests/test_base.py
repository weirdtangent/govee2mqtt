# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import json
import pytest
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch

from govee2mqtt.base import Base


class FakeBase(Base):
    """Minimal subclass so super() works in Base.__aenter__/__aexit__."""

    pass


class TestSaveState:
    def test_saves_json_structure(self, tmp_path):
        state_file = tmp_path / "govee2mqtt.dat"

        obj = MagicMock()
        obj.config = {"config_path": str(tmp_path)}
        obj.api_calls = 42
        obj.last_call_date = datetime(2026, 1, 15, 10, 30, 0)
        obj.logger = MagicMock()

        Base.save_state(obj)

        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["api_calls"] == 42
        assert "2026-01-15" in data["last_call_date"]

    def test_no_error_handling_raises_on_permission_error(self, tmp_path):
        """govee2mqtt save_state has no PermissionError handling — verify it raises."""
        obj = MagicMock()
        obj.config = {"config_path": "/nonexistent/readonly/path"}
        obj.api_calls = 0
        obj.last_call_date = datetime.now()
        obj.logger = MagicMock()

        with pytest.raises((PermissionError, FileNotFoundError)):
            Base.save_state(obj)


class TestRestoreState:
    def test_restores_state_from_file(self, tmp_path):
        state_file = tmp_path / "govee2mqtt.dat"
        state_file.write_text(
            json.dumps(
                {
                    "api_calls": 99,
                    "last_call_date": "2026-01-15 10:30:00.000000",
                }
            )
        )

        obj = MagicMock()
        obj.config = {"config_path": str(tmp_path)}
        obj.logger = MagicMock()

        Base.restore_state(obj)

        obj.restore_state_values.assert_called_once_with(99, "2026-01-15 10:30:00.000000")

    def test_missing_file_is_noop(self, tmp_path):
        obj = MagicMock()
        obj.config = {"config_path": str(tmp_path)}
        obj.logger = MagicMock()

        Base.restore_state(obj)
        obj.restore_state_values.assert_not_called()


class TestContextManager:
    @pytest.mark.asyncio
    async def test_aenter_creates_session_and_mqttc(self):
        obj = object.__new__(FakeBase)
        obj.logger = MagicMock()
        obj.mqttc_create = AsyncMock()
        obj.restore_state = MagicMock()
        obj.running = False

        with patch("govee2mqtt.base.aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            await Base.__aenter__(obj)

        obj.mqttc_create.assert_called_once()
        obj.restore_state.assert_called_once()
        assert obj.running is True

    @pytest.mark.asyncio
    async def test_aexit_closes_session_and_disconnects(self):
        obj = object.__new__(FakeBase)
        obj.logger = MagicMock()
        obj.running = True
        obj.save_state = MagicMock()
        obj.session = MagicMock()
        obj.session.closed = False
        obj.session.close = AsyncMock()
        obj.publish_service_availability = AsyncMock()
        obj.mqttc = MagicMock()
        obj.mqttc.is_connected.return_value = True
        obj.mqttc.loop_stop = MagicMock()
        obj.mqttc.disconnect = MagicMock()

        with patch("govee2mqtt.base.asyncio.get_running_loop") as mock_loop:
            loop = MagicMock()
            loop.is_running.return_value = True
            loop.create_task = MagicMock()
            mock_loop.return_value = loop

            await Base.__aexit__(obj, None, None, None)

        assert obj.running is False
        obj.save_state.assert_called_once()
        obj.publish_service_availability.assert_called_once_with("offline")
        obj.mqttc.disconnect.assert_called_once()
