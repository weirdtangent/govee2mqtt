# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from govee2mqtt.mixins.loops import LoopsMixin
from govee2mqtt.mixins.helpers import HelpersMixin


class FakeLooper(HelpersMixin, LoopsMixin):
    def __init__(self):
        self.logger = MagicMock()
        self.running = True
        self.device_interval = 1
        self.device_list_interval = 1
        self.device_boost_interval = 1

    async def refresh_all_devices(self):
        pass

    async def refresh_device_list(self):
        pass

    async def refresh_boosted_devices(self):
        pass

    def mark_ready(self):
        pass

    def heartbeat_ready(self):
        pass


class TestDeviceLoop:
    @pytest.mark.asyncio
    async def test_sleep_first_then_check_running(self):
        looper = FakeLooper()
        call_order = []

        async def mock_sleep(seconds):
            call_order.append("sleep")
            looper.running = False

        async def mock_refresh():
            call_order.append("refresh")

        looper.refresh_all_devices = mock_refresh

        with patch("govee2mqtt.mixins.loops.asyncio.sleep", side_effect=mock_sleep):
            await looper.device_loop()

        # govee2mqtt sleeps first, then checks self.running before refreshing
        assert call_order == ["sleep"]

    @pytest.mark.asyncio
    async def test_handles_cancelled_error(self):
        looper = FakeLooper()

        with patch("govee2mqtt.mixins.loops.asyncio.sleep", side_effect=asyncio.CancelledError):
            await looper.device_loop()

        looper.logger.debug.assert_called()


class TestDeviceBoostedLoop:
    @pytest.mark.asyncio
    async def test_sleep_first_pattern(self):
        looper = FakeLooper()

        async def mock_sleep(seconds):
            looper.running = False

        looper.refresh_boosted_devices = AsyncMock()

        with patch("govee2mqtt.mixins.loops.asyncio.sleep", side_effect=mock_sleep):
            await looper.device_boosted_loop()

        # Running set to False during sleep, so refresh should NOT be called
        looper.refresh_boosted_devices.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_cancelled_error(self):
        looper = FakeLooper()

        with patch("govee2mqtt.mixins.loops.asyncio.sleep", side_effect=asyncio.CancelledError):
            await looper.device_boosted_loop()

        looper.logger.debug.assert_called()


class TestHeartbeat:
    @pytest.mark.asyncio
    async def test_sleep_first_then_check_running(self):
        looper = FakeLooper()
        heartbeat_called = False

        def mock_heartbeat():
            nonlocal heartbeat_called
            heartbeat_called = True

        looper.heartbeat_ready = mock_heartbeat

        call_count = 0

        async def mock_sleep(seconds):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                looper.running = False

        with patch("govee2mqtt.mixins.loops.asyncio.sleep", side_effect=mock_sleep):
            await looper.heartbeat()

        assert heartbeat_called

    @pytest.mark.asyncio
    async def test_handles_cancelled_error(self):
        looper = FakeLooper()

        with patch("govee2mqtt.mixins.loops.asyncio.sleep", side_effect=asyncio.CancelledError):
            await looper.heartbeat()

        looper.logger.debug.assert_called()


class TestMainLoop:
    @pytest.mark.asyncio
    async def test_uses_underscore_handle_signal(self):
        looper = FakeLooper()
        looper._handle_signal = MagicMock()
        looper.refresh_device_list = AsyncMock()

        with (
            patch("govee2mqtt.mixins.loops.signal.signal") as mock_signal,
            patch("govee2mqtt.mixins.loops.asyncio.create_task", side_effect=lambda coro, **kw: asyncio.ensure_future(coro)),
            patch("govee2mqtt.mixins.loops.asyncio.gather", new_callable=AsyncMock),
        ):
            await looper.main_loop()

        # Should use _handle_signal (underscore naming)
        assert mock_signal.call_count == 2
        for call in mock_signal.call_args_list:
            assert call.args[1] == looper._handle_signal

    @pytest.mark.asyncio
    async def test_creates_4_tasks(self):
        looper = FakeLooper()
        looper._handle_signal = MagicMock()
        looper.refresh_device_list = AsyncMock()
        created_tasks = []

        def mock_create_task(coro, **kwargs):
            created_tasks.append(kwargs.get("name", "unknown"))
            task = asyncio.ensure_future(coro)
            task.cancel()
            return task

        with (
            patch("govee2mqtt.mixins.loops.signal.signal"),
            patch("govee2mqtt.mixins.loops.asyncio.create_task", side_effect=mock_create_task),
            patch("govee2mqtt.mixins.loops.asyncio.gather", new_callable=AsyncMock),
        ):
            await looper.main_loop()

        assert len(created_tasks) == 4
        assert "device_list_loop" in created_tasks
        assert "device_loop" in created_tasks
        assert "device_boosted_loop" in created_tasks
        assert "heartbeat" in created_tasks
