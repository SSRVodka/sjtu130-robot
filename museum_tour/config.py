"""config.py — Load and validate the YAML tour configuration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Pose:
    x: float
    y: float
    theta: float


@dataclass
class Waypoint:
    name: str
    description: str
    dwell_time: float          # seconds
    audio_file: str
    play_audio_when_walking: bool = False
    actions: List[str] = field(default_factory=list)
    point: Optional[str] = None   # named point on robot map
    pose: Optional[Pose] = None   # raw coordinate fallback

    def __post_init__(self) -> None:
        if self.point is None and self.pose is None:
            raise ValueError(
                f"Waypoint '{self.name}' must specify either 'point' or 'pose'."
            )


@dataclass
class RobotConfig:
    host: str
    nav_poll_interval: float = 1.0
    nav_timeout: float = 120.0


@dataclass
class AudioConfig:
    local_mode: bool = True
    sound_card_id: int = 0
    remote_host: str = "192.168.11.2"
    remote_port: int = 10000


@dataclass
class ProbeConfig:
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class Config:
    robot: RobotConfig
    audio: AudioConfig
    probe: ProbeConfig
    waypoints: List[Waypoint]


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_config(path: str | Path) -> Config:
    """Parse *path* (YAML) and return a validated :class:`Config`."""
    path = Path(path)
    logger.debug("Loading config from %s", path)

    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    robot_raw = raw.get("robot", {})
    robot = RobotConfig(
        host=robot_raw["host"],
        nav_poll_interval=float(robot_raw.get("nav_poll_interval", 1.0)),
        nav_timeout=float(robot_raw.get("nav_timeout", 120.0)),
    )

    audio_raw = raw.get("audio", {})
    audio = AudioConfig(
        local_mode=bool(audio_raw.get("local_mode", True)),
        sound_card_id=int(audio_raw.get("sound_card_id", 0)),
        remote_host=str(audio_raw.get("remote_host", "192.168.11.2")),
        remote_port=int(audio_raw.get("remote_port", 10000)),
    )

    probe_raw = raw.get("probe", {})
    probe = ProbeConfig(
        host=str(probe_raw.get("host", "0.0.0.0")),
        port=int(probe_raw.get("port", 8080)),
    )

    waypoints: List[Waypoint] = []
    for wp_raw in raw.get("waypoints", []):
        pose_raw = wp_raw.get("pose")
        pose = (
            Pose(
                x=float(pose_raw["x"]),
                y=float(pose_raw["y"]),
                theta=float(pose_raw["theta"]),
            )
            if pose_raw
            else None
        )
        waypoints.append(
            Waypoint(
                name=str(wp_raw["name"]),
                description=str(wp_raw["description"]),
                dwell_time=float(wp_raw.get("dwell_time", 0)),
                audio_file=str(wp_raw["audio_file"]),
                play_audio_when_walking=bool(wp_raw.get("play_audio_when_walking", False)),
                actions=list(wp_raw.get("actions") or []),
                point=wp_raw.get("point"),
                pose=pose,
            )
        )

    if not waypoints:
        raise ValueError("No waypoints defined in configuration.")

    config = Config(robot=robot, audio=audio, probe=probe, waypoints=waypoints)
    logger.info("Loaded %d waypoints; host=%s; audio=%s", len(waypoints), robot.host, audio)
    return config
