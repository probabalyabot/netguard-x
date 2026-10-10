"""Render a ChangeReport as a readable Markdown document."""
from __future__ import annotations

from .explain import fmt_path
from .impact import ChangeReport

_ICON = {"NOT_RECOMMENDED": "FAIL", "REVIEW": "REVIEW", "SAFE": "PASS"}


def render_markdown(r: ChangeReport) -> str:
    L: list[str] = []
    v, s, k = r.verdict, r.summary, r.risk
    L.append(f"# Network change verification: {r.network}")
    L.append("")
    L.append(f"**Result: {_ICON.get(v['decision'], v['decision'])}.** {v['headline']}")
    L.append("")
    L.append("## Proposed change")
    for c in r.changes:
        L.append(f"{c['index'] + 1}. {c['description']}")
    L.append("")
    L.append("## Summary")
    L.append("")
    L.append("| Measure | Value |")
    L.append("|---|---|")
    L.append(f"| Declared flows affected | {s['affected_flows']} of {s['declared_flows_checked']} |")
    L.append(f"| Flows broken | {s['broken_flows']} |")
    L.append(f"| Routing failures (loop, black hole, bad next hop) | {s['routing_failures']} |")
    L.append(f"| New security policy violations | {s['security_violations']} |")
    L.append(f"| Newly reachable device pairs | {s['new_exposures']} |")
    L.append(f"| Risk | {k.level.title()} (score {k.score:g} of 100) |")
    L.append("")
    if r.findings:
        L.append("## Findings")
        for f in r.findings:
            L.append("")
            L.append(f"### {f.id} [{f.severity}] {f.title}")
            L.append("")
            L.append(f.human)
            L.append("")
            L.append(f"- Before: {f.before_status} via {fmt_path(f.before_path)}")
            L.append(f"- After: {f.after_status} via {fmt_path(f.after_path)}")
            if f.policies:
                L.append(f"- Policies involved: {', '.join(f.policies)}")
            L.append("")
            L.append("Propagation:")
            L.append("")
            for i, st in enumerate(f.propagation, 1):
                detail = st.detail.replace("\n", "; ")
                L.append(f"{i}. **{st.label}**" + (f" - {detail}" if detail else ""))
            L.append("")
            L.append(f"Technical detail: {f.technical}")
    else:
        L.append("## Findings")
        L.append("")
        L.append("None. Every declared flow and policy behaves as before.")
    if r.config_warnings:
        L.append("")
        L.append("## Configuration warnings")
        L.append("")
        for w in r.config_warnings:
            L.append(f"- {w}")
    if r.rollback:
        L.append("")
        L.append("## Rollback recommendation")
        L.append("")
        for item in r.rollback["revert"]:
            L.append(f"- Do not apply change {item['index'] + 1} ({item['description']}).")
        rb = r.rollback["if_reverted"]
        L.append(f"- Without it the verdict is {rb['decision']} with {rb['remaining_problems']} remaining problem(s).")
        L.append(f"- {r.rollback['note']}")
    L.append("")
    L.append("---")
    L.append(f"Risk weights: {k.weights.model_dump()}. Scope: static routing, ACLs and policy checks on the "
             "supplied model; return traffic is not simulated.")
    return "\n".join(L) + "\n"
