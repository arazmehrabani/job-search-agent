from __future__ import annotations
import json
import warnings
import unittest
from unittest.mock import Mock, patch

from bs4 import XMLParsedAsHTMLWarning

from src.ai import AIEngine
from src.config import load_config
from src.utils import strip_html


class V171WindowsUnicodeTests(unittest.TestCase):
    def test_codex_subprocess_uses_utf8(self):
        cfg = load_config("config.yaml")
        cfg = {**cfg, "ai": {**cfg.get("ai", {}), "provider": "codex_cli"}}
        ai = AIEngine(cfg)
        ai.provider = "codex_cli"
        ai.enabled = True
        ai.codex_executable = r"C:\\fake\\codex.exe"
        completed = Mock(returncode=0, stdout='{"ok":true}', stderr='')
        unicode_payload = {"text": "München – Türme · shear/veer → 20 MW ⚙"}
        with patch("src.ai.subprocess.run", return_value=completed) as run:
            out = ai._text_call("Return JSON only.", unicode_payload, operation="test_unicode")
        self.assertEqual(out, '{"ok":true}')
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs.get("encoding"), "utf-8")
        self.assertEqual(kwargs.get("errors"), "replace")
        self.assertTrue(kwargs.get("text"))
        self.assertIn("München", kwargs.get("input", ""))
        self.assertIn("⚙", kwargs.get("input", ""))

    def test_strip_html_suppresses_xml_warning(self):
        sample = '<?xml version="1.0"?><description><p>Wind &amp; CAE – München</p></description>'
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            text = strip_html(sample)
        self.assertIn("Wind", text)
        self.assertFalse(any(issubclass(w.category, XMLParsedAsHTMLWarning) for w in caught))


if __name__ == "__main__":
    unittest.main()
