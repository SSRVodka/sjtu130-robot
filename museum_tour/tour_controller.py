"""tour_controller.py — Orchestrates the museum guided tour.

Sequence for each waypoint
--------------------------
1. Issue navigation command (by name or pose).
2. Block until arrival (or failure/timeout).
3. Run pre-dwell actions (e.g. greeting gesture).
4. Start audio playback.
5. Wait for dwell_time **or** operator input (if wait_for_input is enabled).
6. Stop audio (if still playing).
7. Advance to next waypoint.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional

import actions as action_registry
from audio_player import AudioPlayer
from config import Config, Waypoint
from input_handler import InputHandler, make_input_handler
from robot_client import RobotClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-stop result record
# ---------------------------------------------------------------------------


@dataclass
class StopResult:
    waypoint_name: str
    nav_success: bool
    skipped: bool = False
    error: Optional[str] = None


@dataclass
class TourResult:
    stops: List[StopResult] = field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        return all(s.nav_success or s.skipped for s in self.stops)

    def summary(self) -> str:
        lines = ["=== Tour Summary ==="]
        for s in self.stops:
            status = "OK" if s.nav_success else ("SKIP" if s.skipped else "FAIL")
            lines.append(f"  [{status}] {s.waypoint_name}")
            if s.error:
                lines.append(f"        Error: {s.error}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


class TourController:
    """
    High-level controller that drives the robot through all waypoints.

    Parameters
    ----------
    config:
        Fully parsed :class:`~config.Config` object.
    client:
        A :class:`~robot_client.RobotClient` connected to the robot.
    input_handler:
        Strategy for waiting for operator "proceed" input.  If ``None``,
        one is constructed from ``config.tour``.
    """

    def __init__(
        self,
        config: Config,
        client: RobotClient,
        input_handler: Optional[InputHandler] = None,
    ) -> None:
        self.config = config
        self.client = client
        self._input_handler: InputHandler = input_handler or make_input_handler(
            mode=config.tour.input_mode,
            device=config.tour.button_device,
            code=config.tour.button_event_code,
        )
        self._stop_requested = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> TourResult:
        """Execute the full tour and return a :class:`TourResult`."""
        result = TourResult()
        total = len(self.config.waypoints)

        logger.info("Starting museum tour — %d stops.", total)
        self._verify_navigation_mode()

        for idx, waypoint in enumerate(self.config.waypoints, start=1):
            if self._stop_requested:
                logger.info("Stop requested — aborting tour.")
                break

            print(f"\n{'='*60}")
            print(f"  Stop {idx}/{total}: {waypoint.name}")
            print(f"{'='*60}")

            stop_result = self._execute_stop(waypoint)
            result.stops.append(stop_result)

            if not stop_result.nav_success and not stop_result.skipped:
                logger.warning(
                    "Navigation failed at '%s'. Continuing to next stop.", waypoint.name
                )

        logger.info("Tour complete.\n%s", result.summary())
        return result

    def request_stop(self) -> None:
        """Signal the tour to stop after the current waypoint finishes."""
        self._stop_requested = True
        self.client.cancel_navigation()

    # ------------------------------------------------------------------
    # Internal: per-stop logic
    # ------------------------------------------------------------------

    def _execute_stop(self, waypoint: Waypoint) -> StopResult:
        player = AudioPlayer(waypoint.audio_file)
        if waypoint.play_audio_when_walking:
            player.play()
        # 1. Navigate
        nav_ok = self._navigate(waypoint)
        if not nav_ok:
            return StopResult(
                waypoint_name=waypoint.name,
                nav_success=False,
                error="Navigation failed or timed out",
            )

        # 2. Pre-dwell actions (e.g. greeting)
        self._run_actions(waypoint)

        # 3. Audio + dwell
        if not waypoint.play_audio_when_walking:
            player.play()

        self._dwell(waypoint, player)

        # 4. Ensure audio is stopped before leaving
        player.stop()

        return StopResult(waypoint_name=waypoint.name, nav_success=True)

    def _navigate(self, waypoint: Waypoint) -> bool:
        """Send the navigation command and wait for arrival."""
        robot_cfg = self.config.robot

        if waypoint.point is not None:
            logger.info("Navigating to named point '%s'…", waypoint.point)
            sent = self.client.nav_to_name(waypoint.point)
        else:
            p = waypoint.pose  # type: ignore[union-attr]
            assert p is not None, "a waypoint must specify either 'point' or 'pose'"
            logger.info("Navigating to pose (%.2f, %.2f, %.2f)…", p.x, p.y, p.theta)
            sent = self.client.nav_to_pose(p.x, p.y, p.theta)

        if not sent:
            logger.error("Failed to send navigation command for '%s'.", waypoint.name)
            return False

        logger.info("Waiting for server to get ready for navigation status...")
        # NOTE: do NOT remove it. REEMAN server needs time to get ready for navigation status.
        time.sleep(5)
        logger.info("Waiting for arrival...")
        return self.client.wait_for_arrival(
            poll_interval=robot_cfg.nav_poll_interval,
            timeout=robot_cfg.nav_timeout,
        )

    def _dwell(self, waypoint: Waypoint, player: AudioPlayer) -> None:
        """Handle the dwell phase: wait for input or timer."""
        dwell = waypoint.dwell_time

        if self.config.tour.wait_for_input:
            # Operator decides when to advance; dwell_time acts as auto-advance
            # fallback so the tour doesn't stall forever if no operator is present.
            self._input_handler.wait_for_proceed(timeout=dwell if dwell > 0 else None)
        else:
            logger.info("Dwelling for %.0f seconds at '%s'…", dwell, waypoint.name)
            # Sleep in small increments so audio can finish naturally
            end_time = time.monotonic() + dwell
            while time.monotonic() < end_time:
                if self._stop_requested:
                    break
                time.sleep(0.25)

    def _run_actions(self, waypoint: Waypoint) -> None:
        for action_name in waypoint.actions:
            action_registry.run_action(action_name, self.client, waypoint.name)

    def _verify_navigation_mode(self) -> None:
        try:
            mode = self.client.get_mode()
            if mode != 2:
                logger.warning(
                    "Robot is NOT in navigation mode (mode=%d). "
                    "Navigation commands may fail.",
                    mode,
                )
            else:
                logger.info("Robot confirmed in navigation mode.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not verify robot mode: %s", exc)
