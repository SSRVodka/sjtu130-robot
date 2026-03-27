"""tests/test_probe.py — Unit tests for ProbeServer endpoints."""

import sys, os, time, json, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch
import urllib.request
import urllib.error

from config import Config, RobotConfig, AudioConfig, ProbeConfig, Waypoint
from tour_controller import TourController, TourState
from probe import ProbeServer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_config():
    return Config(
        robot=RobotConfig(host="10.0.0.1"),
        probe=ProbeConfig(),
        audio=AudioConfig(),
        waypoints=[
            Waypoint(name="Hall A", point="hall_a", dwell_time=30, audio_file="a.mp3"),
            Waypoint(name="Hall B", point="hall_b", dwell_time=30, audio_file="b.mp3"),
        ],
    )


def make_controller():
    client = MagicMock()
    client.get_pose.return_value = MagicMock(x=1.0, y=2.0, theta=0.5)
    return TourController(config=make_config(), client=client)


def start_probe(controller) -> tuple[ProbeServer, int]:
    port = free_port()
    probe = ProbeServer("127.0.0.1", port, controller)
    probe.start()
    time.sleep(0.1)   # let server thread bind
    return probe, port


def get(port, path) -> tuple[int, dict]:
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def put(port, path) -> tuple[int, dict]:
    url = f"http://127.0.0.1:{port}{path}"
    req = urllib.request.Request(url, method="PUT", data=b"")
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------


class TestGetStatus:
    def setup_method(self):
        self.ctrl = make_controller()
        self.probe, self.port = start_probe(self.ctrl)

    def teardown_method(self):
        self.probe.stop()

    def test_returns_200(self):
        code, _ = get(self.port, "/status")
        assert code == 200

    def test_idle_state_fields(self):
        _, body = get(self.port, "/status")
        assert body["current_waypoint"] is None
        assert body["audio_playing"] is False
        assert body["robot_waiting"] is False

    def test_robot_location_populated(self):
        _, body = get(self.port, "/status")
        loc = body["robot_location"]
        assert loc["x"] == 1.0
        assert loc["y"] == 2.0
        assert loc["theta"] == 0.5

    def test_robot_location_none_on_client_error(self):
        with patch.object(self.ctrl.client, "get_pose", side_effect=Exception("unreachable")):
            _, body = get(self.port, "/status")
            assert body["robot_location"] is None

    def test_reflects_navigating_state(self):
        self.ctrl.state.update(phase="navigating", waypoint="Hall A")
        _, body = get(self.port, "/status")
        assert body["current_waypoint"] == "Hall A"
        assert body["robot_waiting"] is False

    def test_robot_waiting_true_when_dwelling(self):
        self.ctrl.state.update(phase="dwelling", waypoint="Hall A")
        _, body = get(self.port, "/status")
        assert body["robot_waiting"] is True

    def test_audio_playing_reflected(self):
        self.ctrl.state.update(audio_playing=True)
        _, body = get(self.port, "/status")
        assert body["audio_playing"] is True

    def test_unknown_path_returns_404(self):
        code, _ = get(self.port, "/unknown")
        assert code == 404


# ---------------------------------------------------------------------------
# PUT /tour
# ---------------------------------------------------------------------------


class TestPutTour:
    def setup_method(self):
        self.ctrl = make_controller()
        self.ctrl.start()
        self.probe, self.port = start_probe(self.ctrl)

    def teardown_method(self):
        self.ctrl.shutdown()
        self.probe.stop()

    def test_valid_waypoint_returns_200(self):
        code, body = put(self.port, "/tour?dst=Hall+A")
        assert code == 200
        assert body["jumping_to"] == "Hall A"

    def test_unknown_waypoint_returns_404(self):
        code, body = put(self.port, "/tour?dst=Nonexistent")
        assert code == 404
        assert "available" in body

    def test_missing_dst_returns_400(self):
        code, body = put(self.port, "/tour")
        assert code == 400

    def test_jump_to_called_on_valid_request(self):
        with patch.object(self.ctrl, "jump_to", wraps=self.ctrl.jump_to) as mock_jt:
            put(self.port, "/tour?dst=Hall+B")
            mock_jt.assert_called_once_with("Hall B")
    
    def test_reset_called_on_reset_request(self):
        with patch.object(self.ctrl, "reset", wraps=self.ctrl.reset) as mock_reset:
            put(self.port, "/reset")
            mock_reset.assert_called_once()

    def test_unknown_path_returns_404(self):
        code, _ = put(self.port, "/unknown")
        assert code == 404
