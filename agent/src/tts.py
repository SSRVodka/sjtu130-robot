"""
TTS tool: converts text to speech via Alibaba qwen3-tts-flash and streams
the resulting PCM audio directly to a phone over TCP.

Provides two integration points for the agent:
  1. A standalone async function  – speak(text)
  2. A tool-definition dict + executor for use with ToolRegistry

Configuration is read from a shared mutable dict so that values set at
runtime (e.g. from a YAML config file) are visible to speak() without
requiring re-imports.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
import logging
import os
import socket
from typing import Any

import requests
import yaml

from .tools.base import ToolDefinition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults – all overridden by applying TTSConfig values to this dict
# ---------------------------------------------------------------------------

WAYPOINT_CONFIG: dict[str, Any] = {}
WAYPOINT_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "museum_tour", "waypoints.yaml")
with open(WAYPOINT_CONFIG_FILE, "r") as f:
    WAYPOINT_CONFIG = yaml.safe_load(f)
PROBE_URL = f"http://{WAYPOINT_CONFIG['probe']['host']}:{WAYPOINT_CONFIG['probe']['port']}"

_tts_cfg: dict[str, Any] = {
    "api_key": "",
    "url": "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
    "model": "qwen3-tts-flash",
    "voice": "Cherry",
    "language": "Chinese",
    "phone_ip": "192.168.1.125",
    "phone_port": 9999,
}

# Context Switch States
# NOTE: Agent 调用 speak 后框架自动记录当前 waypoint 并向 controller 发送 reset 指令，防止与 agent 的讲话冲突。我们称为 Context Switch
# Speak 结束后框架向 controller 发送 jump_to 指令，恢复到原来的 waypoint。
CONTEXT_SWITCH_STATE = {
    "waypoint": None, # waypoint name
    "is_context_switch": False, # whether is in context switch
}


def apply_config(cfg: dict[str, Any]) -> None:
    """Merge values from a TTSConfig dict into the runtime config."""
    _tts_cfg.update({k: v for k, v in cfg.items() if v is not None})


def enter_context_switch() -> bool:
    """
    Fetch current waypoint from probe and reset to idle state.
    Returns True if successful, False otherwise.
    """
    if CONTEXT_SWITCH_STATE["is_context_switch"]:
        logger.warning("tts.enter_context_switch – already in context switch mode: current waypoint=%s will be overwritten",
            CONTEXT_SWITCH_STATE["waypoint"])

    try:
        resp = requests.get(f"{PROBE_URL}/status", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        waypoint_num_id = data.get("current_waypoint", "")
    except Exception as e:
        logger.error("tts.enter_context_switch – failed to GET /status: %s", e)
        return False

    if not waypoint_num_id:
        logger.warning("tts.enter_context_switch – no current waypoint reported by probe")

    try:
        resp = requests.put(f"{PROBE_URL}/reset", timeout=5)
        resp.raise_for_status()
    except Exception as e:
        logger.error("tts.enter_context_switch – failed to PUT /reset: %s", e)
        return False

    CONTEXT_SWITCH_STATE["waypoint"] = waypoint_num_id
    CONTEXT_SWITCH_STATE["is_context_switch"] = True
    logger.info("tts.enter_context_switch – saved waypoint=%s", waypoint_num_id)
    return True

def exit_context_switch() -> bool:
    """
    Exit context switch mode and jump back to the saved waypoint.
    Returns True if successful, False otherwise.
    """
    if not CONTEXT_SWITCH_STATE["is_context_switch"]:
        logger.warning("tts.exit_context_switch – not in context switch mode, skipping")
        return False

    last_wp = CONTEXT_SWITCH_STATE["waypoint"]
    if not last_wp:
        logger.warning("tts.exit_context_switch – no saved waypoint, skipping jump_to")

    try:
        resp = requests.put(f"{PROBE_URL}/tour?dst={last_wp}", timeout=5)
        resp.raise_for_status()
    except Exception as e:
        logger.error("tts.exit_context_switch – failed to PUT /tour?dst=%s: %s", last_wp, e)
        return False

    CONTEXT_SWITCH_STATE["waypoint"] = None
    CONTEXT_SWITCH_STATE["is_context_switch"] = False
    logger.info("tts.exit_context_switch – jumped back to waypoint=%s", last_wp)
    return True

# ---------------------------------------------------------------------------
# Core TTS logic
# ---------------------------------------------------------------------------

async def speak(text: str) -> str:
    """
    Synthesise *text* using Alibaba qwen3-tts-flash and stream PCM audio
    to the phone at *phone_ip:phone_port*.

    Returns a human-readable status string on success, or an error message
    on failure.
    """
    key = _tts_cfg.get("api_key") or ""
    if not key:
        return "[error] TTS API key not configured – set tts.api_key in config"

    ip = _tts_cfg.get("phone_ip", "192.168.1.125")
    port: int = _tts_cfg.get("phone_port", 9999)

    logger.info("tts.speak – text=%r -> %s:%d", text[:60], ip, port)

    enter_context_switch()

    # --- TCP socket to phone ------------------------------------------------
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((ip, port))
    except ConnectionRefusedError:
        logger.error("Connection refused by %s:%d", ip, port)
        return f"[error] Connection refused – phone not reachable at {ip}:{port}"
    except Exception as e:
        logger.error("Socket error connecting to %s:%d: %s", ip, port, e)
        return f"[error] Network error: {e}"

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-DashScope-SSE": "enable",
    }
    payload = {
        "model": _tts_cfg.get("model", "qwen3-tts-flash"),
        "input": {
            "text": text,
            "voice": _tts_cfg.get("voice", "Cherry"),
            "language_type": _tts_cfg.get("language", "Chinese"),
        },
        "parameters": {"format": "pcm"},
    }

    total_bytes = 0
    # first frame audio playback start time
    playback_start_time: float | None = None

    try:
        response = requests.post(
            _tts_cfg.get("url") or "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
            headers=headers, json=payload, stream=True, verify=False
        )

        if response.status_code != 200:
            msg = f"[error] TTS request failed: {response.status_code} – {response.text}"
            logger.error(msg)
            return msg

        frame_count = 0
        for line in response.iter_lines():
            if not line:
                continue

            decoded_line = line.decode("utf-8").strip()
            if not decoded_line.startswith("data:"):
                continue

            json_str = decoded_line[5:].strip()
            if not json_str:
                continue

            try:
                frame_data = json.loads(json_str)
            except json.JSONDecodeError:
                continue

            output_node = frame_data.get("output", {})
            audio_b64: str | None = None

            audio_node = output_node.get("audio")
            if isinstance(audio_node, dict):
                audio_b64 = audio_node.get("data")
            elif isinstance(audio_node, str):
                audio_b64 = audio_node

            if not audio_b64:
                continue

            # Decode base64 → raw PCM bytes → send to phone
            pcm_bytes = base64.b64decode(audio_b64)

            if playback_start_time is None:
                playback_start_time = time.monotonic()

            sock.sendall(pcm_bytes)
            total_bytes += len(pcm_bytes)
            frame_count += 1

        logger.info("tts.speak done – %d audio frame(s) sent", frame_count)

    except requests.exceptions.RequestException as e:
        msg = f"[error] TTS request exception: {e}"
        logger.error(msg)
        return msg
    except Exception as e:
        msg = f"[error] TTS runtime exception: {e}"
        logger.error(msg)
        return msg
    finally:
        sock.close()

    # Block until complete playing audio
    if playback_start_time is not None and total_bytes > 0:
        _BYTES_PER_SECOND = 24000 * 2 * 1  # 48000
        total_duration = total_bytes / _BYTES_PER_SECOND
        elapsed = time.monotonic() - playback_start_time
        remaining = total_duration - elapsed
        if remaining > 0:
            logger.info("tts.speak – waiting %.2fs for playback to finish", remaining)
            await asyncio.sleep(remaining)
    
    exit_context_switch()

    return f"[ok] Sent {frame_count} audio frame(s) to {ip}:{port}"

    # logger.info("tts.speak – text=%r", text)
    # return "[ok] TTS request sent"


# ---------------------------------------------------------------------------
# Tool-definition interface (for use with ToolRegistry / MCP fallback)
# ---------------------------------------------------------------------------

TOOL_NAME = "speak"
TOOL_DESCRIPTION = (
    "Convert the provided text (any language) to speech and play it on the phone. "
    "Use this tool whenever you want to talk to a user or say something out loud. "
    "Input: the text you want the robot to speak."
)

TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "description": "The Chinese text to be spoken by the robot.",
        },
    },
    "required": ["text"],
}


def get_tool_definition() -> ToolDefinition:
    """Return the OpenAI-format tool definition for the speak tool."""
    return ToolDefinition.from_parts(
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        parameters=TOOL_PARAMETERS,
    )


async def call_tool(args: dict[str, Any]) -> str:
    """
    Execute the speak tool: synthesise *text* and stream it to the phone.
    Receives the raw JSON arguments dict from the registry and returns a plain str.
    """
    text = args.get("text")
    if not text:
        return "[error] Missing required argument: 'text'"
    return await speak(text)