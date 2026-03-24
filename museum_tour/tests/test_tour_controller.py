"""tests/test_tour_controller.py — Unit tests for TourController."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch, call
import pytest

from config import Config, RobotConfig, TourConfig, Waypoint, Pose
from tour_controller import TourController, TourResult
from input_handler import InputHandler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_waypoint(
    name: str = "Test Stop",
    point: str = "test",
    dwell_time: float = 0,
    audio_file: str = "test.mp3",
    actions=None,
) -> Waypoint:
    return Waypoint(
        name=name,
        point=point,
        dwell_time=dwell_time,
        audio_file=audio_file,
        actions=actions or [],
    )


def make_config(waypoints=None, wait_for_input=False) -> Config:
    return Config(
        robot=RobotConfig(host="10.0.0.1", nav_poll_interval=0, nav_timeout=5),
        tour=TourConfig(wait_for_input=wait_for_input),
        waypoints=waypoints or [make_waypoint()],
    )


class AlwaysProceedInput(InputHandler):
    """Immediately signals 'proceed'."""
    def wait_for_proceed(self, timeout=None):
        return True


@pytest.fixture()
def mock_client():
    client = MagicMock()
    client.get_mode.return_value = 2         # navigation mode
    client.nav_to_name.return_value = True
    client.nav_to_pose.return_value = True
    client.wait_for_arrival.return_value = True
    return client


def make_controller(config=None, client=None, input_handler=None):
    return TourController(
        config=config or make_config(),
        client=client or MagicMock(),
        input_handler=input_handler or AlwaysProceedInput(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTourControllerNavigation:
    def test_single_waypoint_named_point(self, mock_client):
        wp = make_waypoint(name="Hall A", point="hall_a")
        cfg = make_config(waypoints=[wp])
        ctrl = make_controller(config=cfg, client=mock_client)

        with patch("tour_controller.AudioPlayer") as MockAudio:
            MockAudio.return_value.play.return_value = None
            MockAudio.return_value.stop.return_value = None
            result = ctrl.run()

        mock_client.nav_to_name.assert_called_once_with("hall_a")
        assert result.all_succeeded is True
        assert result.stops[0].nav_success is True

    def test_single_waypoint_pose(self, mock_client):
        wp = Waypoint(
            name="Gallery",
            pose=Pose(x=100.0, y=200.0, theta=1.57),
            dwell_time=0,
            audio_file="g.mp3",
        )
        cfg = make_config(waypoints=[wp])
        ctrl = make_controller(config=cfg, client=mock_client)

        with patch("tour_controller.AudioPlayer"):
            result = ctrl.run()

        mock_client.nav_to_pose.assert_called_once_with(100.0, 200.0, 1.57)
        assert result.all_succeeded is True

    def test_multiple_waypoints_all_succeed(self, mock_client):
        waypoints = [make_waypoint(name=f"Stop {i}", point=f"stop_{i}") for i in range(3)]
        cfg = make_config(waypoints=waypoints)
        ctrl = make_controller(config=cfg, client=mock_client)

        with patch("tour_controller.AudioPlayer"):
            result = ctrl.run()

        assert mock_client.nav_to_name.call_count == 3
        assert len(result.stops) == 3
        assert result.all_succeeded is True

    def test_nav_failure_continues_tour(self, mock_client):
        """A failed navigation stop should not abort the whole tour."""
        mock_client.wait_for_arrival.side_effect = [False, True, True]
        waypoints = [make_waypoint(name=f"Stop {i}", point=f"s{i}") for i in range(3)]
        cfg = make_config(waypoints=waypoints)
        ctrl = make_controller(config=cfg, client=mock_client)

        with patch("tour_controller.AudioPlayer"):
            result = ctrl.run()

        assert len(result.stops) == 3
        assert result.stops[0].nav_success is False
        assert result.stops[1].nav_success is True
        assert result.all_succeeded is False

    def test_nav_command_failure_records_error(self, mock_client):
        mock_client.nav_to_name.return_value = False
        ctrl = make_controller(client=mock_client)

        with patch("tour_controller.AudioPlayer"):
            result = ctrl.run()

        assert result.stops[0].nav_success is False
        assert result.stops[0].error is not None


class TestTourControllerInput:
    def test_wait_for_input_calls_handler(self, mock_client):
        handler = MagicMock(spec=InputHandler)
        handler.wait_for_proceed.return_value = True
        cfg = make_config(wait_for_input=True)
        ctrl = make_controller(config=cfg, client=mock_client, input_handler=handler)

        with patch("tour_controller.AudioPlayer"):
            ctrl.run()

        handler.wait_for_proceed.assert_called_once()

    def test_no_wait_does_not_call_handler(self, mock_client):
        handler = MagicMock(spec=InputHandler)
        cfg = make_config(wait_for_input=False)
        ctrl = make_controller(config=cfg, client=mock_client, input_handler=handler)

        with patch("tour_controller.AudioPlayer"):
            ctrl.run()

        handler.wait_for_proceed.assert_not_called()


class TestTourControllerActions:
    def test_actions_are_executed(self, mock_client):
        wp = make_waypoint(actions=["greet", "display_artifact"])
        cfg = make_config(waypoints=[wp])
        ctrl = make_controller(config=cfg, client=mock_client)

        with patch("tour_controller.AudioPlayer"), \
             patch("tour_controller.action_registry.run_action") as mock_run:
            ctrl.run()

        assert mock_run.call_count == 2
        mock_run.assert_any_call("greet", mock_client, wp.name)
        mock_run.assert_any_call("display_artifact", mock_client, wp.name)

    def test_unknown_action_does_not_crash(self, mock_client):
        """Unknown action names should be skipped with a warning, not crash."""
        import actions as ar
        wp = make_waypoint(actions=["nonexistent_action"])
        cfg = make_config(waypoints=[wp])
        ctrl = make_controller(config=cfg, client=mock_client)

        with patch("tour_controller.AudioPlayer"):
            result = ctrl.run()   # should not raise

        assert result.all_succeeded is True


class TestTourControllerStop:
    def test_request_stop_aborts_after_current(self, mock_client):
        waypoints = [make_waypoint(name=f"S{i}", point=f"s{i}") for i in range(4)]
        cfg = make_config(waypoints=waypoints)
        ctrl = make_controller(config=cfg, client=mock_client)

        stop_called = []

        def side_effect_nav_to_name(point):
            stop_called.append(point)
            if point == "s1":
                ctrl.request_stop()
            return True

        mock_client.nav_to_name.side_effect = side_effect_nav_to_name
        mock_client.cancel_navigation.return_value = True

        with patch("tour_controller.AudioPlayer"):
            result = ctrl.run()

        # Should have processed s0 and s1, then aborted
        assert len(result.stops) <= 2


class TestTourResult:
    def test_all_succeeded_true(self):
        r = TourResult()
        from tour_controller import StopResult
        r.stops = [StopResult("A", True), StopResult("B", True)]
        assert r.all_succeeded is True

    def test_all_succeeded_false(self):
        from tour_controller import StopResult
        r = TourResult()
        r.stops = [StopResult("A", True), StopResult("B", False)]
        assert r.all_succeeded is False

    def test_summary_contains_names(self):
        from tour_controller import StopResult
        r = TourResult()
        r.stops = [StopResult("Ancient Hall", True), StopResult("Modern Wing", False)]
        s = r.summary()
        assert "Ancient Hall" in s
        assert "Modern Wing" in s
        assert "OK" in s
        assert "FAIL" in s
