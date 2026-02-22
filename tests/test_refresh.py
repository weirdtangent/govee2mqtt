# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from govee2mqtt.mixins.refresh import RefreshMixin
from govee2mqtt.mixins.helpers import HelpersMixin


class FakeRefresher(HelpersMixin, RefreshMixin):
    def __init__(self):
        self.logger = MagicMock()
        self.running = True
        self.device_interval = 30
        self.device_boost_interval = 5
        self.discovery_complete = True
        self.devices = {}
        self.states = {}
        self.boosted = []

    async def build_device_states(self, device_id, data=None):
        pass

    async def get_device(self, device_id):
        return {}


class TestRefreshAllDevices:
    @pytest.mark.asyncio
    async def test_waits_for_discovery_gate(self):
        r = FakeRefresher()
        r.discovery_complete = False
        r.devices = {"LIGHT001": {}}
        r.build_device_states = AsyncMock()

        call_count = 0

        async def mock_sleep(seconds):
            nonlocal call_count
            call_count += 1
            r.discovery_complete = True

        with patch("govee2mqtt.mixins.refresh.asyncio.sleep", side_effect=mock_sleep):
            await r.refresh_all_devices()

        assert call_count == 1
        r.build_device_states.assert_called_once()

    @pytest.mark.asyncio
    async def test_excludes_boosted_devices(self):
        r = FakeRefresher()
        r.devices = {"LIGHT001": {}, "LIGHT002": {}, "LIGHT003": {}}
        r.boosted = ["LIGHT002"]
        r.build_device_states = AsyncMock()

        await r.refresh_all_devices()

        # LIGHT002 is boosted, should be excluded
        assert r.build_device_states.call_count == 2
        called_ids = [c.args[0] for c in r.build_device_states.call_args_list]
        assert "LIGHT002" not in called_ids

    @pytest.mark.asyncio
    async def test_gather_pattern(self):
        r = FakeRefresher()
        r.devices = {"LIGHT001": {}, "LIGHT002": {}}
        r.build_device_states = AsyncMock()

        await r.refresh_all_devices()

        assert r.build_device_states.call_count == 2


class TestRefreshBoostedDevices:
    @pytest.mark.asyncio
    async def test_refreshes_boosted_devices(self):
        r = FakeRefresher()
        r.devices = {"LIGHT001": {}, "LIGHT002": {}}
        r.boosted = ["LIGHT001"]
        r.build_device_states = AsyncMock()

        await r.refresh_boosted_devices()

        r.build_device_states.assert_called_once_with("LIGHT001")

    @pytest.mark.asyncio
    async def test_removes_processed_items_from_boosted(self):
        r = FakeRefresher()
        r.devices = {"LIGHT001": {}}
        r.boosted = ["LIGHT001"]
        r.build_device_states = AsyncMock()

        await r.refresh_boosted_devices()

        assert len(r.boosted) == 0

    @pytest.mark.asyncio
    async def test_multi_item_boosted_skips_during_iteration(self):
        """Exposes list-mutation-during-iteration: only first item is processed."""
        r = FakeRefresher()
        r.devices = {"LIGHT001": {}, "LIGHT002": {}}
        r.boosted = ["LIGHT001", "LIGHT002"]
        r.build_device_states = AsyncMock()

        await r.refresh_boosted_devices()

        # Code mutates list during iteration — only LIGHT001 is processed
        assert r.build_device_states.call_count == 1
        r.build_device_states.assert_called_once_with("LIGHT001")
        assert r.boosted == ["LIGHT002"]

    @pytest.mark.asyncio
    async def test_skips_when_no_boosted(self):
        r = FakeRefresher()
        r.devices = {"LIGHT001": {}}
        r.boosted = []
        r.build_device_states = AsyncMock()

        await r.refresh_boosted_devices()

        r.build_device_states.assert_not_called()

    @pytest.mark.asyncio
    async def test_waits_for_discovery_gate(self):
        r = FakeRefresher()
        r.discovery_complete = False
        r.boosted = ["LIGHT001"]
        r.build_device_states = AsyncMock()

        call_count = 0

        async def mock_sleep(seconds):
            nonlocal call_count
            call_count += 1
            r.discovery_complete = True

        with patch("govee2mqtt.mixins.refresh.asyncio.sleep", side_effect=mock_sleep):
            await r.refresh_boosted_devices()

        assert call_count == 1
