import type { Change, InterpretResponse } from "../api/types";

/** The changes a draft describes, in the order the sentences were written; requirements become
 *  ADD_POLICY. Mirrors netguardx/pipeline.py `drafted`. Older APIs without `matched`: changes, then
 *  requirements. */
export function draftedChanges(r: InterpretResponse): Change[] {
  const policy = (i: number): Change => ({ operation: "ADD_POLICY", policy: r.policies[i] });
  if (r.matched) return r.matched.map((m) => (m.kind === "change" ? r.changes[m.index] : policy(m.index)));
  return [...r.changes, ...r.policies.map((_, i) => policy(i))];
}

/** The misspelt word and the device to use instead, from a refusal like
 *  "unknown device FWW (did you mean FW?)". */
export function typoFix(u: { reason: string | null; suggestion?: string }): { word: string; suggestion: string } | null {
  const m = /unknown device (\S+)/.exec(u.reason ?? "");
  return m && u.suggestion ? { word: m[1], suggestion: u.suggestion } : null;
}

/** Replace a whole word (not part of a longer name: FW in FWW, R1 in R11 or USER0-1 stay). */
export function replaceWord(text: string, word: string, replacement: string): string {
  const esc = word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return text.replace(new RegExp(`(?<![\\w-])${esc}(?![\\w-])`, "g"), replacement);
}

/** Append a new draft to the change set, replacing the previous draft's changes when they are still
 *  the last ones in the set (so drafting again, or applying a "did you mean" fix, does not add the
 *  same changes twice). `previous` is what the last draft appended; `null` when there is none. */
export function withDraft(current: Change[], previous: Change[] | null, drafted: Change[]): Change[] {
  const tail = previous ? current.slice(current.length - previous.length) : [];
  const sameTail = previous !== null && previous.length > 0 && tail.length === previous.length && tail.every((c, i) => c === previous[i]);
  return [...(sameTail ? current.slice(0, current.length - previous!.length) : current), ...drafted];
}
