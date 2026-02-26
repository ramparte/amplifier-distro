"""Tests for voice app static/index.html

Verifies that the Preact voice app index.html exists with all required
elements from the spec:

  TestIndexFileExists       - file present at correct path
  TestIndexContent          - required JS hooks, components, CSS present
  TestIndexRouteServesFile  - GET /apps/voice/ serves the actual file (not placeholder)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

# Path to static/index.html (resolved relative to this test file)
_STATIC_DIR = (
    Path(__file__).parent.parent
    / "src"
    / "amplifier_distro"
    / "server"
    / "apps"
    / "voice"
    / "static"
)
INDEX_HTML = _STATIC_DIR / "index.html"


def _make_app() -> FastAPI:
    from amplifier_distro.server.app import DistroServer
    from amplifier_distro.server.apps.voice import manifest

    server = DistroServer()
    server.register_app(manifest)
    return server.app


# ---------------------------------------------------------------------------
# TestIndexFileExists
# ---------------------------------------------------------------------------


class TestIndexFileExists:
    def test_index_html_file_exists(self) -> None:
        assert INDEX_HTML.exists(), (
            f"index.html not found at {INDEX_HTML}. "
            "Task 5.2 requires creating this file."
        )

    def test_index_html_is_not_empty(self) -> None:
        assert INDEX_HTML.stat().st_size > 500, (
            "index.html appears to be empty or too small"
        )


# ---------------------------------------------------------------------------
# TestIndexContent
# ---------------------------------------------------------------------------


class TestIndexContent:
    @pytest.fixture(autouse=True)
    def content(self) -> None:
        self.html = INDEX_HTML.read_text(encoding="utf-8")

    # --- vendor.js script tag ---
    def test_loads_vendor_js(self) -> None:
        assert "vendor.js" in self.html, "index.html must load vendor.js"

    # --- useWebRTC hook ---
    def test_declares_use_web_rtc_hook(self) -> None:
        assert "useWebRTC" in self.html, "index.html must declare a useWebRTC hook"

    def test_rtc_state_declared(self) -> None:
        assert "rtcState" in self.html, "useWebRTC must maintain rtcState"

    def test_connect_function_declared(self) -> None:
        assert "connect" in self.html, "useWebRTC must expose a connect() function"

    def test_disconnect_function_declared(self) -> None:
        assert "disconnect" in self.html, (
            "useWebRTC must expose a disconnect() function"
        )

    def test_send_data_channel_message_declared(self) -> None:
        assert "sendDataChannelMessage" in self.html, (
            "useWebRTC must expose sendDataChannelMessage()"
        )

    def test_fetches_session_endpoint(self) -> None:
        assert "/apps/voice/session" in self.html, (
            "connect() must fetch /apps/voice/session for ephemeral token"
        )

    def test_posts_to_sdp_endpoint(self) -> None:
        assert "/apps/voice/sdp" in self.html, (
            "connect() must POST to /apps/voice/sdp for SDP exchange"
        )

    def test_creates_rtc_peer_connection(self) -> None:
        assert "RTCPeerConnection" in self.html, (
            "connect() must create an RTCPeerConnection"
        )

    def test_uses_stun_server(self) -> None:
        assert "stun:stun.l.google.com" in self.html, (
            "RTCPeerConnection must use Google STUN"
        )

    def test_requests_microphone(self) -> None:
        assert "getUserMedia" in self.html, "connect() must call getUserMedia for audio"

    def test_creates_data_channel(self) -> None:
        assert "oai-events" in self.html, (
            "connect() must create data channel named 'oai-events'"
        )

    # --- Two-stage VAD ---
    def test_stage1_server_vad(self) -> None:
        assert "server_vad" in self.html, (
            "Stage 1 session.update must use server_vad type"
        )

    def test_stage2_semantic_vad(self) -> None:
        assert "semantic_vad" in self.html, (
            "Stage 2 session.update must use semantic_vad type (GA constraint)"
        )

    def test_stage2_uses_settimeout(self) -> None:
        assert "setTimeout" in self.html, (
            "Stage 2 semantic_vad must be sent after setTimeout (GA API constraint)"
        )

    def test_vad_threshold(self) -> None:
        assert "threshold" in self.html, "Stage 1 VAD must include threshold config"

    def test_noise_reduction(self) -> None:
        assert "noise_reduction" in self.html or "near_field" in self.html, (
            "Stage 1 must configure noise_reduction near_field"
        )

    def test_transcription_model(self) -> None:
        assert "gpt-4o-transcribe" in self.html, (
            "Stage 1 must configure transcription with gpt-4o-transcribe"
        )

    def test_semantic_vad_eagerness(self) -> None:
        assert "eagerness" in self.html, "Stage 2 semantic_vad must set eagerness"

    # --- VoiceApp component ---
    def test_declares_voice_app_component(self) -> None:
        assert "VoiceApp" in self.html, "index.html must declare a VoiceApp component"

    def test_start_voice_chat_button(self) -> None:
        assert "Start Voice Chat" in self.html, (
            "VoiceApp must have a 'Start Voice Chat' button when idle"
        )

    def test_disconnect_button(self) -> None:
        assert "Disconnect" in self.html, (
            "VoiceApp must have a 'Disconnect' button when connected"
        )

    def test_posts_to_sessions_endpoint(self) -> None:
        assert "/apps/voice/sessions" in self.html, (
            "handleConnect must POST to /apps/voice/sessions"
        )

    def test_handle_rtc_message_placeholder(self) -> None:
        assert "handleRtcMessage" in self.html, (
            "VoiceApp must define handleRtcMessage (placeholder for Task 5.3)"
        )

    def test_console_debug_in_handler(self) -> None:
        assert "console.debug" in self.html, (
            "handleRtcMessage must call console.debug as placeholder"
        )

    # --- CSS / theme ---
    def test_dark_theme_background(self) -> None:
        assert "#1a1a1a" in self.html, "CSS must use dark theme with #1a1a1a background"

    def test_uses_system_ui_font(self) -> None:
        assert "system-ui" in self.html, "CSS must use system-ui font"

    def test_max_width_900px(self) -> None:
        assert "900px" in self.html, "CSS must set 900px max-width"

    # --- Preact wiring ---
    def test_uses_preact_render(self) -> None:
        assert "render" in self.html, "index.html must call preact render()"

    def test_uses_htm(self) -> None:
        assert "html`" in self.html or "window.html" in self.html, (
            "index.html must use htm tagged template literal"
        )

    # --- Resource cleanup (Issues 1 & 2 from quality review) ---

    def test_stream_ref_used_for_track_cleanup(self) -> None:
        assert "streamRef" in self.html, (
            "connect() must store stream in streamRef so disconnect() can stop tracks"
        )

    def test_media_stream_tracks_stopped_on_disconnect(self) -> None:
        assert ".stop()" in self.html, (
            "disconnect() must call .stop() on each MediaStream track to release mic"
        )

    def test_audio_ref_used_for_element_cleanup(self) -> None:
        assert "audioRef" in self.html, (
            "ontrack handler must store audio element in audioRef for cleanup"
        )

    def test_audio_element_removed_on_disconnect(self) -> None:
        assert ".remove()" in self.html, (
            "disconnect() must call .remove() on audio element to avoid DOM leak"
        )

    # --- Code clarity (Issues 4, 5, 6 from quality review) ---

    def test_catch_blocks_have_clarifying_comment(self) -> None:
        assert "already closed" in self.html or "ignore" in self.html.lower(), (
            "catch blocks in disconnect() should have a comment clarifying intent"
        )

    def test_sessions_post_does_not_send_empty_object(self) -> None:
        assert "JSON.stringify({})" not in self.html, (
            "Sessions POST should not send JSON.stringify({}) — use null or omit body"
        )

    def test_handle_state_change_has_task_comment(self) -> None:
        assert "5.3" in self.html, (
            "handleStateChange should reference Task 5.3 to clarify its purpose"
        )


# ---------------------------------------------------------------------------
# TestIndexRouteServesFile
# ---------------------------------------------------------------------------


class TestIndexRouteServesFile:
    def setup_method(self) -> None:
        self.client = TestClient(_make_app(), raise_server_exceptions=False)

    def test_index_route_returns_200(self) -> None:
        resp = self.client.get("/apps/voice/")
        assert resp.status_code == 200

    def test_index_route_serves_actual_file(self) -> None:
        """Verify the route serves the real file, not the placeholder."""
        resp = self.client.get("/apps/voice/")
        assert "not built yet" not in resp.text, (
            "Route must serve the real index.html, not the build placeholder"
        )

    def test_index_route_contains_voice_app(self) -> None:
        resp = self.client.get("/apps/voice/")
        assert "VoiceApp" in resp.text or "Start Voice Chat" in resp.text
