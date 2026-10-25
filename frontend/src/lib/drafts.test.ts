import { describe, expect, it } from "vitest";
import type { Change, InterpretResponse } from "../api/types";
import { draftedChanges, replaceWord, typoFix, withDraft } from "./drafts";

const base: InterpretResponse = { parser: "rule-based", kind: "mixed", changes: [], policies: [], unparsed: [], needs_review: true, note: "" };
const route: Change = { operation: "DELETE_ROUTE", router: "R1", destination: "0.0.0.0/0" };
const link: Change = { operation: "ADD_LINK", node_a: "R2", node_b: "R3" };
const policy = { source: "USER", destination: "APP", action: "DENY" as const };

describe("draftedChanges", () => {
  it("follows sentence order and turns requirements into ADD_POLICY", () => {
    const r = { ...base, changes: [route], policies: [policy],
      matched: [{ text: "a", kind: "policy" as const, index: 0, understood_as: "" }, { text: "b", kind: "change" as const, index: 0, understood_as: "" }] };
    expect(draftedChanges(r)).toEqual([{ operation: "ADD_POLICY", policy }, route]);
  });
  it("falls back to changes then requirements without matched", () => {
    expect(draftedChanges({ ...base, changes: [route], policies: [policy] })).toEqual([route, { operation: "ADD_POLICY", policy }]);
  });
});

describe("typoFix", () => {
  it("reads the word and the suggestion", () => {
    expect(typoFix({ reason: "unknown device FWW (did you mean FW?)", suggestion: "FW" })).toEqual({ word: "FWW", suggestion: "FW" });
    expect(typoFix({ reason: "unknown device SRV9", suggestion: undefined })).toBeNull();
    expect(typoFix({ reason: "not a reachability requirement" })).toBeNull();
  });
});

describe("replaceWord", () => {
  it("replaces whole words only", () => {
    expect(replaceWord("block ssh on FWW; FWW2 stays", "FWW", "FW")).toBe("block ssh on FW; FWW2 stays");
    expect(replaceWord("R11 and R1 and USER0-1", "R1", "R2")).toBe("R11 and R2 and USER0-1");
  });
});

describe("withDraft", () => {
  it("appends a first draft", () => {
    expect(withDraft([link], null, [route])).toEqual([link, route]);
  });
  it("replaces the previous draft when it is still at the end", () => {
    const first = [route];
    const set = withDraft([link], null, first);
    expect(withDraft(set, first, [link])).toEqual([link, link]);
  });
  it("keeps the previous draft once the set was edited after it", () => {
    const first = [route];
    const edited = [...withDraft([link], null, first), link];
    expect(withDraft(edited, first, [route])).toEqual([link, route, link, route]);
  });
});
