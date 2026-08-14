# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
"""Tests for atomic state persistence.

The original implementation opened the target with O_TRUNC and then called os.fchmod, which
raises EPERM on volumes that do not permit chmod. The truncate had already happened, so every
shutdown left a 0-byte .dat and every start restored nothing.
"""

import json
import os
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from govee2mqtt.base import Base


class FakeService(Base):
    def __init__(self, config_path):
        self.config = {"config_path": str(config_path)}
        self.logger = MagicMock()
        self.api_calls = 42
        self.last_call_date = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


@pytest.fixture
def svc(tmp_path):
    return FakeService(tmp_path)


def _dat(tmp_path):
    return tmp_path / "govee2mqtt.dat"


class TestSaveState:
    def test_writes_readable_state(self, svc, tmp_path):
        svc.save_state()

        data = json.loads(_dat(tmp_path).read_text())
        assert data["api_calls"] == 42

    def test_leaves_no_temp_file_behind(self, svc, tmp_path):
        svc.save_state()

        assert list(tmp_path.glob("*.tmp")) == []

    def test_a_failed_save_does_not_destroy_existing_state(self, svc, tmp_path, monkeypatch):
        """The whole point: the previous version truncated first and lost everything."""
        svc.save_state()
        original = _dat(tmp_path).read_text()
        assert original.strip()

        def boom(*a, **k):
            raise PermissionError(1, "Operation not permitted")

        monkeypatch.setattr(os, "replace", boom)
        svc.api_calls = 99
        svc.save_state()

        assert _dat(tmp_path).read_text() == original
        svc.logger.error.assert_called_once()

    def test_a_failed_save_cleans_up_its_temp_file(self, svc, tmp_path, monkeypatch):
        monkeypatch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))

        svc.save_state()

        assert list(tmp_path.glob("*.tmp")) == []

    def test_does_not_chmod_an_existing_file(self, svc, tmp_path, monkeypatch):
        """os.fchmod on a file owned by another uid is what raised EPERM in production."""
        called = []
        monkeypatch.setattr(os, "fchmod", lambda *a, **k: called.append(a))

        svc.save_state()
        svc.save_state()

        assert called == []


class TestRoundTrip:
    def test_state_survives_save_and_restore(self, svc, tmp_path):
        svc.save_state()
        svc.restore_state_values = MagicMock()

        svc.restore_state()

        svc.restore_state_values.assert_called_once()
        assert svc.restore_state_values.call_args.args[0] == 42
