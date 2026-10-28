"""The optional language-model rewrite step. No test calls Ollama or Gemini."""
import json

import httpx
import pytest

from netguardx.nlp import llm


@pytest.fixture()
def on(monkeypatch):
    monkeypatch.setenv("NETGUARDX_LLM", "1")
    monkeypatch.setenv("LLM_ORDER", "ollama,gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setattr(llm, "_cache", {})


def _fake(answers):
    """Providers that answer from ``answers`` ({provider: text or None}) and record their calls."""
    calls = []

    def make(name):
        def ask(request):
            calls.append(name)
            a = answers.get(name)
            return a.split("\n") if a else None
        return ask
    return {n: make(n) for n in llm.PROVIDERS}, calls


def _reply(lines, status=200):
    body = {"candidates": [{"content": {"parts": [{"text": json.dumps({"lines": lines})}]}}]}
    return httpx.Response(status, json=body, request=httpx.Request("POST", "https://x"))


def test_off_in_tests():
    assert not llm.enabled()


def test_understood_text_never_calls_a_model(net, on, monkeypatch):
    fake, calls = _fake({"ollama": "connect FW and BACKUP"})
    monkeypatch.setattr(llm, "PROVIDERS", fake)
    r = llm.interpret("block ssh from USER to DB on FW", net)
    assert r["changes"] and r["rewritten"] is None and calls == []


def test_ollama_first_and_gemini_not_needed(net, on, monkeypatch):
    fake, calls = _fake({"ollama": "block ssh from USER to DB on FW", "gemini": "x"})
    monkeypatch.setattr(llm, "PROVIDERS", fake)
    r = llm.interpret("stop the user box from sshing into the database", net)
    assert r["rewritten"] == "block ssh from USER to DB on FW" and r["rewritten_by"] == "ollama"
    assert r["changes"][0]["operation"] == "ADD_ACL_RULE" and not r["unparsed"] and calls == ["ollama"]


def test_gemini_used_when_ollama_is_down_or_worse(net, on, monkeypatch):
    for ollama in (None, "make it much faster"):
        monkeypatch.setattr(llm, "_cache", {})
        fake, calls = _fake({"ollama": ollama, "gemini": "connect FW and BACKUP"})
        monkeypatch.setattr(llm, "PROVIDERS", fake)
        r = llm.interpret("plug the firewall into backup", net)
        assert r["rewritten_by"] == "gemini" and calls == ["ollama", "gemini"]


def test_order_setting(net, on, monkeypatch):
    monkeypatch.setenv("LLM_ORDER", "gemini")
    assert llm.providers() == ["gemini"]


def test_typed_result_kept_when_no_rewrite_is_better(net, on, monkeypatch):
    fake, _ = _fake({"ollama": "make it much faster", "gemini": None})
    monkeypatch.setattr(llm, "PROVIDERS", fake)
    r = llm.interpret("make it faster", net)
    assert r["rewritten"] is None and r["unparsed"][0]["text"] == "make it faster"


def test_rewrites_are_remembered(net, on, monkeypatch):
    fake, calls = _fake({"ollama": "connect FW and BACKUP"})
    monkeypatch.setattr(llm, "PROVIDERS", fake)
    llm.interpret("plug the firewall into backup", net)
    llm.interpret("plug the firewall into backup", net)
    assert calls == ["ollama"]


def test_ollama_not_running_is_skipped_quietly(monkeypatch):
    def refuse(*a, **k):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(httpx, "post", refuse)
    assert llm._ask_ollama("anything") is None


def test_ollama_reads_json(monkeypatch):
    def post(url, **k):
        assert url.endswith("/api/chat") and k["json"]["format"] == llm.SCHEMA
        return httpx.Response(200, json={"message": {"content": json.dumps({"lines": ["connect FW and BACKUP"]})}},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", post)
    assert llm._ask_ollama("plug the firewall into backup") == ["connect FW and BACKUP"]


def test_gemini_moves_past_busy_models(on, monkeypatch):
    calls = []

    def post(url, **k):
        calls.append(url)
        assert k["headers"]["x-goog-api-key"] == "test-key"
        return _reply([], 503) if len(calls) == 1 else _reply(["connect FW and BACKUP", " "])
    monkeypatch.setattr(httpx, "post", post)
    assert llm._ask_gemini("plug the firewall into backup") == ["connect FW and BACKUP"]
    assert llm.GEMINI_MODELS[0] in calls[0] and llm.GEMINI_MODELS[1] in calls[1]


def test_network_summary_names_devices_and_numbers_rules(net):
    s = llm.describe_network(net)
    assert "FW | firewall" in s and "on FW: rule 1: allow tcp/5432 from APP to DB" in s
    assert "P3: USER must never reach DB" in s and "->" not in s  # the parser's words, no arrows


def test_warm_up_loads_the_model_with_the_settings_drafts_use(on, monkeypatch):
    """A different num_ctx makes Ollama reload the model, which made the first draft take 8 s."""
    sent = []
    monkeypatch.setattr(httpx, "post", lambda url, **k: sent.append((url, k["json"])))
    llm.warm_up()
    [(url, body)] = sent
    assert url.endswith("/api/generate") and body["options"] == llm.OLLAMA_OPTIONS


def test_ollama_connect_timeout_is_short():
    assert llm.OLLAMA_TIMEOUT.connect <= 1


@pytest.mark.parametrize("text", [
    "ip route 10.0.7.0 255.255.255.0 R3",              # which router: only the user knows
    "R1(config)# ip route 10.0.7.0 255.0.255.0 R3",   # invalid netmask: never repaired
    "delete rule 0 on FW", "delete rule 7 on FW",       # rules that do not exist
    "send USER traffic on R1 via R3",                   # no specific route: the user gives the prefix
])
def test_a_choice_only_the_user_can_make_is_never_sent_to_a_model(net, on, monkeypatch, text):
    fake, calls = _fake({"ollama": "add a route on R2 to 10.0.7.0/24 via R3"})
    monkeypatch.setattr(llm, "PROVIDERS", fake)
    r = llm.interpret(text, net)
    assert calls == [] and r["rewritten"] is None and r["unparsed"]


def test_a_rewrite_that_drops_a_named_device_is_not_used(net, on, monkeypatch):
    """Seen with llama3.1: "send USER traffic ..." came back as a route to a different device."""
    fake, _ = _fake({"ollama": "connect FW and BACKUP"})
    monkeypatch.setattr(llm, "PROVIDERS", fake)
    assert llm.interpret("hook up USER with BACKUP somehow", net)["rewritten"] is None


def test_named_devices_are_exact_ids_not_ordinary_words(net):
    assert llm._named_devices("plug the user box into R3 and the db", net) == {"R3"}
    assert llm._named_devices("block USER from DB on FW", net) == {"USER", "DB", "FW"}
    assert llm._keeps_devices("blok ssh from USR to DB on FWW", "block ssh from USER to DB on FW", net)
