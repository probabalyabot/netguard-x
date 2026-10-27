"""Typed commands through the gatekeeper (netguardx/pipeline.py) and the draft / session commands."""
import io
import json
from pathlib import Path

import pytest

from netguardx.cli import main
from netguardx.nlp import interpret
from netguardx.pipeline import NOT_UNDERSTOOD, Session, drafted

ROOT = Path(__file__).parent.parent
BASIC = str(ROOT / "netguardx" / "examples" / "basic.json")
CORPUS = json.loads((Path(__file__).parent / "nlp_corpus.json").read_text(encoding="utf-8"))
DEMO = [e for e in CORPUS if e.get("note", "").startswith("test-scripts/") and "Cisco" not in e["note"]]


def run(net, *lines, operator=False):
    s = Session(net, operator=operator)
    entries = [s.feed(line, i) for i, line in enumerate(lines, 1)]
    return s, [e for e in entries if e]


# ------------------------------------------------------------------------------------------ drafted
def test_drafted_keeps_sentence_order_and_turns_requirements_into_add_policy(net):
    r = interpret("USER must never reach APP. remove the default route on R1", net)
    assert [c.operation for c in drafted(r)] == ["ADD_POLICY", "DELETE_ROUTE"]


# ------------------------------------------------------------------------------------------ session
@pytest.mark.parametrize("entry", DEMO, ids=[e["note"].split("/")[1] for e in DEMO])
def test_each_demo_sentence_gets_its_scripts_verdict(net, entry):
    expected = {"pass": "EXECUTED", "review": "HELD", "fail": "REJECTED"}[entry["note"].split("/")[1].split("-")[0]]
    _, [e] = run(net, entry["text"])
    assert e["outcome"] == expected, e


def test_lines_see_what_earlier_lines_executed_and_headers_carry_over(net):
    s, entries = run(net, "R1(config)#", "ip route 10.0.7.0 255.255.255.0 R3", "no ip route 10.0.7.0 255.255.255.0 R3")
    assert [e["outcome"] for e in entries] == ["EXECUTED", "EXECUTED"]
    assert entries[1]["understood_as"] == ["Delete route on R1: 10.0.7.0/24 via R3"]
    assert s.summary()["checkpoints"] == 2


def test_a_typo_under_a_header_is_refused_not_applied_to_the_header_device(net):
    s, entries = run(net, "R1(config)#", "block ssh from USER to DB on FWW", "remove the default route on R11")
    assert [e["outcome"] for e in entries] == [NOT_UNDERSTOOD, NOT_UNDERSTOOD]
    assert "did you mean FW?" in entries[0]["reason"] and "did you mean R1?" in entries[1]["reason"]
    assert s.gk.version == 0


def test_half_understood_lines_are_not_executed(net):
    s, [e] = run(net, "cable R2 to R3; make it faster")
    assert e["outcome"] == NOT_UNDERSTOOD and e["understood_as"] == ["Add link R2 - R3"] and s.gk.version == 0


def test_the_agent_cannot_add_requirements_but_an_operator_can(net):
    _, [agent] = run(net, "the internet cannot reach DB")
    assert agent["outcome"] == "REJECTED" and "may not change policies" in agent["reason"]
    s, [person] = run(net, "the internet cannot reach DB", operator=True)
    assert person["outcome"] == "EXECUTED" and len(s.gk.network.policies) == 7


def test_held_commands_stay_held(net):
    s, [e] = run(net, "cable FW to BACKUP")
    assert e["outcome"] == "HELD" and s.summary()["held"] == [e["pending_id"]] and s.gk.version == 0


def test_blank_comment_and_session_lines_are_skipped(net):
    _, entries = run(net, "", "# note", "conf t", "end", "!")
    assert entries == []


# -------------------------------------------------------------------------------------- draft CLI
def test_draft_prints_the_drafts(capsys):
    assert main(["draft", BASIC, "block ssh from USER to DB on FW"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["changes"][0]["operation"] == "ADD_ACL_RULE" and out["matched"]


def test_draft_exits_2_when_something_is_not_understood(capsys):
    assert main(["draft", BASIC, "block ssh from USER to DB on FWW"]) == 2
    assert json.loads(capsys.readouterr().out)["unparsed"][0]["suggestion"] == "FW"


def test_draft_analyze_gives_the_verdict(tmp_path, capsys):
    assert main(["draft", BASIC, "send DB traffic on R1 via R3", "--analyze"]) == 1  # the firewall bypass
    out = capsys.readouterr()
    assert "Do not deploy" in out.out and "understood" in out.err
    f = tmp_path / "change.txt"
    f.write_text("R1(config)#\nip route 10.0.7.0 255.255.255.0 R3\n", encoding="utf-8")
    assert main(["draft", BASIC, "--file", str(f), "--analyze"]) == 0
    assert main(["draft", BASIC, "make it faster", "--analyze"]) == 2


def test_draft_needs_text_or_file_not_both(capsys):
    assert main(["draft", BASIC]) == 2
    assert "not both" in capsys.readouterr().err


# ------------------------------------------------------------------------------------ session CLI
def test_session_command_prints_each_line_and_writes_a_log(tmp_path, capsys):
    cmds = tmp_path / "cmds.txt"
    cmds.write_text("set the metric of R1's default route to 50\nsend DB traffic on R1 via R3\nmake it faster\n",
                    encoding="utf-8")
    log = tmp_path / "log.json"
    assert main(["session", BASIC, str(cmds), "--out", str(log)]) == 0
    out = capsys.readouterr().out
    assert "EXECUTED" in out and "REJECTED" in out and "NOT UNDERSTOOD" in out
    assert "3 commands: 1 executed, 0 held, 1 rejected, 0 invalid, 1 not understood" in out
    saved = json.loads(log.read_text(encoding="utf-8"))
    assert [e["outcome"] for e in saved["entries"]] == ["EXECUTED", "REJECTED", NOT_UNDERSTOOD]


def test_session_reads_typed_commands_from_stdin(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("cable R2 to R3\nthe internet cannot reach DB\n"))
    assert main(["session", BASIC, "-", "--operator"]) == 0
    out = capsys.readouterr().out
    assert "as an operator" in out and "2 executed" in out


@pytest.mark.parametrize("name, network, expected", [
    ("session.txt", "basic", {"EXECUTED": 5, "HELD": 1, "REJECTED": 7, "NOT UNDERSTOOD": 1}),
    ("enterprise-session.txt", "enterprise", {"EXECUTED": 6, "HELD": 2, "REJECTED": 10, "NOT UNDERSTOOD": 2}),
])
def test_demo_sessions_end_as_their_readme_says(name, network, expected):
    from netguardx import Network

    net = Network.model_validate(json.loads((ROOT / "netguardx" / "examples" / f"{network}.json").read_text(encoding="utf-8")))
    s = Session(net)
    for i, line in enumerate((ROOT / "test-scripts" / name).read_text(encoding="utf-8").splitlines(), 1):
        s.feed(line, i)
    got = s.summary()
    assert {k: got[k] for k in expected} == expected
