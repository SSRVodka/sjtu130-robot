"""robot_client.py — Thin HTTP wrapper around the Reeman SLAM Web API v3."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

# Default timeout for individual HTTP requests (seconds)
_HTTP_TIMEOUT = 10


# ---------------------------------------------------------------------------
# Navigation status enumerations (from API docs)
# ---------------------------------------------------------------------------


class NavRes(IntEnum):
    """Top-level navigation phase codes (`res` field)."""
    INIT = 6       # status normal / initialising
    STARTED = 1    # navigation started
    FINISHED = 3   # navigation concluded (check reason)
    CANCELLED = 4  # operator cancelled


class NavReason(IntEnum):
    """Reason codes for NavRes.FINISHED (res == 3)."""
    SUCCESS = 0
    FAILURE = 1


class InitReason(IntEnum):
    """Reason codes for NavRes.INIT (res == 6)."""
    OK = 0
    DOCKING = 1
    ESTOP = 2
    ADAPTER_CHARGING = 3
    POINT_NOT_FOUND = 4
    AGV_DOCK_FAIL = 5
    LOCALIZATION_ERROR = 6
    FIXED_ROUTE_TOO_FAR = 7
    FIXED_ROUTE_NOT_FOUND = 8
    POINT_READ_FAIL = 9


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class NavStatus:
    res: int
    reason: int
    goal: str
    dist: float
    mileage: float

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "NavStatus":
        return cls(
            res=int(d.get("res", -1)),
            reason=int(d.get("reason", -1)),
            goal=str(d.get("goal", "")),
            dist=float(d.get("dist", 0.0)),
            mileage=float(d.get("mileage", 0.0)),
        )

    @property
    def is_finished(self) -> bool:
        return self.res == NavRes.FINISHED

    @property
    def is_success(self) -> bool:
        return self.is_finished and self.reason == NavReason.SUCCESS

    @property
    def is_started(self) -> bool:
        return self.res == NavRes.STARTED


@dataclass
class Pose:
    x: float
    y: float
    theta: float


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class RobotClient:
    """HTTP client for the Reeman SLAM navigation API."""

    def __init__(self, host: str, http_timeout: float = _HTTP_TIMEOUT) -> None:
        self.base_url = f"http://{host}"
        self.http_timeout = http_timeout
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        logger.debug("GET %s", url)
        resp = self._session.get(url, timeout=self.http_timeout)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        logger.debug("POST %s  body=%s", url, body)
        resp = self._session.post(url, json=body or {}, timeout=self.http_timeout)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Basic info
    # ------------------------------------------------------------------

    def get_version(self) -> str:
        return self._get("/reeman/current_version")["version"]

    def get_pose(self) -> Pose:
        d = self._get("/reeman/pose")
        return Pose(x=d["x"], y=d["y"], theta=d["theta"])

    def get_mode(self) -> int:
        """Return 1 = mapping mode, 2 = navigation mode."""
        return self._get("/reeman/get_mode")["mode"]

    def get_battery(self) -> int:
        """Return battery percentage (0-100)."""
        return self._get("/reeman/base_encode")["battery"]

    # ------------------------------------------------------------------
    # Navigation commands
    # ------------------------------------------------------------------

    def nav_to_name(self, point_name: str) -> bool:
        """Navigate to a named waypoint. Returns True on success."""
        try:
            result = self._post("/cmd/nav_name", {"point": point_name})
            ok = result.get("status") == "success"
            if not ok:
                logger.warning("nav_to_name(%r) returned non-success: %s", point_name, result)
            return ok
        except Exception as exc:  # noqa: BLE001
            logger.error("nav_to_name(%r) failed: %s", point_name, exc)
            return False

    def nav_to_pose(self, x: float, y: float, theta: float) -> bool:
        """Navigate to raw map coordinates. Returns True on success."""
        try:
            result = self._post("/cmd/nav", {"x": x, "y": y, "theta": theta})
            ok = result.get("status") == "success"
            if not ok:
                logger.warning("nav_to_pose failed: %s", result)
            return ok
        except Exception as exc:  # noqa: BLE001
            logger.error("nav_to_pose failed: %s", exc)
            return False

    def cancel_navigation(self) -> bool:
        """Cancel the current navigation goal."""
        try:
            result = self._post("/cmd/cancel_goal", {})
            return result.get("status") == "success"
        except Exception as exc:  # noqa: BLE001
            logger.error("cancel_navigation failed: %s", exc)
            return False

    def get_nav_status(self) -> Optional[NavStatus]:
        """Return the current navigation status, or None on error."""
        try:
            d = self._get("/reeman/nav_status")
            return NavStatus.from_dict(d)
        except Exception as exc:  # noqa: BLE001
            logger.error("get_nav_status failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Blocking navigation with timeout
    # ------------------------------------------------------------------

    def wait_for_arrival(
        self,
        poll_interval: float = 1.0,
        timeout: float = 120.0,
    ) -> bool:
        """
        Poll nav_status until navigation finishes or *timeout* seconds elapse.

        Returns True if the robot arrived successfully, False otherwise.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.get_nav_status()
            if status is None:
                time.sleep(poll_interval)
                continue

            logger.debug(
                "nav_status: res=%s reason=%s dist=%.2f goal=%s",
                status.res,
                status.reason,
                status.dist,
                status.goal,
            )

            if status.is_success:
                logger.info("Navigation to '%s' completed successfully.", status.goal)
                return True

            if status.is_finished and not status.is_success:
                logger.warning(
                    "Navigation failed. res=%s reason=%s", status.res, status.reason
                )
                return False

            time.sleep(poll_interval)

        logger.error("Navigation timed out after %.0f seconds.", timeout)
        self.cancel_navigation()
        return False
