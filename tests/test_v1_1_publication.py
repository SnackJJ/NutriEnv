"""Publication tables must retain the exact report counts and protocol identity."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("render_v1_1", ROOT / "scripts" / "render_v1_1.py")
assert spec is not None and spec.loader is not None
publication = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publication)


def test_published_reports_and_readme_table():
    runs = publication.load_reports()
    assert [r["data"]["passed_tasks"] for r in runs] == [60, 56, 37]
    assert publication.render_table(runs) in (ROOT / "README.md").read_text()


@pytest.mark.parametrize("change", ["missing", "scorer", "counts", "duplicate", "void", "family"])
def test_invalid_report_is_not_silently_published(tmp_path, change):
    runs = publication.load_reports()
    directory = tmp_path / "reports"
    directory.mkdir()
    for run in runs:
        data = copy.deepcopy(run["data"])
        if run is runs[0]:
            if change == "missing":
                continue
            if change == "scorer":
                data["scorer_version"] = "old-ruler"
            elif change == "counts":
                data["passed_tasks"] -= 1
            elif change == "duplicate":
                data["tasks"][1]["task_id"] = data["tasks"][0]["task_id"]
            elif change == "void":
                data["tasks"][0]["is_void"] = True
            elif change == "family":
                data["family_breakdown"]["log"]["passed"] += 1
        (directory / run["filename"]).write_text(json.dumps(data))
    with pytest.raises(ValueError):
        publication.load_reports(tmp_path)


def test_provenance_binds_replay_verified_artifacts():
    manifest = json.loads((ROOT / "reports" / "v1.1-provenance.json").read_text())
    assert manifest["identity"] == publication.IDENTITY
    assert manifest["split_sha256"] == publication.sha256(ROOT / manifest["identity"]["split"])
    assert manifest["catalog_sha256"] == publication.sha256(ROOT / manifest["catalog"])
    assert manifest["reports"] == {
        filename: publication.sha256(ROOT / "reports" / filename)
        for _, filename, _ in publication.REPORTS
    }
