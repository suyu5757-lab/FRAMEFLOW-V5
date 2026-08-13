"""FRAMEFLOW local server with OpenAI image and speech proxies."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import urllib.error
import urllib.request
import wave
from email.parser import BytesParser
from email.policy import default as email_policy
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
GENERATED_DIR = ROOT / "generated"
GENERATED_AUDIO_DIR = GENERATED_DIR / "audio"
REFERENCE_AUDIO_DIR = GENERATED_AUDIO_DIR / "references"
OPENAI_IMAGES_URL = "https://api.openai.com/v1/images/generations"
OPENAI_SPEECH_URL = "https://api.openai.com/v1/audio/speech"
ALLOWED_SIZES = {"1024x1024", "1024x1536", "1536x1024"}
ALLOWED_QUALITIES = {"low", "medium", "high"}
ALLOWED_TTS_MODELS = {"gpt-4o-mini-tts", "gpt-4o-mini-tts-2025-12-15"}
ALLOWED_TTS_VOICES = {"alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer", "verse", "marin", "cedar"}
ALLOWED_AUDIO_FORMATS = {"mp3", "opus", "aac", "flac", "wav", "pcm"}
ALLOWED_IMPORT_EXTENSIONS = {".mp3", ".m4a", ".wav", ".ogg", ".aac", ".flac", ".webm", ".mp4"}
MAX_JSON_BODY = 100_000
MAX_AUDIO_UPLOAD = 25 * 1024 * 1024


class FrameflowHandler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path.split("?", 1)[0] == "/api/health":
            self._json_response(HTTPStatus.OK, {"status": "ok", "openai_configured": bool(os.environ.get("OPENAI_API_KEY")), "audio": True, "images": True})
            return
        if self._is_private_path():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler API
        if self._is_private_path():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        super().do_HEAD()

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        route = self.path.split("?", 1)[0]
        if route == "/api/audio/import":
            self._import_audio()
            return
        if route == "/api/audio/speech":
            self._generate_speech()
            return
        if route != "/api/images/generate":
            self._json_response(HTTPStatus.NOT_FOUND, {"error": "接口不存在。"})
            return

        try:
            payload = self._read_json()
            prompt = str(payload.get("prompt", "")).strip()
            if not prompt:
                self._json_response(HTTPStatus.BAD_REQUEST, {"error": "Prompt 不能为空。"})
                return

            api_key = os.environ.get("OPENAI_API_KEY", "").strip()
            if not api_key:
                self._json_response(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": "尚未配置 OPENAI_API_KEY。请在启动工作台前设置环境变量。"},
                )
                return

            size = payload.get("size", "1024x1024")
            quality = payload.get("quality", "medium")
            if size not in ALLOWED_SIZES or quality not in ALLOWED_QUALITIES:
                self._json_response(HTTPStatus.BAD_REQUEST, {"error": "图片尺寸或质量参数无效。"})
                return

            upstream = self._call_openai(api_key, prompt, size, quality)
            image_data = upstream.get("data", [{}])[0].get("b64_json")
            if not image_data:
                raise ValueError("OpenAI 响应中没有图片数据。")

            GENERATED_DIR.mkdir(exist_ok=True)
            filename = f"frameflow-{secrets.token_hex(8)}.png"
            (GENERATED_DIR / filename).write_bytes(base64.b64decode(image_data))
            self._json_response(
                HTTPStatus.OK,
                {
                    "url": f"/generated/{filename}",
                    "filename": filename,
                    "model": "gpt-image-2",
                    "size": size,
                    "quality": quality,
                    "revised_prompt": upstream.get("data", [{}])[0].get("revised_prompt"),
                },
            )
        except json.JSONDecodeError:
            self._json_response(HTTPStatus.BAD_REQUEST, {"error": "请求不是有效 JSON。"})
        except urllib.error.HTTPError as exc:
            detail = self._upstream_error(exc)
            self._json_response(exc.code, {"error": detail})
        except (ValueError, OSError, urllib.error.URLError) as exc:
            self._json_response(HTTPStatus.BAD_GATEWAY, {"error": str(exc)})

    def _generate_speech(self) -> None:
        try:
            payload = self._read_json()
            text = str(payload.get("text", "")).strip()
            model = str(payload.get("model", "gpt-4o-mini-tts"))
            voice = str(payload.get("voice", "coral"))
            audio_format = str(payload.get("format", "wav"))
            instructions = str(payload.get("instructions", "")).strip()
            speed = float(payload.get("speed", 1.0))
            dialogue_id = str(payload.get("dialogue_id", "DLG")).strip()
            if not text or len(text) > 4096:
                self._json_response(HTTPStatus.BAD_REQUEST, {"error": "配音文本必须为 1–4096 个字符。"})
                return
            if model not in ALLOWED_TTS_MODELS or voice not in ALLOWED_TTS_VOICES or audio_format not in ALLOWED_AUDIO_FORMATS or not 0.25 <= speed <= 4.0:
                self._json_response(HTTPStatus.BAD_REQUEST, {"error": "TTS 模型、声音、格式或速度参数无效。"})
                return
            api_key = os.environ.get("OPENAI_API_KEY", "").strip()
            if not api_key:
                self._json_response(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "尚未配置 OPENAI_API_KEY。请设置环境变量后重启工作台。"})
                return
            body = {"model": model, "input": text, "voice": voice, "response_format": audio_format, "speed": speed}
            if instructions:
                body["instructions"] = instructions
            audio_bytes = self._call_openai_binary(OPENAI_SPEECH_URL, api_key, body)
            GENERATED_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
            safe_dialogue = "".join(c for c in dialogue_id if c.isalnum() or c in "_-")[:40] or "DLG"
            filename = f"{safe_dialogue}-{secrets.token_hex(8)}.{audio_format}"
            destination = GENERATED_AUDIO_DIR / filename
            destination.write_bytes(audio_bytes)
            self._json_response(HTTPStatus.OK, {"url": f"/generated/audio/{filename}", "filename": filename, "model": model, "voice": voice, "format": audio_format, "duration": self._audio_duration(destination)})
        except json.JSONDecodeError:
            self._json_response(HTTPStatus.BAD_REQUEST, {"error": "请求不是有效 JSON。"})
        except urllib.error.HTTPError as exc:
            self._json_response(exc.code, {"error": self._upstream_error(exc)})
        except (ValueError, OSError, urllib.error.URLError) as exc:
            self._json_response(HTTPStatus.BAD_GATEWAY, {"error": str(exc)})

    def _import_audio(self) -> None:
        try:
            length = self._content_length(MAX_AUDIO_UPLOAD)
            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in content_type:
                self._json_response(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "请使用 multipart/form-data 上传音频。"})
                return
            message = BytesParser(policy=email_policy).parsebytes(f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + self.rfile.read(length))
            part = next((item for item in message.iter_parts() if item.get_param("name", header="content-disposition") == "file"), None)
            if part is None:
                self._json_response(HTTPStatus.BAD_REQUEST, {"error": "缺少音频文件。"})
                return
            original_name = Path(part.get_filename() or "reference.wav").name
            extension = Path(original_name).suffix.lower()
            data = part.get_payload(decode=True) or b""
            if extension not in ALLOWED_IMPORT_EXTENSIONS or not data:
                self._json_response(HTTPStatus.BAD_REQUEST, {"error": "音频格式不受支持或文件为空。"})
                return
            REFERENCE_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
            filename = f"voice-ref-{secrets.token_hex(8)}{extension}"
            destination = REFERENCE_AUDIO_DIR / filename
            destination.write_bytes(data)
            self._json_response(HTTPStatus.OK, {"url": f"/generated/audio/references/{filename}", "filename": filename, "original_name": original_name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "format": extension.lstrip("."), "duration": self._audio_duration(destination)})
        except (ValueError, OSError) as exc:
            self._json_response(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def _read_json(self) -> dict:
        length = self._content_length(MAX_JSON_BODY)
        return json.loads(self.rfile.read(length) or b"{}")

    def _content_length(self, maximum: int) -> int:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Content-Length 无效。") from exc
        if length <= 0 or length > maximum:
            raise ValueError(f"请求内容必须为 1–{maximum} 字节。")
        return length

    def _is_private_path(self) -> bool:
        clean_path = self.path.split("?", 1)[0]
        return clean_path.startswith("/.") or clean_path.startswith("/__pycache__") or clean_path.startswith("/tests") or clean_path in {"/server.py", "/启动工作台.bat"}

    def _call_openai(self, api_key: str, prompt: str, size: str, quality: str) -> dict:
        body = json.dumps(
            {
                "model": "gpt-image-2",
                "prompt": prompt,
                "size": size,
                "quality": quality,
                "output_format": "png",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            OPENAI_IMAGES_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.load(response)

    @staticmethod
    def _call_openai_binary(url: str, api_key: str, body: dict) -> bytes:
        request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=300) as response:
            return response.read()

    @staticmethod
    def _audio_duration(path: Path) -> float | None:
        if path.suffix.lower() != ".wav":
            return None
        try:
            with wave.open(str(path), "rb") as audio:
                return round(audio.getnframes() / audio.getframerate(), 3)
        except (wave.Error, ZeroDivisionError, OSError):
            return None

    @staticmethod
    def _upstream_error(exc: urllib.error.HTTPError) -> str:
        try:
            data = json.loads(exc.read().decode("utf-8"))
            return data.get("error", {}).get("message") or f"OpenAI API 返回 {exc.code}。"
        except (json.JSONDecodeError, UnicodeDecodeError):
            return f"OpenAI API 返回 {exc.code}。"

    def _json_response(self, status: int, payload: dict) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    os.chdir(ROOT)
    server = ThreadingHTTPServer(("127.0.0.1", 8787), FrameflowHandler)
    print("FRAMEFLOW 工作台：http://127.0.0.1:8787")
    print("图片生成：" + ("已检测到 OPENAI_API_KEY" if os.environ.get("OPENAI_API_KEY") else "未配置 OPENAI_API_KEY"))
    print("配音生成：" + ("已检测到 OPENAI_API_KEY" if os.environ.get("OPENAI_API_KEY") else "未配置 OPENAI_API_KEY"))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n工作台已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
