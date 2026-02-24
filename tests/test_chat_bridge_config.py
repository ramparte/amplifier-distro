"""Tests for BridgeConfig behaviors and show_thinking fields."""

from __future__ import annotations

import pathlib

from amplifier_distro.bridge import BridgeConfig


class TestBridgeConfigNewFields:
    def test_behaviors_default_is_none(self):
        config = BridgeConfig()
        assert config.behaviors is None

    def test_behaviors_can_be_set(self):
        config = BridgeConfig(behaviors=["web-search", "file-ops"])
        assert config.behaviors == ["web-search", "file-ops"]

    def test_show_thinking_default_is_false(self):
        config = BridgeConfig()
        assert config.show_thinking is False

    def test_show_thinking_can_be_set(self):
        config = BridgeConfig(show_thinking=True)
        assert config.show_thinking is True

    def test_existing_fields_still_work(self):
        config = BridgeConfig(
            working_dir=pathlib.Path("/tmp"),
            bundle_name="my-bundle",
            behaviors=["tool-a"],
            show_thinking=True,
        )
        assert config.working_dir == pathlib.Path("/tmp")
        assert config.bundle_name == "my-bundle"
        assert config.behaviors == ["tool-a"]
        assert config.show_thinking is True
