#!/usr/bin/env python3
"""Build frontend/sample-fitmap.json, the saved analysis behind the
"See a sample" heat map on the home page.

The sample lets a recruiter see the heat map before uploading anything. The
role in data/sample_jd.txt is invented and labelled "Sample role" on the
page; the scores are not. This script sends that role through the same Jev
requests a real analysis makes and saves the answers, so the sample shows
exactly what the live feature would show for that text.

Run from the repository root, with the app's environment (backend/.env or
exported variables) providing TYPESAFE_API_KEY:

    PYTHONPATH=backend python scripts/build_sample_fitmap.py

Run it again after changing data/resume.json, data/sample_jd.txt, the
evidence levels, or the matrix columns: the saved scores do not update
themselves. Until the file holds a map, the page hides the sample link.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_JD = ROOT / "data" / "sample_jd.txt"
OUTPUT = ROOT / "frontend" / "sample-fitmap.json"


async def build_sample() -> dict | None:
    # Imported here so `--help`-style reading of this file needs no backend.
    from app.config import get_settings
    from app.content import load_resume_context, load_resume_json_public
    from app.fit_map import build_fit_map

    settings = get_settings()
    if not settings.typesafe_api_key:
        raise SystemExit("TYPESAFE_API_KEY is not set; the sample needs real Jev answers.")
    jd_text = SAMPLE_JD.read_text(encoding="utf-8")
    fit_map = await build_fit_map(
        jd_text, load_resume_context(), settings, resume=load_resume_json_public()
    )
    if fit_map is None:
        return None
    return {"role": jd_text.strip().splitlines()[0], "fitmap": fit_map}


def main() -> int:
    sample = asyncio.run(build_sample())
    if sample is None:
        print("Jev returned no map; frontend/sample-fitmap.json was left unchanged.", file=sys.stderr)
        return 1
    OUTPUT.write_text(json.dumps(sample, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    fit_map = sample["fitmap"]
    matrix = "with" if fit_map.get("columns") else "WITHOUT"
    print(f"Wrote {OUTPUT.relative_to(ROOT)}: {len(fit_map['requirements'])} requirements, {matrix} the matrix.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
