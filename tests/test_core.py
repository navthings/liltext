import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from liltext.attachments import image_b64
from liltext.config import ChatConfig
from liltext.context import model_trigger, parse_trigger
from liltext.messages import Attachment, Message, decode_body
from liltext.ollama import OllamaError


class CoreTests(unittest.TestCase):
    def test_config_roundtrip(self):
        cfg = ChatConfig.from_dict({"name": "AI", "models": ["a"], "context_messages": 0, "max_chain": -1})
        self.assertEqual(cfg.context_messages, 1)
        self.assertEqual(cfg.max_chain, 0)
        self.assertEqual(ChatConfig.from_dict(cfg.to_dict()).to_dict(), cfg.to_dict())

    def test_triggers(self):
        models = ["navthings/lilchat:q8_0", "navthings/lilbase:q4_K_M"]
        self.assertEqual(model_trigger(models[0]), "lilchat")
        self.assertEqual(parse_trigger("@lilchat explain transformers", models).prompt, "explain transformers")
        self.assertEqual(parse_trigger("lilbase, explain transformers", models).trigger, "lilbase")
        self.assertTrue(parse_trigger("@all explain this", models).all_models)
        self.assertIsNone(parse_trigger("@llama3 hi", models))

    def test_attributed_body(self):
        self.assertEqual(decode_body(b"xxNSString12345\x05hello"), "hello")

    def test_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "photo.png"
            p.write_bytes(b"hello")
            result = image_b64((Attachment(p, "image/png", "photo.png"),))
            self.assertEqual(result, base64.b64encode(b"hello").decode())

    def test_image_missing_is_safe(self):
        self.assertIsNone(image_b64((Attachment(Path("/does/not/exist.png"), "image/png", None),)))

    def test_ollama_http_error_is_readable(self):
        from urllib.error import HTTPError
        from unittest.mock import patch
        error = HTTPError("http://localhost:11434/api/chat", 404, "not found", {}, None)
        error.read = lambda: b'{"error":"model missing not found"}'
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(OllamaError, "model"):
                from liltext.ollama import chat
                chat("missing", [])


if __name__ == "__main__":
    unittest.main()
