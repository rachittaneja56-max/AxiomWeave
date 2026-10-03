import json
from pathlib import Path

import pytest

from scripts.release_harness import prepare_run


def test_release_harness_prepares_blinded_denominated_packet_without_overwrite(
    tmp_path: Path,
) -> None:
    first = prepare_run(tmp_path, "action_planning", "A")
    manifest = json.loads((first / "run_manifest.json").read_text(encoding="utf-8"))
    per_case = json.loads((first / "per_case_results.json").read_text(encoding="utf-8"))
    aggregate = json.loads((first / "aggregate_metrics.json").read_text(encoding="utf-8"))
    human = json.loads((first / "human_review_packet.json").read_text(encoding="utf-8"))

    assert manifest["candidate_label"] == "A"
    assert manifest["candidate_model"] is None
    assert manifest["final_promotion"] == "PENDING FINAL EVALUATION"
    assert manifest["case_count"] == len(per_case) == aggregate["denominator"]
    assert all(result["status"] == "not_run" for result in per_case)
    assert human["blind_review"] is True
    assert all(review["preference"] is None for review in human["case_reviews"])
    assert prepare_run(tmp_path, "action_planning", "A") != first
    with pytest.raises(ValueError, match="Unknown evaluation task"):
        prepare_run(tmp_path, "unknown", "A")
