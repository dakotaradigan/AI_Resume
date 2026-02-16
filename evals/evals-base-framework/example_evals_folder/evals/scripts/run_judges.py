"""
Judge runner: sends bot responses through LLM judges for automated grading.

Usage:
    python evals/scripts/run_judges.py                        # all judges, latest eval run
    python evals/scripts/run_judges.py --judge groundedness   # one judge only
    python evals/scripts/run_judges.py --eval-run eval_run_2026-02-08_120102.jsonl

Reads from:  evals/results/eval_run_*.jsonl (bot responses)
             evals/judges/*.md              (judge prompts, auto-discovered)
             data/resume.json               (source data, for judges that need it)
Writes to:   evals/results/judge_run_YYYY-MM-DD_HHMMSS.jsonl
"""

import json
import re
import argparse
from datetime import datetime
from pathlib import Path

import anthropic

# --- Paths ---
SCRIPT_DIR = Path(__file__).parent
EVALS_DIR = SCRIPT_DIR.parent
JUDGES_DIR = EVALS_DIR / "judges"
RESULTS_DIR = EVALS_DIR / "results"
RESUME_PATH = EVALS_DIR.parent / "data" / "resume.json"

# --- Config ---
JUDGE_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 256  # Judges return short JSON, no need for more


def parse_judge_file(path: Path) -> dict:
    """Parse a judge .md file into metadata + prompt.

    Each judge file has YAML frontmatter (between --- markers) and the
    system prompt body below it. Returns a dict with keys:
        name, description, applies_to, needs_source_data, prompt
    """
    text = path.read_text(encoding="utf-8")

    # Split frontmatter from body
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"Judge file {path.name} missing YAML frontmatter (--- markers)")

    frontmatter_raw = parts[1].strip()
    prompt = parts[2].strip()

    # Parse YAML manually (avoids pyyaml dependency for 4 simple fields)
    meta = {}
    for line in frontmatter_raw.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()

        if value.startswith("[") and value.endswith("]"):
            # Parse simple list: [core, edge_case] -> ["core", "edge_case"]
            inner = value[1:-1]
            meta[key] = [item.strip() for item in inner.split(",") if item.strip()]
        elif value.lower() in ("true", "false"):
            meta[key] = value.lower() == "true"
        else:
            meta[key] = value

    return {
        "name": meta.get("name", path.stem),
        "description": meta.get("description", ""),
        "applies_to": meta.get("applies_to", []),
        "needs_source_data": meta.get("needs_source_data", False),
        "prompt": prompt,
    }


def discover_judges(judge_filter: str | None = None) -> list[dict]:
    """Find all judge .md files in the judges/ directory.

    If judge_filter is provided, only return that judge.
    Skips README.md files.
    """
    judges = []
    for path in sorted(JUDGES_DIR.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        judge = parse_judge_file(path)
        if judge_filter and judge["name"] != judge_filter:
            continue
        judges.append(judge)

    if judge_filter and not judges:
        available = [p.stem for p in JUDGES_DIR.glob("*.md") if p.name.lower() != "readme.md"]
        raise ValueError(f"Judge '{judge_filter}' not found. Available: {available}")

    return judges


def should_judge_run(judge: dict, category: str | None) -> bool:
    """Decide if a judge should run on this test case.

    Rules:
    - If the test case has no category, run all judges (production data).
    - If the judge has no applies_to list, run on everything.
    - If both exist, only run when the category is in applies_to.
    """
    if not category:
        return True
    if not judge["applies_to"]:
        return True
    return category in judge["applies_to"]


def find_latest_eval_run() -> Path:
    """Find the most recent eval_run_*.jsonl file in results/."""
    runs = sorted(RESULTS_DIR.glob("eval_run_*.jsonl"))
    if not runs:
        raise FileNotFoundError(f"No eval run files found in {RESULTS_DIR}")
    return runs[-1]


def load_eval_results(path: Path) -> list[dict]:
    """Load bot responses from an eval run JSONL file."""
    results = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))
    return results


def load_source_data() -> str:
    """Load resume.json as a string for judges that need it."""
    if not RESUME_PATH.exists():
        raise FileNotFoundError(f"Resume data not found at {RESUME_PATH}")
    return RESUME_PATH.read_text(encoding="utf-8")


def build_judge_message(judge: dict, case: dict, source_data: str | None) -> str:
    """Build the user message for a judge call.

    Assembles the context the judge needs: query, response, category,
    and optionally the source data (resume.json).
    """
    parts = [
        f"**User Query:** {case['query']}",
        f"**Bot Response:** {case['response']}",
    ]

    category = case.get("category")
    if category:
        parts.append(f"**Query Category:** {category}")

    if source_data:
        parts.append(f"**Source Data:**\n```json\n{source_data}\n```")

    return "\n\n".join(parts)


def call_judge(client: anthropic.Anthropic, judge: dict, message: str) -> dict:
    """Send a single judge call to Claude Haiku and parse the verdict.

    Returns: {"verdict": "pass"|"fail"|"unknown", "reason": "..."}
    On error: {"verdict": "error", "reason": "error description"}
    """
    try:
        response = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=MAX_TOKENS,
            system=judge["prompt"],
            messages=[{"role": "user", "content": message}],
        )

        raw = response.content[0].text.strip()

        # Parse JSON from response (handle potential markdown wrapping)
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            return {"verdict": "error", "reason": f"No JSON in response: {raw[:100]}"}

        verdict = json.loads(json_match.group())

        if verdict.get("verdict") not in ("pass", "fail", "unknown"):
            return {"verdict": "error", "reason": f"Invalid verdict value: {verdict}"}

        return verdict

    except json.JSONDecodeError as e:
        return {"verdict": "error", "reason": f"JSON parse error: {e}"}
    except anthropic.APIError as e:
        return {"verdict": "error", "reason": f"API error: {e}"}


def run_judges(
    eval_results: list[dict],
    judges: list[dict],
    source_data: str | None,
    output_path: Path,
) -> None:
    """Run all judges against all eval results and write verdicts."""
    client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY from env

    total_calls = 0
    skipped = 0
    errors = 0

    print(f"Judges:  {[j['name'] for j in judges]}")
    print(f"Cases:   {len(eval_results)}")
    print(f"Output:  {output_path.name}\n")

    for i, case in enumerate(eval_results):
        case_id = case.get("id", i + 1)
        category = case.get("category")

        # Skip cases that errored during eval (no response to judge)
        if case.get("status") not in (None, "success"):
            continue

        for judge in judges:
            if not should_judge_run(judge, category):
                skipped += 1
                continue

            # Build context for this judge
            include_source = judge["needs_source_data"] and source_data
            message = build_judge_message(
                judge, case, source_data if include_source else None
            )

            # Call the judge
            verdict = call_judge(client, judge, message)
            total_calls += 1

            if verdict["verdict"] == "error":
                errors += 1

            # Build output record
            record = {
                "case_id": case_id,
                "judge": judge["name"],
                "category": category,
                "query": case["query"],
                "verdict": verdict["verdict"],
                "reason": verdict.get("reason", ""),
            }

            # Write incrementally
            with open(output_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")

            status_icon = {"pass": "+", "fail": "-", "unknown": "?", "error": "!"}[verdict["verdict"]]
            print(
                f"  [{status_icon}] #{case_id:>3d} | {judge['name']:20s} | "
                f"{verdict['verdict']:5s} | {verdict.get('reason', '')[:60]}"
            )

        # Progress marker between cases
        if (i + 1) % 10 == 0:
            print(f"\n--- {i + 1}/{len(eval_results)} cases processed ---\n")

    # Summary
    print(f"\n{'='*50}")
    print(f"JUDGE RUN COMPLETE")
    print(f"{'='*50}")
    print(f"Total judge calls: {total_calls}")
    print(f"Skipped (category mismatch): {skipped}")
    print(f"Errors: {errors}")
    print(f"Results: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run LLM judges on eval results")
    parser.add_argument(
        "--judge",
        default=None,
        help="Run only this judge (e.g. 'groundedness')",
    )
    parser.add_argument(
        "--eval-run",
        default=None,
        help="Eval run file to judge (default: latest)",
    )
    args = parser.parse_args()

    # Discover judges
    judges = discover_judges(args.judge)
    print(f"Discovered {len(judges)} judge(s): {[j['name'] for j in judges]}")

    # Load eval results
    if args.eval_run:
        eval_path = RESULTS_DIR / args.eval_run
    else:
        eval_path = find_latest_eval_run()
    print(f"Loading eval results from: {eval_path.name}")

    eval_results = load_eval_results(eval_path)

    # Load source data (for groundedness judge)
    source_data = None
    if any(j["needs_source_data"] for j in judges):
        print(f"Loading source data from: {RESUME_PATH.name}")
        source_data = load_source_data()

    # Output path
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    output_path = RESULTS_DIR / f"judge_run_{timestamp}.jsonl"

    run_judges(eval_results, judges, source_data, output_path)
