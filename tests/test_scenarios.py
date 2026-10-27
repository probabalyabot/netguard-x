"""Every example scenario that states an expected verdict gets it (netguardx/examples/changes/<network>/)."""
import json
from pathlib import Path

import pytest

from netguardx import AnalysisOptions, Change, IncrementalVerifier, Network, analyze

EX = Path(__file__).parent.parent / "netguardx" / "examples"
SCENARIOS = sorted(p for p in (EX / "changes").glob("*/*.json"))


def load(path: Path) -> tuple[Network, dict]:
    net = Network.model_validate(json.loads((EX / f"{path.parent.name}.json").read_text(encoding="utf-8")))
    return net, json.loads(path.read_text(encoding="utf-8"))


def changes(d: dict) -> list[Change]:
    return [Change.model_validate(c) for c in d["changes"]]


def ids(p: Path) -> str:
    return f"{p.parent.name}/{p.stem}"


def test_the_enterprise_network_has_scenarios_of_every_kind():
    names = [p.stem for p in SCENARIOS if p.parent.name == "enterprise"]
    for kind in ("pass-", "review-", "fail-"):
        assert any(n.startswith(kind) for n in names), kind


@pytest.mark.parametrize("path", SCENARIOS, ids=ids)
def test_scenario_gets_its_expected_verdict(path):
    net, d = load(path)
    kind = path.stem.split("-")[0]
    assert d["expected"] == {"pass": "SAFE", "review": "REVIEW", "fail": "NOT_RECOMMENDED"}[kind]
    assert analyze(net, changes(d)).verdict["decision"] == d["expected"]


@pytest.mark.parametrize("path", SCENARIOS, ids=ids)
def test_incremental_matches_full_on_the_scenario(path):
    net, d = load(path)
    opts = AnalysisOptions(probe_limit=200)  # a probe sample keeps this quick; the verdict test uses the default
    a, b = IncrementalVerifier()(net, changes(d), opts), analyze(net, changes(d), opts)
    assert a.model_dump(exclude={"meta"}) == b.model_dump(exclude={"meta"})


def test_maintenance_window_blames_only_the_bad_change():
    net, d = load(EX / "changes" / "enterprise" / "fail-09-maintenance-window.json")
    rb = analyze(net, changes(d)).rollback
    assert [r["index"] for r in rb["revert"]] == [len(d["changes"]) - 1]
    assert rb["if_reverted"]["decision"] == "SAFE"
