"""tests/test_robot_client.py — Unit tests for RobotClient using mocked HTTP."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch, call
import pytest

from robot_client import RobotClient, NavStatus, NavRes, NavReason


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# NavStatus
# ---------------------------------------------------------------------------


class TestNavStatus:
    def test_from_dict_basic(self):
        s = NavStatus.from_dict({"res": 3, "reason": 0, "goal": "A", "dist": 0.0, "mileage": 1.2})
        assert s.res == 3
        assert s.reason == 0
        assert s.is_success is True
        assert s.is_finished is True

    def test_not_finished(self):
        s = NavStatus.from_dict({"res": 1, "reason": 0, "goal": "A", "dist": 0.5, "mileage": 0})
        assert s.is_started is True
        assert s.is_finished is False
        assert s.is_success is False

    def test_failed_navigation(self):
        s = NavStatus.from_dict({"res": 3, "reason": 1, "goal": "B", "dist": 0, "mileage": 0})
        assert s.is_finished is True
        assert s.is_success is False

    def test_missing_fields_defaults(self):
        s = NavStatus.from_dict({})
        assert s.res == -1
        assert s.reason == -1


# ---------------------------------------------------------------------------
# RobotClient
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_session():
    """Return a mock requests.Session injected into RobotClient."""
    with patch("robot_client.requests.Session") as MockSession:
        session = MagicMock()
        MockSession.return_value = session
        yield session


@pytest.fixture()
def client(mock_session) -> RobotClient:
    return RobotClient(host="10.0.0.1")


class TestRobotClientBasicInfo:
    def test_get_version(self, client, mock_session):
        mock_session.get.return_value = make_response({"version": "v3.1.5"})
        assert client.get_version() == "v3.1.5"
        mock_session.get.assert_called_once_with(
            "http://10.0.0.1/reeman/current_version", timeout=10
        )

    def test_get_pose(self, client, mock_session):
        mock_session.get.return_value = make_response({"x": 1.5, "y": 2.5, "theta": 0.3})
        pose = client.get_pose()
        assert pose.x == pytest.approx(1.5)
        assert pose.theta == pytest.approx(0.3)

    def test_get_mode(self, client, mock_session):
        mock_session.get.return_value = make_response({"mode": 2})
        assert client.get_mode() == 2

    def test_get_battery(self, client, mock_session):
        mock_session.get.return_value = make_response(
            {"battery": 85, "chargeFlag": 0, "emergencyButton": 1}
        )
        assert client.get_battery() == 85


class TestRobotClientNavigation:
    def test_nav_to_name_success(self, client, mock_session):
        mock_session.post.return_value = make_response({"status": "success"})
        assert client.nav_to_name("hall_a") is True
        mock_session.post.assert_called_once_with(
            "http://10.0.0.1/cmd/nav_name", json={"point": "hall_a"}, timeout=10
        )

    def test_nav_to_name_failure(self, client, mock_session):
        mock_session.post.return_value = make_response({"status": "Exception"})
        assert client.nav_to_name("unknown") is False

    def test_nav_to_name_http_error(self, client, mock_session):
        mock_session.post.side_effect = Exception("Connection refused")
        assert client.nav_to_name("hall_a") is False

    def test_nav_to_pose_success(self, client, mock_session):
        mock_session.post.return_value = make_response({"status": "success"})
        assert client.nav_to_pose(1.0, 2.0, 0.5) is True
        mock_session.post.assert_called_once_with(
            "http://10.0.0.1/cmd/nav", json={"x": 1.0, "y": 2.0, "theta": 0.5}, timeout=10
        )

    def test_cancel_navigation(self, client, mock_session):
        mock_session.post.return_value = make_response({"status": "success"})
        assert client.cancel_navigation() is True


class TestWaitForArrival:
    def test_succeeds_on_first_poll(self, client, mock_session):
        mock_session.get.return_value = make_response(
            {"res": 3, "reason": 0, "goal": "A", "dist": 0, "mileage": 0.5}
        )
        assert client.wait_for_arrival(poll_interval=0, timeout=5) is True

    def test_succeeds_after_several_polls(self, client, mock_session):
        responses = [
            make_response({"res": 6, "reason": 0, "goal": "A", "dist": 2.0, "mileage": 0}),
            make_response({"res": 1, "reason": 0, "goal": "A", "dist": 1.0, "mileage": 0}),
            make_response({"res": 3, "reason": 0, "goal": "A", "dist": 0, "mileage": 1.2}),
        ]
        mock_session.get.side_effect = responses
        assert client.wait_for_arrival(poll_interval=0, timeout=10) is True
        assert mock_session.get.call_count == 3

    def test_fails_on_nav_failure(self, client, mock_session):
        mock_session.get.return_value = make_response(
            {"res": 3, "reason": 1, "goal": "A", "dist": 0, "mileage": 0}
        )
        assert client.wait_for_arrival(poll_interval=0, timeout=5) is False

    def test_times_out(self, client, mock_session):
        # Always return "started" so it never finishes
        mock_session.get.return_value = make_response(
            {"res": 1, "reason": 0, "goal": "A", "dist": 2.0, "mileage": 0}
        )
        mock_session.post.return_value = make_response({"status": "success"})
        result = client.wait_for_arrival(poll_interval=0, timeout=0.05)
        assert result is False
        # cancel_goal should have been called
        mock_session.post.assert_called_with(
            "http://10.0.0.1/cmd/cancel_goal", json={}, timeout=10
        )

    def test_handles_none_status(self, client, mock_session):
        # First call raises, second returns success
        mock_session.get.side_effect = [
            Exception("timeout"),
            make_response({"res": 3, "reason": 0, "goal": "A", "dist": 0, "mileage": 0}),
        ]
        assert client.wait_for_arrival(poll_interval=0, timeout=5) is True
