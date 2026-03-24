"""input_handler.py — Wait for operator "proceed" signal.

Two modes are supported:

* ``"cli"``    — operator presses **Enter** in the terminal.
* ``"button"`` — a Linux input device (mouse button, physical button mapped
                 via udev) generates an event matching *event_code*.

Both modes are non-blocking internally; they block the *calling* thread until
the signal arrives or the optional *timeout* expires.
"""

from __future__ import annotations

import logging
import select
import struct
import sys
import threading
import time
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class InputHandler(ABC):
    """Wait for a "proceed to next stop" signal from the operator."""

    @abstractmethod
    def wait_for_proceed(self, timeout: Optional[float] = None) -> bool:
        """
        Block until the operator signals to proceed.

        Parameters
        ----------
        timeout:
            Maximum seconds to wait.  ``None`` means wait forever.

        Returns
        -------
        bool
            ``True`` if the signal was received, ``False`` if *timeout* elapsed.
        """


# ---------------------------------------------------------------------------
# CLI handler
# ---------------------------------------------------------------------------


class CLIInputHandler(InputHandler):
    """Prompt the operator on stdout and wait for Enter."""

    def wait_for_proceed(self, timeout: Optional[float] = None) -> bool:
        prompt = "\n>>> Press Enter to continue to the next stop (or wait for timeout)…"
        if timeout is not None:
            prompt = (
                f"\n>>> Press Enter to continue now, or wait {timeout:.0f}s for auto-advance…"
            )

        print(prompt, flush=True)

        # Use select so we can respect the timeout on POSIX systems
        if sys.stdin.isatty():
            ready, _, _ = select.select([sys.stdin], [], [], timeout)
            if ready:
                sys.stdin.readline()  # consume the line
                logger.info("Operator pressed Enter — advancing.")
                return True
            logger.info("Timeout elapsed — auto-advancing.")
            return False
        else:
            # Non-interactive stdin (e.g. piped): just sleep and advance
            if timeout:
                time.sleep(timeout)
            return False


# ---------------------------------------------------------------------------
# Hardware button handler (Linux evdev)
# ---------------------------------------------------------------------------

# Linux input_event struct: { timeval(8 bytes), type(u16), code(u16), value(s32) }
_EVENT_FMT = "llHHi"
_EVENT_SIZE = struct.calcsize(_EVENT_FMT)
_EV_KEY = 0x01
_KEY_PRESSED = 1


class ButtonInputHandler(InputHandler):
    """
    Wait for a Linux input device event (e.g. mouse click or GPIO button).

    Parameters
    ----------
    device_path:
        Path to the evdev device, e.g. ``/dev/input/event0``.
    event_code:
        Numeric event code to match, e.g. ``272`` for BTN_LEFT.
    """

    def __init__(self, device_path: str = "/dev/input/event0", event_code: int = 272) -> None:
        self.device_path = device_path
        self.event_code = event_code

    def wait_for_proceed(self, timeout: Optional[float] = None) -> bool:
        try:
            with open(self.device_path, "rb") as dev:
                logger.info(
                    "Waiting for button (device=%s, code=%s)…",
                    self.device_path,
                    self.event_code,
                )
                deadline = time.monotonic() + timeout if timeout else None
                while True:
                    remaining: Optional[float] = None
                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            logger.info("Button timeout elapsed — auto-advancing.")
                            return False

                    ready, _, _ = select.select([dev], [], [], remaining)
                    if not ready:
                        logger.info("Button timeout elapsed — auto-advancing.")
                        return False

                    raw = dev.read(_EVENT_SIZE)
                    if len(raw) < _EVENT_SIZE:
                        continue
                    _, _, ev_type, ev_code, ev_value = struct.unpack(_EVENT_FMT, raw)
                    if ev_type == _EV_KEY and ev_code == self.event_code and ev_value == _KEY_PRESSED:
                        logger.info("Button pressed (code=%s) — advancing.", self.event_code)
                        return True
        except PermissionError:
            logger.error(
                "Cannot read %s — permission denied. Try: sudo chmod a+r %s",
                self.device_path,
                self.device_path,
            )
        except FileNotFoundError:
            logger.error("Input device not found: %s", self.device_path)
        except Exception as exc:  # noqa: BLE001
            logger.error("ButtonInputHandler error: %s", exc)

        # Fallback to CLI on any error
        logger.warning("Falling back to CLI input handler.")
        return CLIInputHandler().wait_for_proceed(timeout)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_input_handler(mode: str, device: str = "/dev/input/event0", code: int = 272) -> InputHandler:
    """Return the appropriate :class:`InputHandler` for *mode*."""
    if mode == "button":
        return ButtonInputHandler(device_path=device, event_code=code)
    if mode == "cli":
        return CLIInputHandler()
    raise ValueError(f"Unknown input_mode '{mode}'. Expected 'cli' or 'button'.")
