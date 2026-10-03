import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts.create_phase6_bundle import create_bundle


def test_phase6_bundle_contains_safe_fixture_and_security_test_summary(tmp_path: Path) -> None:
    junit = tmp_path / "junit.xml"
    junit.write_text(
        (
            "<testsuites><testsuite>"
            '<testcase classname="tests.test_phase6_security" name="test_csrf"/>'
            '<testcase classname="tests.test_unrelated" name="test_other"/>'
            "</testsuite></testsuites>"
        ),
        encoding="utf-8",
    )
    output = create_bundle("a" * 40, [junit], tmp_path / "bundle")

    with ZipFile(output) as archive:
        summary = json.loads(archive.read("ci-summary.json"))
        assert summary["phase5_media_bundle_reference"] == f"phase5-media-review-{'a' * 40}"
        assert summary["phase6_counts"] == {
            "total": 1,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
            "passed": 1,
        }
        assert "heldout_fixture_manifest.json" in archive.namelist()
        assert "final-acceptance-worksheet.md" in archive.namelist()
        assert summary["no_raw_source_or_model_outputs_included"] is True
    with pytest.raises(ValueError, match="already exists"):
        create_bundle("a" * 40, [junit], tmp_path / "bundle")
