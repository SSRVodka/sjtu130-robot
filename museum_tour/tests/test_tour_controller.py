"""tests/test_tour_controller.py — Unit tests for TourController."""

import sys, os, time, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch
import pytest

from config import Config, RobotConfig, AudioConfig, ProbeConfig, Waypoint, Pose
from tour_controller import TourController, TourState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_waypoint(name="Stop", point="p", dwell_time=0, audio="a.mp3", actions=None):
    return Waypoint(name=name, point=point, dwell_time=dwell_time,
                    audio_file=audio, actions=actions or [])


def make_config(waypoints=None):
    return Config(
        robot=RobotConfig(host="10.0.0.1", nav_poll_interval=0, nav_timeout=5),
        audio=AudioConfig(),
        probe=ProbeConfig(),
        waypoints=waypoints or [make_waypoint()],
    )


def make_client(nav_ok=True):
    c = MagicMock()
    c.nav_to_name.return_value = nav_ok
    c.nav_to_pose.return_value = nav_ok
    c.wait_for_arrival.return_value = nav_ok
    c.cancel_navigation.return_value = True
    return c


def run_tour(controller, target, timeout=2.0):
    """Start controller, jump_to target, wait for 'finished', then shutdown."""
    controller.start()
    controller.jump_to(target)
    time.sleep(0.02)   # yield so controller thread can start processing
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if controller.state.snapshot()["phase"] == "finished":
            break
        time.sleep(0.05)
    controller.shutdown()


# ---------------------------------------------------------------------------
# TourState
# ---------------------------------------------------------------------------


class TestTourState:
    def test_update_and_snapshot(self):
        s = TourState()
        s.update(phase="navigating", waypoint="A")
        snap = s.snapshot()
        assert snap["phase"] == "navigating"
        assert snap["waypoint"] == "A"

    def test_thread_safe_concurrent_updates(self):
        s = TourState()
        errors = []
        def worker():
            try:
                for _ in range(100):
                    s.update(phase="navigating")
                    s.snapshot()
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert not errors


# ---------------------------------------------------------------------------
# TourController — basic flow
# ---------------------------------------------------------------------------


class TestTourControllerFlow:
    def test_idle_until_jump_to(self):
        ctrl = TourController(config=make_config(), client=make_client())
        ctrl.start()
        time.sleep(0.1)
        assert ctrl.state.snapshot()["phase"] == "idle"
        ctrl.shutdown()

    def test_single_named_waypoint(self):
        wp = make_waypoint(name="Hall A", point="hall_a")
        client = make_client()
        ctrl = TourController(config=make_config([wp]), client=client)
        with patch("tour_controller.AudioPlayer"):
            run_tour(ctrl, "Hall A")
        client.nav_to_name.assert_called_with("hall_a")

    def test_pose_waypoint(self):
        wp = Waypoint(name="Gallery", pose=Pose(1.0, 2.0, 1.57),
                      dwell_time=0, audio_file="g.mp3")
        client = make_client()
        ctrl = TourController(config=make_config([wp]), client=client)
        with patch("tour_controller.AudioPlayer"):
            run_tour(ctrl, "Gallery")
        client.nav_to_pose.assert_called_with(1.0, 2.0, 1.57)

    def test_multiple_waypoints_all_navigated(self):
        waypoints = [make_waypoint(name=f"S{i}", point=f"p{i}") for i in range(3)]
        client = make_client()
        ctrl = TourController(config=make_config(waypoints), client=client)
        with patch("tour_controller.AudioPlayer"):
            run_tour(ctrl, "S0", timeout=3.0)
        assert client.nav_to_name.call_count == 3

    def test_failed_navigation_skipped_continues(self):
        waypoints = [make_waypoint(name=f"S{i}", point=f"p{i}") for i in range(3)]
        client = make_client()
        client.wait_for_arrival.side_effect = [False, True, True]
        ctrl = TourController(config=make_config(waypoints), client=client)
        with patch("tour_controller.AudioPlayer"):
            run_tour(ctrl, "S0", timeout=3.0)
        assert client.nav_to_name.call_count == 3   # all three attempted

    def test_start_from_middle_waypoint(self):
        waypoints = [make_waypoint(name=f"S{i}", point=f"p{i}") for i in range(4)]
        client = make_client()
        ctrl = TourController(config=make_config(waypoints), client=client)
        with patch("tour_controller.AudioPlayer"):
            run_tour(ctrl, "S2", timeout=3.0)
        calls = [c.args[0] for c in client.nav_to_name.call_args_list]
        assert calls == ["p2", "p3"], f"got {calls}"


# ---------------------------------------------------------------------------
# TourController — jump_to
# ---------------------------------------------------------------------------


class TestJumpTo:
    def test_unknown_waypoint_returns_false(self):
        ctrl = TourController(config=make_config(), client=make_client())
        assert ctrl.jump_to("nonexistent") is False

    def test_known_waypoint_returns_true(self):
        wp = make_waypoint(name="A", point="a")
        ctrl = TourController(config=make_config([wp]), client=make_client())
        ctrl.start()
        assert ctrl.jump_to("A") is True
        ctrl.shutdown()

    def test_jump_interrupts_dwell(self):
        """jump_to during a long dwell should abort within ~0.2 s (poll granularity)."""
        wp1 = make_waypoint(name="A", point="a", dwell_time=60)
        wp2 = make_waypoint(name="B", point="b", dwell_time=0)
        client = make_client()
        ctrl = TourController(config=make_config([wp1, wp2]), client=client)

        ctrl.start()
        with patch("tour_controller.AudioPlayer"):
            ctrl.jump_to("A")
            time.sleep(0.3)          # let it settle into the dwell
            t0 = time.monotonic()
            ctrl.jump_to("B")
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                if ctrl.state.snapshot()["phase"] == "finished":
                    break
                time.sleep(0.05)
        ctrl.shutdown()
        assert time.monotonic() - t0 < 2.0, "jump_to should abort dwell within 2 s"


class TestReset:
    def test_reset_to_idle(self):
        ctrl = TourController(config=make_config(), client=make_client())
        ctrl.start()
        ctrl.jump_to("A")
        time.sleep(0.1)
        ctrl.reset()
        assert ctrl.state.snapshot()["phase"] == "idle"
        ctrl.shutdown()
    
    def test_reset_during_dwell(self):
        ctrl = TourController(config=make_config(), client=make_client())
        ctrl.start()
        ctrl.jump_to("A")
        time.sleep(0.1)
        ctrl.reset()
        assert ctrl.state.snapshot()["phase"] == "idle"
        ctrl.shutdown()


# ---------------------------------------------------------------------------
# TourController — actions
# ---------------------------------------------------------------------------


class TestActions:
    def test_registered_actions_called(self):
        wp = make_waypoint(name="A", point="a", actions=["greet"])
        client = make_client()
        ctrl = TourController(config=make_config([wp]), client=client)
        with patch("tour_controller.AudioPlayer"), \
             patch("tour_controller.action_registry.run_action") as mock_run:
            run_tour(ctrl, "A")
        mock_run.assert_called_once_with("greet", client, "A")

    def test_unknown_action_does_not_crash(self):
        wp = make_waypoint(name="A", point="a", actions=["no_such_action"])
        ctrl = TourController(config=make_config([wp]), client=make_client())
        with patch("tour_controller.AudioPlayer"):
            run_tour(ctrl, "A")   # should not raise
