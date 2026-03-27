"""tour_controller.py — Threaded museum tour orchestrator.

The controller starts *idle* and waits for a :meth:`jump_to` call before
doing anything.  Each call to :meth:`jump_to` interrupts any running tour
and restarts it from the named waypoint, then proceeds sequentially.

Per-stop sequence
-----------------
1. Navigate (by name or pose).
2. Run pre-dwell actions.
3. Start audio; dwell for ``dwell_time`` seconds.
4. Stop audio; advance.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

import actions as action_registry
from audio_player import AudioPlayer, LocalAudioPlayer, RemoteAudioPlayer
from config import Config, Waypoint
from robot_client import RobotClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared state (read by probe server from another thread)
# ---------------------------------------------------------------------------


@dataclass
class TourState:
    phase: str = "idle"            # "idle" | "navigating" | "dwelling" | "finished"
    waypoint: Optional[str] = None # current waypoint name
    audio_playing: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, **kwargs) -> None:
        with self._lock:
            for k, v in kwargs.items():
                setattr(self, k, v)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "phase": self.phase,
                "waypoint": self.waypoint,
                "audio_playing": self.audio_playing,
            }


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


class TourController:
    """
    Drives the robot through waypoints in a background thread.

    Call :meth:`start` once to launch the thread, then :meth:`jump_to` to
    begin (or restart) the tour from any named waypoint.
    """

    def __init__(self, config: Config, client: RobotClient) -> None:
        self.config = config
        self.client = client
        self.state = TourState()

        self._wp_index: Dict[str, int] = {
            wp.name: i for i, wp in enumerate(config.waypoints)
        }
        # Signalled by jump_to() to interrupt the current tour loop.
        self._interrupt = threading.Event()
        self._next_target: Optional[str] = None
        self._audio: Optional[AudioPlayer] = None
        self._shutdown = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Launch the controller thread (stays idle until jump_to is called)."""
        t = threading.Thread(target=self._run, daemon=True, name="tour-ctrl")
        t.start()
        logger.info("Tour controller started — idle. Send PUT /tour?dst=<n> to begin.")

    def jump_to(self, waypoint_name: str) -> bool:
        """
        Interrupt any running tour and restart from *waypoint_name*.

        Returns False if *waypoint_name* is not in the waypoint list.
        """
        if waypoint_name not in self._wp_index:
            return False
        self._next_target = waypoint_name
        self._interrupt.set()            # wake the dwell loop / unblock idle wait
        self.client.cancel_navigation()  # unblock wait_for_arrival if navigating
        if self._audio:
            self._audio.stop()
        logger.info("jump_to('%s') requested.", waypoint_name)
        return True
    
    def reset(self) -> None:
        """
        Immediately interrupts any running tour and resets the tour controller to idle state.
        """
        self._next_target = None
        self._interrupt.set()
        self.client.cancel_navigation()
        if self._audio:
            self._audio.stop()
        self.state.update(phase="idle", waypoint=None, audio_playing=False)
        logger.info("Tour controller reset to idle state.")

    def shutdown(self) -> None:
        """Stop the tour and terminate the controller thread."""
        self._shutdown = True
        self._interrupt.set()
        self.client.cancel_navigation()
        if self._audio:
            self._audio.stop()

    # ------------------------------------------------------------------
    # Internal: main loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while not self._shutdown:
            self._interrupt.wait()          # block until jump_to() or shutdown
            if self._shutdown:
                break
            self._interrupt.clear()
            target = self._next_target
            if target is None or target not in self._wp_index:
                continue
            self._execute_from(self._wp_index[target])

        self.state.update(phase="idle", waypoint=None, audio_playing=False)

    def _execute_from(self, start_idx: int) -> None:
        total = len(self.config.waypoints)
        for wp in self.config.waypoints[start_idx:]:
            if self._interrupt.is_set():
                return
            
            # build audio client
            self._audio = LocalAudioPlayer(wp.audio_file, self.config.audio.sound_card_id) \
                if self.config.audio.local_mode \
                else RemoteAudioPlayer(wp.audio_file,
                    self.config.audio.remote_host,
                    self.config.audio.remote_port)
            
            if wp.play_audio_when_walking:
                self._audio.play()
                self.state.update(audio_playing=True)

            # 1. Navigate
            logger.info("Stop %d/%d — navigating to '%s'.", start_idx + 1, total, wp.name)
            self.state.update(phase="navigating", waypoint=wp.name)
            nav_start_time = time.monotonic()
            if not self._navigate(wp):
                logger.warning("Navigation failed at '%s', skipping.", wp.name)
                start_idx += 1
                continue
            start_idx += 1
            nav_duration = time.monotonic() - nav_start_time

            if self._interrupt.is_set():
                return

            # 2. Pre-dwell actions
            self._run_actions(wp)
            if self._interrupt.is_set():
                return

            # 3. Audio + dwell
            actual_dwell_time = wp.dwell_time
            self.state.update(phase="dwelling")
            if not wp.play_audio_when_walking:
                self._audio.play()
                self.state.update(audio_playing=True)
                # adjust dwell time if playing audio when walking (considering navigation time)
                actual_dwell_time = max(0, wp.dwell_time - nav_duration) + 2

            self._dwell(actual_dwell_time)

            self._audio.stop()
            self._audio = None
            self.state.update(audio_playing=False)

        if not self._interrupt.is_set():
            self.state.update(phase="finished", waypoint=None)
            logger.info("Tour complete.")

    # ------------------------------------------------------------------
    # Internal: step helpers
    # ------------------------------------------------------------------

    def _navigate(self, wp: Waypoint) -> bool:
        cfg = self.config.robot
        if wp.point is not None:
            sent = self.client.nav_to_name(wp.point)
        else:
            p = wp.pose  # type: ignore[union-attr]
            assert p is not None, "pose or point is required for a waypoint"
            sent = self.client.nav_to_pose(p.x, p.y, p.theta)
        if not sent:
            return False
        
        logger.info("Waiting for REEMAN server to respond...")
        # NOTE: do NOT remove this. REEMAN server needs time to update navigation status
        time.sleep(1)
        logger.info("Waiting for arrival...")

        return self.client.wait_for_arrival(
            poll_interval=cfg.nav_poll_interval,
            timeout=cfg.nav_timeout,
        )

    def _dwell(self, seconds: float) -> None:
        """Sleep for *seconds*, waking immediately if interrupted."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if self._interrupt.wait(timeout=min(remaining, 0.2)):
                return  # interrupted

    def _run_actions(self, wp: Waypoint) -> None:
        for name in wp.actions:
            action_registry.run_action(name, self.client, wp.name)
