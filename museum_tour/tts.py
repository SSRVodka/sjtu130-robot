import base64
import json
import socket

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# API_KEY
API_KEY = ""
URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"

# === 手机的网络配置 ===
PHONE_IP = "192.168.1.125"
PHONE_PORT = 9999


def stream_to_phone(text, target_ip, target_port):
    print(f"generating voice: {text}\n")

    # 1. 建立 TCP Socket 连接
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        print(f"connecting to {target_ip}:{target_port} ...\n")
        sock.connect((target_ip, target_port))
        print("connection established\n")
    except ConnectionRefusedError:
        print("Connection refused\n")
        return
    except Exception as e:
        print(f"network error: {e}\n")
        return

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "X-DashScope-SSE": "enable",
    }

    payload = {
        "model": "qwen3-tts-flash",
        "input": {"text": text, "voice": "Cherry", "language_type": "Chinese"},
        "parameters": {
            "format": "pcm"
            # 24000Hz, 16bit, 单声道
        },
    }

    try:
        response = requests.post(
            URL, headers=headers, json=payload, stream=True, verify=False
        )

        if response.status_code != 200:
            print(f"request failed: {response.status_code} - {response.text}\n")
            return

        for line in response.iter_lines():
            if not line:
                continue

            decoded_line = line.decode("utf-8").strip()

            if decoded_line.startswith("data:"):
                json_str = decoded_line[5:].strip()
                if not json_str:
                    continue

                try:
                    frame_data = json.loads(json_str)

                    audio_b64 = None
                    output_node = frame_data.get("output", {})
                    if "audio" in output_node:
                        audio_node = output_node["audio"]
                        if isinstance(audio_node, dict) and "data" in audio_node:
                            audio_b64 = audio_node["data"]
                        elif isinstance(audio_node, str):
                            audio_b64 = audio_node

                    if audio_b64:
                        # 2. 板子端先解码成纯粹的 PCM 字节流
                        wav_bytes = base64.b64decode(audio_b64)

                        # 3. 通过局域网 Socket 直接把裸流发给手机
                        sock.sendall(wav_bytes)

                except json.JSONDecodeError:
                    pass

    except requests.exceptions.RequestException as e:
        print(f"network request exception: {e}\n")
    except Exception as e:
        print(f"runtime exception: {e}\n")
    finally:
        sock.close()
        print("connection closed\n")


if __name__ == "__main__":
    test_text = "那我来给大家推荐一款T恤，这款呢真的是超级好看，这个颜色呢很显气质，而且呢也是搭配的绝佳单品，大家可以闭眼入，真的是非常好看，对身材的包容性也很好，不管啥身材的宝宝呢，穿上去都是很好看的。推荐宝宝们下单哦。"
    stream_to_phone(test_text, PHONE_IP, PHONE_PORT)
