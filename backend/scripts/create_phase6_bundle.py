"""Create a compact, source-safe Phase 6 CI review bundle."""

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _junit_summary(path: Path) -> dict[str, object]:
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    selected = [
        case
        for case in cases
        if any(
            marker in f"{case.get('classname', '')}.{case.get('name', '')}"
            for marker in ("test_phase6_security", "test_recovery", "test_release_harness")
        )
    ]
    failures = sum(case.find("failure") is not None for case in selected)
    errors = sum(case.find("error") is not None for case in selected)
    skipped = sum(case.find("skipped") is not None for case in selected)
    return {
        "phase6_testcases": [
            {
                "name": f"{case.get('classname', '')}.{case.get('name', '')}",
                "status": (
                    "failed"
                    if case.find("failure") is not None or case.find("error") is not None
                    else "skipped"
                    if case.find("skipped") is not None
                    else "passed"
                ),
            }
            for case in selected
        ],
        "phase6_counts": {
            "total": len(selected),
            "failures": failures,
            "errors": errors,
            "skipped": skipped,
            "passed": len(selected) - failures - errors - skipped,
        },
    }


def create_bundle(sha: str, junit_paths: list[Path], output_dir: Path) -> Path:
    if not sha or any(character not in "0123456789abcdef" for character in sha.lower()):
        raise ValueError("A hexadecimal commit SHA is required")
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"axiomweave-release-review-{sha}.zip"
    if output.exists():
        raise ValueError("Release bundle output already exists")
    summary = {
        "commit_sha": sha,
        "created_at": datetime.now(UTC).isoformat(),
        "phase5_media_bundle_reference": f"phase5-media-review-{sha}",
        "no_raw_source_or_model_outputs_included": True,
    }
    summary.update(_junit_summary(junit_paths[0]))
    if len(junit_paths) > 1:
        summary["postgres_junit"] = _junit_summary(junit_paths[1])
    included = [
        (BACKEND / "evals/release/model_profiles.json", "model_profiles.json"),
        (BACKEND / "evals/release/heldout_cases.json", "heldout_fixture_manifest.json"),
        (
            BACKEND / "evals/release/human_review_packet.template.json",
            "human_review_packet.template.json",
        ),
        (REPO / "docs/judge/final-acceptance-worksheet.md", "final-acceptance-worksheet.md"),
        (REPO / "docs/judge/claim-register.md", "claim-register.md"),
        (REPO / "docs/judge/model-evaluation.md", "model-evaluation.md"),
    ]
    output.write_bytes(b"")
    try:
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            archive.writestr("ci-summary.json", json.dumps(summary, indent=2, sort_keys=True))
            for source, name in included:
                archive.write(source, name)
            for index, junit in enumerate(junit_paths):
                archive.writestr(
                    "backend-junit.xml" if index == 0 else "postgres-junit.xml",
                    junit.read_bytes(),
                )
            fixture_hash = _sha256(BACKEND / "evals/release/heldout_cases.json")
            archive.writestr(
                "fixture-checksum.txt", f"SHA-256 {fixture_hash}  heldout_cases.json\n"
            )
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--backend-junit", type=Path, required=True)
    parser.add_argument("--postgres-junit", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(
        create_bundle(
            args.sha,
            [args.backend_junit, args.postgres_junit],
            args.output_dir,
        )
    )


if __name__ == "__main__":
    main()
