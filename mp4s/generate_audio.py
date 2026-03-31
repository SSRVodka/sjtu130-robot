import json
import os

import dashscope
import requests
import yaml

# 配置dashscope base url
dashscope.base_http_api_url = "https://dashscope.aliyuncs.com/api/v1"


def download_audio(url, path):
    print(f"正在下载音频: {url}")
    try:
        response = requests.get(url, stream=True)
        if response.status_code == 200:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"文件已保存: {path}")
        else:
            print(f"下载失败，状态码: {response.status_code}")
    except Exception as e:
        print(f"下载过程中发生错误: {e}")


def recursive_find_url(obj):
    """递归在字典/列表中寻找 http(s) 开头的 url"""
    if isinstance(obj, str):
        if obj.startswith("http") and obj.endswith(".mp3"):
            return obj
        # dashscope 可能返回如 oss:// 的 url 或是其他格式，如果确信是返回URL，一般是 http 开头
        if obj.startswith("http"):
            return obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k == "audio_url" or k == "url":
                return v
            res = recursive_find_url(v)
            if res:
                return res
    elif isinstance(obj, list):
        for item in obj:
            res = recursive_find_url(item)
            if res:
                return res
    return None


def generate_audio():
    # 获取当前 lines.yaml 的路径
    yaml_path = os.path.join(os.path.dirname(__file__), "lines.yaml")

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    model_config = data.get("model_config", {})
    model = model_config.get("model", "qwen3-tts-flash")
    voice = model_config.get("voice", "Cherry")
    language_type = model_config.get("language", "Chinese")
    api_key = model_config.get("api_key")

    waypoints = data.get("waypoints", [])

    if not api_key:
        print(
            "警告: API Key 未设置或使用了默认值！请确保在 lines.yaml 中配置了真实的 api_key。"
        )

    # project_root是包含mp4s的目录
    project_root = os.path.dirname(os.path.dirname(__file__))

    for point in waypoints:
        name = point.get("name")
        description = point.get("description")
        audio_file_rel = point.get("audio_file")

        if not description or not audio_file_rel:
            continue

        # 加上.mp3后缀（或者其他目标格式，模型通常返回mp3）
        if not audio_file_rel.endswith(".mp3"):
            audio_file_path = os.path.join(project_root, audio_file_rel + ".mp3")
        else:
            audio_file_path = os.path.join(project_root, audio_file_rel)

        print(f"\n--- 开始处理断点: {name} ---")

        # 若需要跳过已生成的文件，可取消注释下面两行
        if os.path.exists(audio_file_path):
            print(f"跳过已存在的文件: {audio_file_path}")
            continue

        try:
            # 请求音频生成
            response = dashscope.MultiModalConversation.call(
                model=model,
                api_key=api_key,
                text=description,
                voice=voice,
                language_type=language_type,
                stream=False,
            )

            if response.status_code == 200:
                # 尝试用常见的多模态返回结构提取内容
                audio_url = None

                # DashScope MultiModalConversation 常见结构
                try:
                    message_content = response.output.choices[0].message.content
                    if isinstance(message_content, list):
                        for item in message_content:
                            # 可能会有 {"audio": "http...", "type": "audio"} 形式
                            if isinstance(item, dict) and "audio" in item:
                                audio_url = item["audio"]
                            if isinstance(item, dict) and "audio_url" in item:
                                audio_url = item["audio_url"]
                    elif isinstance(message_content, dict):
                        audio_url = message_content.get("audio") or message_content.get(
                            "audio_url"
                        )
                except Exception:
                    pass

                # 如果标准解析没取到，使用递归搜索备用方案
                if not audio_url:
                    response_dict = getattr(response, "output", {})
                    audio_url = recursive_find_url(response_dict) or recursive_find_url(
                        response
                    )

                if audio_url:
                    print(f"成功获取音频URL: {audio_url}")
                    download_audio(audio_url, audio_file_path)
                else:
                    print(
                        f"模型调用成功，但在返回结果中未能提取到音频URL。完整返回包为:\n{response}"
                    )
            else:
                print(f"接口调用失败，错误信息: {response.code} - {response.message}")
        except Exception as e:
            print(f"处理时发生异常: {e}")


if __name__ == "__main__":
    generate_audio()
