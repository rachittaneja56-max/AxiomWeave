"""Prepare immutable, blinded folders for the final held-out model evaluation."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

FIXTURE = Path(__file__).resolve().parents[1] / "evals" / "release" / "heldout_cases.json"
PROFILES = Path(__file__).resolve().parents[1] / "evals" / "release" / "model_profiles.json"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_run(output_root: Path, task: str, candidate_label: str) -> Path:
    if candidate_label not in {"A", "B", "C"}:
        raise ValueError("Candidate label must be A, B, or C")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    profiles = json.loads(PROFILES.read_text(encoding="utf-8"))
    profile = next((item for item in profiles["profiles"] if item["task"] == task), None)
    if profile is None:
        raise ValueError("Unknown evaluation task")
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:12]}"
    run_dir = output_root / run_id
    run_dir.mkdir(exist_ok=False)
    cases = [case for case in fixture["cases"] if case["task"] == task]
    manifest: dict[str, Any] = {
        "format_version": 1,
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "candidate_label": candidate_label,
        "task": task,
        "profile_version": profiles["registry_version"],
        "candidate_model": None,
        "final_promotion": "PENDING FINAL EVALUATION",
        "fixture_path": FIXTURE.name,
        "fixture_sha256": _digest(FIXTURE),
        "case_count": len(cases),
        "human_blind": True,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (run_dir / "fixture_snapshot.json").write_text(
        json.dumps({"profile": fixture["profile"], "cases": cases}, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "raw_outputs.json").write_text("[]\n", encoding="utf-8")
    (run_dir / "per_case_results.json").write_text(
        json.dumps(
            [
                {
                    "case_id": case["case_id"],
                    "candidate_label": candidate_label,
                    "status": "not_run",
                    "metrics": {},
                    "latency_ms": None,
                    "input_tokens": None,
                    "output_tokens": None,
                    "cost": None,
                }
                for case in cases
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "aggregate_metrics.json").write_text(
        json.dumps(
            {
                "candidate_label": candidate_label,
                "task": task,
                "denominator": len(cases),
                "completed_cases": 0,
                "metrics": {},
                "latency_ms": {"count": 0, "p50": None, "p95": None},
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": None,
                "status": "not_run",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "human_review_packet.json").write_text(
        json.dumps(
            {
                "candidate_label": candidate_label,
                "task": task,
                "blind_review": True,
                "reviewer": None,
                "review_date": None,
                "case_reviews": [
                    {
                        "case_id": case["case_id"],
                        "preference": None,
                        "quality_score": None,
                        "notes": None,
                    }
                    for case in cases
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--candidate-label", choices=("A", "B", "C"), required=True)
    args = parser.parse_args()
    print(prepare_run(args.output_root, args.task, args.candidate_label))


if __name__ == "__main__":
    main()
