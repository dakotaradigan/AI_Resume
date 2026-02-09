"""
Judge validator: compares LLM judge verdicts to human labels.

Usage:
    python evals/scripts/validate_judges.py
    python evals/scripts/validate_judges.py --judge-run judge_run_2026-02-08_120102.jsonl

Reads from:  evals/results/judge_run_*.jsonl   (judge verdicts)
             evals/results/human_labeled_results.jsonl  (human labels)
Writes to:   stdout (TPR/TNR per judge + disagreement details)

Key metrics:
    TPR (True Positive Rate): Of cases humans marked "pass", how many did the judge also pass?
    TNR (True Negative Rate): Of cases humans marked "fail", how many did the judge also fail?

We prioritize TNR — catching every failure matters more than avoiding false alarms.
Target: TNR > 80%, TPR > 85%
"""

import json
import argparse
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
RESULTS_DIR = SCRIPT_DIR.parent / "results"
HUMAN_LABELS_PATH = RESULTS_DIR / "human_labeled_results.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    """Load a JSONL file into a list of dicts."""
    results = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))
    return results


def find_latest_judge_run() -> Path:
    """Find the most recent judge_run_*.jsonl file."""
    runs = sorted(RESULTS_DIR.glob("judge_run_*.jsonl"))
    if not runs:
        raise FileNotFoundError(f"No judge run files found in {RESULTS_DIR}")
    return runs[-1]


def build_human_label_map(human_results: list[dict]) -> dict[int, dict]:
    """Build a lookup from case_id -> human label data.

    Returns: {case_id: {"label": "pass"|"fail", "critique": "..."}}
    Skips cases without a human label (empty or None).
    """
    label_map = {}
    for case in human_results:
        label = case.get("human_label", "")
        if not label or label not in ("pass", "fail"):
            continue
        label_map[case["id"]] = {
            "label": label,
            "critique": case.get("human_critique", ""),
            "query": case.get("query", ""),
        }
    return label_map


def validate(judge_verdicts: list[dict], human_labels: dict[int, dict]) -> None:
    """Compare judge verdicts to human labels and print TPR/TNR."""

    # Group verdicts by judge name
    by_judge: dict[str, list[dict]] = defaultdict(list)
    for v in judge_verdicts:
        if v["verdict"] == "error":
            continue  # Skip errored judge calls
        by_judge[v["judge"]].append(v)

    print(f"\n{'='*60}")
    print(f"JUDGE VALIDATION REPORT")
    print(f"{'='*60}")
    print(f"Human labels available: {len(human_labels)}")
    print(f"Judges evaluated: {list(by_judge.keys())}\n")

    for judge_name, verdicts in sorted(by_judge.items()):
        print(f"\n--- {judge_name.upper()} ---")

        # Counters
        true_pos = 0   # human=pass, judge=pass
        false_neg = 0  # human=pass, judge=fail  (judge too strict)
        true_neg = 0   # human=fail, judge=fail
        false_pos = 0  # human=fail, judge=pass  (judge too lenient)
        no_label = 0   # no human label for this case

        disagreements = []

        for v in verdicts:
            case_id = v["case_id"]
            human = human_labels.get(case_id)

            if not human:
                no_label += 1
                continue

            human_label = human["label"]
            judge_verdict = v["verdict"]

            if human_label == "pass" and judge_verdict == "pass":
                true_pos += 1
            elif human_label == "pass" and judge_verdict == "fail":
                false_neg += 1
                disagreements.append({
                    "case_id": case_id,
                    "type": "FALSE_NEG (judge too strict)",
                    "query": v.get("query", "")[:60],
                    "judge_reason": v.get("reason", ""),
                    "human_critique": human.get("critique", ""),
                })
            elif human_label == "fail" and judge_verdict == "fail":
                true_neg += 1
            elif human_label == "fail" and judge_verdict == "pass":
                false_pos += 1
                disagreements.append({
                    "case_id": case_id,
                    "type": "FALSE_POS (judge too lenient)",
                    "query": v.get("query", "")[:60],
                    "judge_reason": v.get("reason", ""),
                    "human_critique": human.get("critique", ""),
                })

        # Compute rates
        total_human_pass = true_pos + false_neg
        total_human_fail = true_neg + false_pos

        tpr = (true_pos / total_human_pass * 100) if total_human_pass > 0 else 0
        tnr = (true_neg / total_human_fail * 100) if total_human_fail > 0 else 0

        total_compared = true_pos + false_neg + true_neg + false_pos
        agreement = ((true_pos + true_neg) / total_compared * 100) if total_compared > 0 else 0

        # Print results
        print(f"  Cases judged:     {len(verdicts)}")
        print(f"  With human label: {total_compared}")
        print(f"  No human label:   {no_label}")
        print()
        print(f"  Confusion Matrix:")
        print(f"                    Judge Pass    Judge Fail")
        print(f"  Human Pass        {true_pos:>6d}        {false_neg:>6d}")
        print(f"  Human Fail        {false_pos:>6d}        {true_neg:>6d}")
        print()
        print(f"  TPR (sensitivity): {tpr:5.1f}%  (target: >85%)")
        print(f"  TNR (specificity): {tnr:5.1f}%  (target: >80%)")
        print(f"  Agreement:         {agreement:5.1f}%")

        # Status
        tpr_ok = tpr >= 85
        tnr_ok = tnr >= 80
        if tpr_ok and tnr_ok:
            print(f"  Status: PASSING")
        else:
            issues = []
            if not tnr_ok:
                issues.append(f"TNR below 80% (judge is too lenient)")
            if not tpr_ok:
                issues.append(f"TPR below 85% (judge is too strict)")
            print(f"  Status: NEEDS TUNING - {'; '.join(issues)}")

        # Show disagreements
        if disagreements:
            print(f"\n  Disagreements ({len(disagreements)}):")
            for d in disagreements[:10]:  # Show max 10
                print(f"    #{d['case_id']:>3d} [{d['type']}]")
                print(f"         Query:  {d['query']}")
                print(f"         Judge:  {d['judge_reason'][:80]}")
                print(f"         Human:  {d['human_critique'][:80]}")
                print()
            if len(disagreements) > 10:
                print(f"    ... and {len(disagreements) - 10} more disagreements")

    print(f"\n{'='*60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate LLM judges against human labels")
    parser.add_argument(
        "--judge-run",
        default=None,
        help="Judge run file to validate (default: latest)",
    )
    parser.add_argument(
        "--human-labels",
        default=str(HUMAN_LABELS_PATH),
        help="Path to human-labeled results",
    )
    args = parser.parse_args()

    # Load judge verdicts
    if args.judge_run:
        judge_path = RESULTS_DIR / args.judge_run
    else:
        judge_path = find_latest_judge_run()
    print(f"Loading judge verdicts from: {judge_path.name}")
    judge_verdicts = load_jsonl(judge_path)

    # Load human labels
    human_path = Path(args.human_labels)
    if not human_path.exists():
        print(f"Human labels not found: {human_path}")
        print("Run parse_review.py first to generate human_labeled_results.jsonl")
        exit(1)
    print(f"Loading human labels from: {human_path.name}")
    human_results = load_jsonl(human_path)
    human_labels = build_human_label_map(human_results)

    validate(judge_verdicts, human_labels)
