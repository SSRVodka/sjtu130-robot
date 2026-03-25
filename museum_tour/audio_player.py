"""audio_player.py — Play audio files during the museum tour.

Uses subprocess to launch a platform-appropriate player so the main thread
remains responsive.  Playback is non-blocking by default; call ``wait()``
to block until the clip finishes.
"""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _find_player() -> Optional[str]:
    """Return the first available command-line audio player found on PATH."""
    candidates = {
        "Linux": ["aplay", "mpg123", "mpg321", "ffplay", "cvlc"],
        "Darwin": ["afplay", "mpg123", "ffplay"],
        "Windows": ["ffplay"],
    }
    system = platform.system()
    for cmd in candidates.get(system, candidates["Linux"]):
        if shutil.which(cmd):
            return cmd
    return None


_PLAYER_CMD = _find_player()


class AudioPlayer:
    """Plays a single audio file in a background thread."""

    def __init__(self, audio_file: str | Path) -> None:
        self.audio_file = Path(audio_file)
        self._process: Optional[subprocess.Popen] = None  # type: ignore[type-arg]
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def play(self) -> None:
        """Start playback in a background thread (non-blocking)."""
        if not self.audio_file.exists():
            logger.warning("Audio file not found, skipping: %s", self.audio_file)
            return

        if _PLAYER_CMD is None:
            logger.warning(
                "No audio player found on PATH (tried mpg123, afplay, ffplay…). "
                "Skipping audio for: %s",
                self.audio_file,
            )
            return

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.debug("Started audio: %s", self.audio_file)

    def stop(self) -> None:
        """Terminate playback immediately."""
        if self._process and self._process.poll() is None:
            self._process.terminate()
            logger.debug("Stopped audio: %s", self.audio_file)

    def wait(self) -> None:
        """Block until playback finishes."""
        if self._thread:
            self._thread.join()

    @property
    def is_playing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_cmd(self) -> list[str]:
        assert _PLAYER_CMD is not None
        cmd = _PLAYER_CMD
        file_str = str(self.audio_file)
        # use source card 1 on OrangePi5 Plus (OpenHarmony OS)
        if cmd == "aplay":
            return ["aplay", "-Dplughw:1", file_str]
        # ffplay needs extra flags to suppress its video window
        if cmd == "ffplay":
            return ["ffplay", "-nodisp", "-autoexit", file_str]
        # cvlc (VLC without GUI)
        if cmd == "cvlc":
            return ["cvlc", "--play-and-exit", file_str]
        return [cmd, file_str]

    def _run(self) -> None:
        cmd = self._build_cmd()
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._process.wait()
        except Exception as exc:  # noqa: BLE001
            logger.error("Audio playback error (%s): %s", self.audio_file, exc)
