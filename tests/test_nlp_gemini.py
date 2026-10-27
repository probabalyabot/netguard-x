"""The optional Gemini rewrite step. No test calls the real API."""
import json

import httpx
import pytest

from netguardx.nlp import gemini


@pytest.fixture()
def on(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("NETGUARDX_GEMINI", "1")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)


def _reply(lines, status=200):
    body = {"candidates": [{"content": {"parts": [{"text": json.dumps({"lines": lines})}]}}]}
    return httpx.Response(status, json=body, request=httpx.Request("POST", "https://x"))


def test_off_by_default_in_tests(net):
    assert not gemini.enabled()


def test_understood_text_never_calls_gemini(net, on, monkeypatch):
    monkeypatch.setattr(gemini, "rewrite", lambda *a: pytest.fail("called Gemini"))
    r = gemini.interpret("block ssh from USER to DB on FW", net)
    assert r["changes"] and r["rewritten"] is None


def test_rewrite_used_when_it_parses_better(net, on, monkeypatch):
    monkeypatch.setattr(gemini, "rewrite", lambda *a: "block ssh from USER to DB on FW")
    r = gemini.interpret("stop the user box from sshing into the database", net)
    assert r["rewritten"] == "block ssh from USER to DB on FW"
    assert r["changes"][0]["operation"] == "ADD_ACL_RULE" and not r["unparsed"]


def test_typed_result_kept_when_rewrite_is_no_better(net, on, monkeypatch):
    monkeypatch.setattr(gemini, "rewrite", lambda *a: "make it much faster")
    r = gemini.interpret("make it faster", net)
    assert r["rewritten"] is None and r["unparsed"][0]["text"] == "make it faster"


def test_failure_falls_back_to_the_parser(net, on, monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(httpx, "post", boom)
    r = gemini.interpret("make it faster", net)
    assert r["rewritten"] is None and r["unparsed"]


def test_rewrite_reads_json_and_skips_a_missing_model(net, on, monkeypatch):
    calls = []

    def post(url, **k):
        calls.append(url)
        assert k["headers"]["x-goog-api-key"] == "test-key"
        return _reply([], 404) if len(calls) == 1 else _reply(["connect FW and BACKUP", " "])
    monkeypatch.setattr(httpx, "post", post)
    assert gemini.rewrite("plug the firewall into backup", net) == "connect FW and BACKUP"
    assert gemini.MODELS[0] in calls[0] and gemini.MODELS[1] in calls[1]


def test_network_summary_names_devices_and_numbers_rules(net):
    s = gemini.describe_network(net)
    assert "FW | firewall" in s and "on FW: rule 1: ALLOW APP -> DB TCP/5432" in s
