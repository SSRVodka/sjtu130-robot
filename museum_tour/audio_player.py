"""audio_player.py — Play audio files during the museum tour.

Uses subprocess to launch a platform-appropriate player so the main thread
remains responsive.  Playback is non-blocking by default; call ``wait()``
to block until the clip finishes.
"""

from __future__ import annotations

from abc import abstractmethod
import logging
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class AudioPlayer:
    """Plays a single audio file."""
    @abstractmethod
    def play(self) -> None:
        raise NotImplementedError
    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError
    @abstractmethod
    def wait(self, interrupt: threading.Event) -> bool:
        raise NotImplementedError
    @property
    def is_playing(self) -> bool:
        return False


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


class LocalAudioPlayer(AudioPlayer):
    """Plays a single audio file in a background thread."""

    def __init__(self, audio_file: str | Path, sound_card_id: int = 0) -> None:
        self.audio_file = Path(audio_file)
        self.sound_card_id = sound_card_id
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

    def wait(self, interrupt: threading.Event) -> bool:
        """Block until playback finishes or interrupt is set."""
        if self._thread:
            self._thread.join()
        return True

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
        if cmd == "aplay":
            return ["aplay", f"-Dplughw:{self.sound_card_id}", file_str]
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


class RemoteAudioPlayer(AudioPlayer):
    """Plays a single audio file over a network via a remote audio player server."""

    def __init__(self, audio_file: str, host: str, port: int) -> None:
        self.audio_file = audio_file
        self.host = host
        self.port = port
        self._playing = False
        self._lock = threading.Lock()

    def _url(self, path: str) -> str:
        return f"http://{self.host}:{self.port}{path}"

    def play(self) -> None:
        threading.Thread(
            target=self._request,
            args=("PUT", self._url("/play")),
            kwargs={"params": {"file": self.audio_file}},
            daemon=True,
        ).start()

    def stop(self) -> None:
        self._request("PUT", self._url("/stop"))

    def wait(self, interrupt: threading.Event) -> bool:
        """Returns True if not interrupted"""
        while True:
            time.sleep(1)
            if (interrupt.is_set()):
                logger.warning("audio player wait interrupted")
                return False
            if not self.is_playing:
                break
        return True

    @property
    def is_playing(self) -> bool:
        try:
            resp = self._request("GET", self._url("/status"))
            if resp is None:
                return False
            val: bool = resp.json().get("playing", False) if resp.ok else False
            with self._lock:
                self._playing = val
            return self._playing
        except Exception as exc:  # noqa: BLE001
            logger.error("RemoteAudioPlayer is_playing failed: %s", exc)
            return False

    def _request(
        self, method: str, url: str, params: Optional[dict] = None
    ) -> Optional[requests.Response]:
        try:
            resp = requests.request(method, url, params=params, timeout=10)
            return resp
        except Exception as exc:  # noqa: BLE001
            logger.error("RemoteAudioPlayer request failed (%s %s): %s", method, url, exc)
            return None
