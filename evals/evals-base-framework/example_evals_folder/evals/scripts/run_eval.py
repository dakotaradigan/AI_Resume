"""
Eval runner: sends synthetic queries to the Resume Assistant and collects responses.

Usage:
    python evals/scripts/run_eval.py

Reads from:  evals/datasets/synthetic_eval_v1.jsonl
Writes to:   evals/results/eval_run_YYYY-MM-DD_HHMMSS.jsonl

Each result includes the original query, the bot's response, response time,
and fields for human labeling (pass/fail + critique).
"""

import json
import time
import uuid
import argparse
from datetime import datetime
from pathlib import Path

import requests

BASE_URL = "https://chat.dakotaradigan.io"
CHAT_ENDPOINT = f"{BASE_URL}/api/chat"

# Rate limit: 20 req/min on production. Stay under with 4s between requests.
DELAY_BETWEEN_REQUESTS = 4.0

SCRIPT_DIR = Path(__file__).parent
DATASETS_DIR = SCRIPT_DIR.parent / "datasets"
RESULTS_DIR = SCRIPT_DIR.parent / "results"


def run_eval(dataset_path: Path, output_path: Path) -> None:
    """Send each query to the bot and save responses."""
    with open(dataset_path, "r", encoding="utf-8") as f:
        test_cases = [json.loads(line) for line in f if line.strip()]

    print(f"Loaded {len(test_cases)} test cases from {dataset_path.name}")
    print(f"Estimated time: ~{len(test_cases) * DELAY_BETWEEN_REQUESTS / 60:.0f} minutes")
    print(f"Writing results to {output_path.name}\n")

    results = []
    for i, case in enumerate(test_cases):
        query = case["query"]
        # Fresh session per query to avoid chat limit
        session_id = str(uuid.uuid4())

        print(f"[{i+1}/{len(test_cases)}] {case['category']:12s} | {query[:60]}...")

        start = time.time()
        try:
            resp = requests.post(
                CHAT_ENDPOINT,
                json={"message": query, "session_id": session_id},
                timeout=30,
            )
            elapsed = time.time() - start

            if resp.status_code == 200:
                data = resp.json()
                reply = data.get("reply", "")
                status = "success"
            else:
                reply = f"HTTP {resp.status_code}: {resp.text[:200]}"
                status = "error"
                elapsed = time.time() - start

        except requests.Timeout:
            reply = "TIMEOUT (30s)"
            status = "timeout"
            elapsed = 30.0
        except requests.RequestException as e:
            reply = f"REQUEST_ERROR: {e}"
            status = "error"
            elapsed = time.time() - start

        result = {
            "id": case["id"],
            "category": case["category"],
            "query": query,
            "response": reply,
            "status": status,
            "response_time_s": round(elapsed, 2),
            "expected_topics": case.get("expected_topics", []),
            "notes": case.get("notes", ""),
            # Human labeling fields (filled in during review)
            "human_label": None,  # "pass" or "fail"
            "human_critique": "",  # free-form explanation
        }
        results.append(result)

        # Write incrementally so we don't lose progress on crash
        with open(output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(result) + "\n")

        # Rate limit spacing (skip delay on last item)
        if i < len(test_cases) - 1:
            time.sleep(DELAY_BETWEEN_REQUESTS)

    # Summary
    success = sum(1 for r in results if r["status"] == "success")
    errors = sum(1 for r in results if r["status"] == "error")
    timeouts = sum(1 for r in results if r["status"] == "timeout")
    avg_time = sum(r["response_time_s"] for r in results if r["status"] == "success") / max(success, 1)

    print(f"\n{'='*50}")
    print(f"EVAL RUN COMPLETE")
    print(f"{'='*50}")
    print(f"Total:    {len(results)}")
    print(f"Success:  {success}")
    print(f"Errors:   {errors}")
    print(f"Timeouts: {timeouts}")
    print(f"Avg response time: {avg_time:.2f}s")
    print(f"Results:  {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run evals against Resume Assistant")
    parser.add_argument(
        "--dataset",
        default=str(DATASETS_DIR / "synthetic_eval_v1.jsonl"),
        help="Path to dataset file",
    )
    parser.add_argument(
        "--base-url",
        default=BASE_URL,
        help="Base URL of the Resume Assistant API",
    )
    args = parser.parse_args()

    # Allow overriding base URL (e.g. for localhost testing)
    if args.base_url != BASE_URL:
        CHAT_ENDPOINT = f"{args.base_url}/api/chat"

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"Dataset not found: {dataset_path}")
        exit(1)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    output_path = RESULTS_DIR / f"eval_run_{timestamp}.jsonl"

    run_eval(dataset_path, output_path)
