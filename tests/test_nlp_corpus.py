"""The developer phrase corpus (tests/nlp_corpus.json) is a spec: every entry must pass.

It measures how much of the grammar is covered, not how well the parser understands people; that is
what a held-out set written by someone who has not read the grammar is for (scored with
``python -m netguardx.nlp.score``, not asserted here).
"""
import json
from pathlib import Path

import pytest

from netguardx.nlp import interpret
from netguardx.nlp.score import check, main, score

CORPUS = json.loads((Path(__file__).parent / "nlp_corpus.json").read_text(encoding="utf-8"))
HERE = Path(__file__).parent
ENTERPRISE = json.loads((HERE / "nlp_corpus_enterprise.json").read_text(encoding="utf-8"))
ENTERPRISE_NET = HERE.parent / "netguardx" / "examples" / "enterprise.json"


@pytest.mark.parametrize("entry", CORPUS, ids=[e["text"][:45] for e in CORPUS])
def test_corpus_entry(net, entry):
    ok, got = check(entry, net)
    assert ok, f"expected {entry}, got {got}"


def test_corpus_covers_every_demo_script():
    scripts = {p.stem for p in (Path(__file__).parent.parent / "test-scripts").glob("*.json")}
    covered = {e["note"].split("/")[1].split(",")[0] for e in CORPUS if e.get("note", "").startswith("test-scripts/")}
    assert covered == {s.split("-")[0] + "-" + s.split("-")[1] for s in scripts}


def test_score_counts_exact_and_understood(net):
    entries = [
        {"text": "remove the default route on R1",
         "changes": [{"operation": "DELETE_ROUTE", "router": "R1", "destination": "0.0.0.0/0"}]},
        {"text": "remove the default route on R1",  # understood, but not what this entry expects
         "changes": [{"operation": "DELETE_ROUTE", "router": "R2", "destination": "0.0.0.0/0"}]},
        {"text": "make it faster", "changes": [{"operation": "ADD_LINK", "node_a": "R1", "node_b": "R3"}]},
        {"text": "make it faster", "unparsed": True},
    ]
    r = score(entries, net)
    assert (r["exact"], r["entries"], r["understood"], r["requests"]) == (2, 4, 2, 3)
    assert [m["text"] for m in r["misses"]] == ["remove the default route on R1", "make it faster"]


def test_score_command_line(tmp_path, capsys):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(CORPUS[:3]), encoding="utf-8")
    assert main([str(good)]) == 0 and "exact:      3/3" in capsys.readouterr().out
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"text": "make it faster", "changes": [{"operation": "DELETE_POLICY", "policy_id": "P1"}]}]))
    assert main([str(bad)]) == 1 and "MISS" in capsys.readouterr().out


def test_an_address_after_to_is_still_a_destination(net):
    """The router/next-hop address rule must not swallow a destination written as an address."""
    r = interpret("add a route on R3 to 10.0.5.10 via R1", net)
    assert r["changes"] == [{"operation": "ADD_ROUTE", "router": "R3", "destination": "10.0.5.10/32", "next_hop": "R1"}]


@pytest.fixture(scope="module")
def enterprise():
    from netguardx import Network
    return Network.model_validate(json.loads(ENTERPRISE_NET.read_text(encoding="utf-8")))


@pytest.mark.parametrize("entry", ENTERPRISE, ids=[e["text"][:45] for e in ENTERPRISE])
def test_enterprise_corpus_entry(enterprise, entry):
    ok, got = check(entry, enterprise)
    assert ok, f"expected {entry}, got {got}"


def test_enterprise_corpus_covers_every_enterprise_scenario():
    folder = HERE.parent / "netguardx" / "examples" / "changes" / "enterprise"
    scenarios = {"-".join(p.stem.split("-")[:2]) for p in folder.glob("*.json")}
    covered = {e["note"].split("/")[1].split(",")[0] for e in ENTERPRISE if e.get("note", "").startswith("enterprise/")}
    assert covered == scenarios
