from __future__ import annotations

import io
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import server


class ServerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.FrameflowHandler)
        cls.base_url = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def request(self, path: str, data: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict]:
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                result = json.load(exc)
                exc.close()
                return exc.code, result
            except json.JSONDecodeError:
                exc.close()
                return exc.code, {}

    @staticmethod
    def wav_bytes() -> bytes:
        output = io.BytesIO()
        with wave.open(output, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\0\0" * 1600)
        return output.getvalue()

    def test_health_and_private_paths(self) -> None:
        status, body = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        status, _ = self.request("/server.py")
        self.assertEqual(status, 404)

    def test_tts_requires_key_and_validates_parameters(self) -> None:
        payload = json.dumps({"text": "测试", "model": "gpt-4o-mini-tts", "voice": "coral", "format": "wav", "speed": 1}).encode()
        with mock.patch.dict(os.environ, {}, clear=True):
            status, body = self.request("/api/audio/speech", payload, {"Content-Type": "application/json"})
        self.assertEqual(status, 503)
        self.assertIn("OPENAI_API_KEY", body["error"])
        invalid = json.dumps({"text": "测试", "model": "bad-model", "voice": "coral", "format": "wav", "speed": 1}).encode()
        status, _ = self.request("/api/audio/speech", invalid, {"Content-Type": "application/json"})
        self.assertEqual(status, 400)

    def test_tts_success_writes_versionable_file(self) -> None:
        filename = "DLG001-fixedtoken.wav"
        destination = server.GENERATED_AUDIO_DIR / filename
        payload = json.dumps({"text": "不要开门。", "model": "gpt-4o-mini-tts", "voice": "coral", "format": "wav", "speed": 0.95, "dialogue_id": "DLG001"}).encode()
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(server.secrets, "token_hex", return_value="fixedtoken"), mock.patch.object(server.FrameflowHandler, "_call_openai_binary", return_value=self.wav_bytes()):
            status, body = self.request("/api/audio/speech", payload, {"Content-Type": "application/json"})
        try:
            self.assertEqual(status, 200)
            self.assertEqual(body["url"], f"/generated/audio/{filename}")
            self.assertEqual(body["duration"], 0.1)
            self.assertTrue(destination.is_file())
        finally:
            if destination.is_file():
                destination.unlink()

    def test_reference_upload_hashes_and_saves_locally(self) -> None:
        boundary = "frameflow-test-boundary"
        audio = self.wav_bytes()
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"reference.wav\"\r\nContent-Type: audio/wav\r\n\r\n".encode() + audio + f"\r\n--{boundary}--\r\n".encode())
        filename = "voice-ref-fixedref.wav"
        destination = server.REFERENCE_AUDIO_DIR / filename
        with mock.patch.object(server.secrets, "token_hex", return_value="fixedref"):
            status, response = self.request("/api/audio/import", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            self.assertEqual(status, 200)
            self.assertEqual(response["filename"], filename)
            self.assertEqual(response["duration"], 0.1)
            self.assertEqual(len(response["sha256"]), 64)
            self.assertTrue(destination.is_file())
        finally:
            if destination.is_file():
                destination.unlink()


if __name__ == "__main__":
    unittest.main()
