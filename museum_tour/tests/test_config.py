"""tests/test_config.py — Unit tests for config loading and validation."""

import textwrap
from pathlib import Path

import pytest
import yaml

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import load_config, Config, Waypoint, RobotConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "tour.yaml"
    p.write_text(textwrap.dedent(content))
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_minimal_named_point(self, tmp_path):
        cfg_path = write_yaml(tmp_path, """
            robot:
              host: "10.0.0.5"
            waypoints:
              - name: "Hall A"
                point: "hall_a"
                dwell_time: 30
                audio_file: "hall_a.mp3"
        """)
        cfg = load_config(cfg_path)

        assert isinstance(cfg, Config)
        assert cfg.robot.host == "10.0.0.5"
        assert len(cfg.waypoints) == 1
        wp = cfg.waypoints[0]
        assert wp.name == "Hall A"
        assert wp.point == "hall_a"
        assert wp.dwell_time == 30
        assert wp.audio_file == "hall_a.mp3"
        assert wp.pose is None

    def test_pose_waypoint(self, tmp_path):
        cfg_path = write_yaml(tmp_path, """
            robot:
              host: "10.0.0.1"
            waypoints:
              - name: "Gallery"
                pose:
                  x: 1.5
                  y: 2.5
                  theta: 0.78
                dwell_time: 20
                audio_file: "gallery.mp3"
        """)
        cfg = load_config(cfg_path)
        wp = cfg.waypoints[0]
        assert wp.point is None
        assert wp.pose is not None
        assert wp.pose.x == pytest.approx(1.5)
        assert wp.pose.theta == pytest.approx(0.78)

    def test_defaults(self, tmp_path):
        cfg_path = write_yaml(tmp_path, """
            robot:
              host: "10.0.0.1"
            waypoints:
              - name: "Room"
                point: "room"
                dwell_time: 10
                audio_file: "room.mp3"
        """)
        cfg = load_config(cfg_path)
        assert cfg.robot.nav_poll_interval == pytest.approx(1.0)
        assert cfg.robot.nav_timeout == pytest.approx(120.0)

    def test_tour_overrides(self, tmp_path):
        cfg_path = write_yaml(tmp_path, """
            robot:
              host: "10.0.0.1"
              nav_timeout: 60
            tour:
              wait_for_input: true
              input_mode: "button"
              button_event_code: 999
            waypoints:
              - name: "A"
                point: "a"
                dwell_time: 5
                audio_file: "a.mp3"
        """)
        cfg = load_config(cfg_path)
        assert cfg.robot.nav_timeout == pytest.approx(60.0)

    def test_actions_loaded(self, tmp_path):
        cfg_path = write_yaml(tmp_path, """
            robot:
              host: "10.0.0.1"
            waypoints:
              - name: "Entrance"
                point: "entrance"
                dwell_time: 10
                audio_file: "entrance.mp3"
                actions:
                  - greet
                  - display_artifact
        """)
        cfg = load_config(cfg_path)
        assert cfg.waypoints[0].actions == ["greet", "display_artifact"]

    def test_missing_point_and_pose_raises(self, tmp_path):
        cfg_path = write_yaml(tmp_path, """
            robot:
              host: "10.0.0.1"
            waypoints:
              - name: "Bad"
                dwell_time: 10
                audio_file: "bad.mp3"
        """)
        with pytest.raises(ValueError, match="must specify either"):
            load_config(cfg_path)

    def test_no_waypoints_raises(self, tmp_path):
        cfg_path = write_yaml(tmp_path, """
            robot:
              host: "10.0.0.1"
            waypoints: []
        """)
        with pytest.raises(ValueError, match="No waypoints"):
            load_config(cfg_path)

    def test_multiple_waypoints(self, tmp_path):
        cfg_path = write_yaml(tmp_path, """
            robot:
              host: "10.0.0.1"
            waypoints:
              - name: "A"
                point: "a"
                dwell_time: 10
                audio_file: "a.mp3"
              - name: "B"
                point: "b"
                dwell_time: 20
                audio_file: "b.mp3"
              - name: "C"
                pose: {x: 1.0, y: 2.0, theta: 0.0}
                dwell_time: 30
                audio_file: "c.mp3"
        """)
        cfg = load_config(cfg_path)
        assert len(cfg.waypoints) == 3
        assert cfg.waypoints[2].pose is not None
