"""Evaluate hybrid retrieval against a user-approved golden dataset.

Operational warning: pipeline initialization may auto-reindex the configured
``resume`` collection on corpus drift. Confirm the approved dataset and intended
Qdrant target before running. Never use production credentials; this script has
no collection-name override, so use an isolated non-production cluster.

Usage:
    python evals/scripts/run_retrieval_eval.py --k 4

Reads from:  evals/datasets/retrieval_golden_v1.jsonl
Writes to:   evals/results/retrieval_run_YYYY-MM-DD_HHMMSS.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
EVALS_DIR = SCRIPT_DIR.parent
REPO_ROOT = EVALS_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"
DATASETS_DIR = EVALS_DIR / "datasets"
RESULTS_DIR = EVALS_DIR / "results"

sys.path.insert(0, str(BACKEND_DIR))

from config import get_settings  # noqa: E402
from rag import build_corpus, initialize_rag_pipeline  # noqa: E402

VECTOR_SCORE_THRESHOLD = 0.30


def load_dataset(dataset_path: Path, corpus_titles: set[str]) -> list[dict[str, Any]]:
    """Load JSONL cases and reject titles that do not exist in the current corpus."""
    cases: list[dict[str, Any]] = []
    with dataset_path.open(encoding="utf-8") as dataset_file:
        for line_number, line in enumerate(dataset_file, 1):
            if not line.strip():
                continue
            case = json.loads(line)
            required_fields = {"id", "query", "expected_titles", "category"}
            missing_fields = required_fields - case.keys()
            if missing_fields:
                missing = ", ".join(sorted(missing_fields))
                raise ValueError(f"{dataset_path}:{line_number} missing fields: {missing}")
            unknown_titles = set(case["expected_titles"]) - corpus_titles
            if unknown_titles:
                unknown = ", ".join(sorted(unknown_titles))
                raise ValueError(
                    f"{dataset_path}:{line_number} contains unknown expected titles: {unknown}"
                )
            cases.append(case)
    if not cases:
        raise ValueError(f"Dataset contains no cases: {dataset_path}")
    return cases


def score_case(expected_titles: list[str], retrieved_titles: list[str]) -> dict[str, float | bool]:
    """Calculate hit, recall, and reciprocal rank for one retrieval case."""
    expected = set(expected_titles)
    relevant_retrieved = expected.intersection(retrieved_titles)
    first_relevant_rank = next(
        (rank for rank, title in enumerate(retrieved_titles, 1) if title in expected),
        None,
    )
    return {
        "hit": bool(relevant_retrieved),
        "recall": len(relevant_retrieved) / len(expected) if expected else 0.0,
        "reciprocal_rank": 1 / first_relevant_rank if first_relevant_rank else 0.0,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, float | int]:
    """Aggregate retrieval metrics for a result group."""
    count = len(results)
    return {
        "queries": count,
        "hit_rate": sum(bool(result["hit"]) for result in results) / count,
        "recall": sum(float(result["recall"]) for result in results) / count,
        "mrr": sum(float(result["reciprocal_rank"]) for result in results) / count,
    }


def print_summary(results: list[dict[str, Any]], output_path: Path, k: int) -> None:
    """Print overall metrics, category breakdown, and retrieval misses."""
    overall = summarize(results)
    print("\nRETRIEVAL EVAL COMPLETE")
    print(f"Queries:      {overall['queries']}")
    print(f"Hit-rate@{k}: {overall['hit_rate']:.3f}")
    print(f"Recall@{k}:   {overall['recall']:.3f}")
    print(f"MRR:          {overall['mrr']:.3f}")

    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        by_category[result["category"]].append(result)

    print("\nPer-category")
    for category in sorted(by_category):
        metrics = summarize(by_category[category])
        print(
            f"  {category}: n={metrics['queries']} "
            f"hit@{k}={metrics['hit_rate']:.3f} "
            f"recall@{k}={metrics['recall']:.3f} mrr={metrics['mrr']:.3f}"
        )

    misses = [result for result in results if not result["hit"]]
    print(f"\nMisses ({len(misses)})")
    for result in misses:
        print(f"  [{result['id']}] {result['query']}")
        print(f"    expected:  {result['expected_titles']}")
        print(f"    retrieved: {result['retrieved_titles']}")
    print(f"\nResults: {output_path}")


def run_retrieval_eval(dataset_path: Path, output_path: Path, k: int) -> None:
    """Run the configured retriever and write one scored JSON object per query."""
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for retrieval eval query embeddings.")
    if not settings.qdrant_url:
        raise RuntimeError("QDRANT_URL is required for retrieval evals.")

    resume_path = settings.data_dir / "resume.json"
    projects_dir = settings.data_dir / "projects"
    corpus = build_corpus(resume_path, projects_dir)
    cases = load_dataset(dataset_path, {chunk.title for chunk in corpus})
    pipeline = initialize_rag_pipeline(
        openai_api_key=settings.openai_api_key,
        resume_path=resume_path,
        projects_dir=projects_dir,
        qdrant_url=settings.qdrant_url,
        qdrant_api_key=settings.qdrant_api_key,
    )

    print(f"Loaded {len(cases)} approved cases from {dataset_path.name}")
    print(f"Writing incremental results to {output_path.name}")

    results: list[dict[str, Any]] = []
    for index, case in enumerate(cases, 1):
        retrieved = pipeline.search(
            case["query"],
            limit=k,
            score_threshold=VECTOR_SCORE_THRESHOLD,
        )
        retrieved_titles = [result["title"] for result in retrieved]
        metrics = score_case(case["expected_titles"], retrieved_titles)
        result = {
            "id": case["id"],
            "query": case["query"],
            "category": case["category"],
            "expected_titles": case["expected_titles"],
            "retrieved_titles": retrieved_titles,
            **metrics,
        }
        results.append(result)
        with output_path.open("a", encoding="utf-8") as output_file:
            output_file.write(json.dumps(result) + "\n")
        status = "hit" if result["hit"] else "MISS"
        print(f"[{index}/{len(cases)}] {status:4s} | {case['query'][:70]}")

    print_summary(results, output_path, k)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Resume Assistant retrieval")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DATASETS_DIR / "retrieval_golden_v1.jsonl",
        help="Path to the user-approved retrieval golden dataset",
    )
    parser.add_argument("--k", type=int, default=4, help="Number of retrieved chunks to score")
    parser.add_argument("--output", type=Path, help="Optional results JSONL path")
    args = parser.parse_args()
    if args.k < 1:
        parser.error("--k must be at least 1")
    return args


if __name__ == "__main__":
    cli_args = parse_args()
    if not cli_args.dataset.exists():
        raise SystemExit(f"Dataset not found: {cli_args.dataset}")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    result_path = cli_args.output or RESULTS_DIR / f"retrieval_run_{timestamp}.jsonl"
    if result_path.exists():
        raise SystemExit(f"Refusing to append to existing results file: {result_path}")
    run_retrieval_eval(cli_args.dataset, result_path, cli_args.k)
