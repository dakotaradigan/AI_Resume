"""The share card: link unfurlers read the Open Graph and Twitter tags, so
the tags, the image they point at, and the image's size are pinned here."""

from __future__ import annotations

import os
import re
import struct
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

# Prevent importing app.main from initializing an external RAG connection.
os.environ["USE_RAG"] = "false"

from app import main as app_main
from app.constants import SITE_URL

from tests.test_chat_stream import make_settings

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
CARD = FRONTEND / "share-card.png"
CARD_URL = f"{SITE_URL}/share-card.png"
PAGES = {
    "index.html": f"{SITE_URL}/",
    "how-it-works.html": f"{SITE_URL}/how-it-works.html",
}


def meta(html: str, attribute: str, name: str) -> str | None:
    match = re.search(rf'<meta {attribute}="{re.escape(name)}" content="([^"]*)"', html)
    return match.group(1) if match else None


def png_size(path: Path) -> tuple[int, int]:
    """Width and height from the PNG header, no image library needed."""
    with path.open("rb") as handle:
        header = handle.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise AssertionError(f"{path.name} is not a PNG")
    return struct.unpack(">II", header[16:24])


class TestShareCardTags(unittest.TestCase):
    def test_every_page_carries_the_card(self) -> None:
        for page, url in PAGES.items():
            with self.subTest(page=page):
                html = (FRONTEND / page).read_text(encoding="utf-8")
                self.assertIn(f'<link rel="canonical" href="{url}" />', html)
                self.assertEqual(meta(html, "property", "og:url"), url)
                self.assertEqual(meta(html, "property", "og:image"), CARD_URL)
                self.assertEqual(meta(html, "property", "og:image:width"), "1200")
                self.assertEqual(meta(html, "property", "og:image:height"), "630")
                self.assertEqual(meta(html, "name", "twitter:card"), "summary_large_image")
                self.assertEqual(meta(html, "name", "twitter:image"), CARD_URL)
                for tag in ("og:title", "og:description", "og:image:alt"):
                    self.assertTrue(meta(html, "property", tag), f"{page} lacks {tag}")

    def test_card_is_1200_by_630(self) -> None:
        self.assertEqual(png_size(CARD), (1200, 630))
        # Unfurlers fetch the card on every share; keep it well under a megabyte.
        self.assertLess(CARD.stat().st_size, 900_000)

    def test_card_is_served_as_png(self) -> None:
        with (
            patch.object(app_main, "get_settings", return_value=make_settings()),
            patch.object(app_main, "initialize_rag", return_value=None),
        ):
            client = TestClient(app_main.build_app())
        with client:
            response = client.get("/share-card.png")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
