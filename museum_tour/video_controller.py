from enum import Enum
import logging
import socket
import threading
import time
from typing import Tuple

from actions import register
from robot_client import RobotClient

logger = logging.getLogger(__name__)


class VideoCmd(Enum):
    # (command code, description, action dwell time in seconds, handle reset cmd-code sequence)
    PLAY_ENTRY_MAIN_VIDEO = (33, "入口大屏视频播放", 5*60, (34,))
    MUTE_ENTRY_MAIN_VIDEO = (34, "入口大屏视频静音", 0, None)
    UNMUTE_ENTRY_MAIN_VIDEO = (35, "入口大屏视频取消静音", 0, (34,))
    PLAY_THREE_FOLDER_VIDEO = (203, "三折叠视频播放", 170, (204,))
    MUTE_THREE_FOLDER_VIDEO = (204, "三折叠视频静音", 0, None)
    UNMUTE_THREE_FOLDER_VIDEO = (205, "三折叠视频取消静音", 0, (204,))
    PLAY_JAKA_ARM_DANCE = (256, "JAKA 机械臂表演播放", 100, (260,257,255))
    MUTE_JAKA_ARM_DANCE = (260, "JAKA 机械臂表演静音", 0, None)
    RESET_JAKA_ARM_DANCE = (255, "JAKA 机械臂表演复位", 0, None)
    STOP_JAKA_ARM_DANCE = (257, "JAKA 机械臂表演停止", 0, None)
    PLAY_UNCHARTED_TERRITORY_VIDEO = (243, "未至之境视频播放", 148, (244,))
    MUTE_UNCHARTED_TERRITORY_VIDEO = (244, "未至之境视频静音", 0, None)

    def __init__(self, code: int, description: str, duration: int, reset_sequence: Tuple[int, ...] | None):
        self.code = code
        self._desc = description
        self.duration = duration
        self.reset_sequence = reset_sequence
    
    def get_description(self) -> str:
        return self._desc
    
    # NOTE: poor O(n) performance
    @staticmethod
    def from_code(cmd_code: int) -> "VideoCmd":
        for member in VideoCmd:
            if member.code == cmd_code:
                return member
        raise ValueError(f"No VideoCmd found with code {cmd_code}")


def play_video(command_code: VideoCmd, host="192.168.1.20", port=8999) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
        send_data = str(command_code.code).encode("utf-8")
        udp_socket.sendto(send_data, (host, port))
        return f"Command code [{command_code}:{command_code.get_description()}] is sent to {host}:{port} via UDP"


def create_play_action(cmd: VideoCmd, action_name: str | None = None):
    if action_name is None:
        action_name = cmd.name.lower()
    
    @register(action_name)
    def play_action(client: RobotClient, waypoint_name: str, interrupt: threading.Event):
        logger.info(play_video(cmd))
        
        if cmd.duration > 0 and interrupt.wait(cmd.duration):
            logger.warning(f"Action '{action_name}' interrupted")
            if cmd.reset_sequence is not None:
                for reset_cmd in cmd.reset_sequence:
                    try:
                        logger.warning(play_video(VideoCmd.from_code(reset_cmd)))
                        time.sleep(0.5)
                    except Exception as e:
                        logger.error(f"reset handle sequence failed: {e}")
            return
        
        logger.info(f"Action '{action_name}' completed")
    
    return play_action


PLAYABLE_COMMANDS = [
    VideoCmd.PLAY_ENTRY_MAIN_VIDEO,
    VideoCmd.MUTE_ENTRY_MAIN_VIDEO,
    VideoCmd.UNMUTE_ENTRY_MAIN_VIDEO,
    VideoCmd.PLAY_THREE_FOLDER_VIDEO,
    VideoCmd.MUTE_THREE_FOLDER_VIDEO,
    VideoCmd.UNMUTE_THREE_FOLDER_VIDEO,
    VideoCmd.PLAY_JAKA_ARM_DANCE,
    VideoCmd.MUTE_JAKA_ARM_DANCE,
    VideoCmd.RESET_JAKA_ARM_DANCE,
    VideoCmd.STOP_JAKA_ARM_DANCE,
    VideoCmd.PLAY_UNCHARTED_TERRITORY_VIDEO,
    VideoCmd.MUTE_UNCHARTED_TERRITORY_VIDEO,
]

for cmd in PLAYABLE_COMMANDS:
    create_play_action(cmd)

