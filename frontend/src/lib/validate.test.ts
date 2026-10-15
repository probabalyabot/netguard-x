import { describe, expect, it } from "vitest";
import { validateChanges, validateNetwork } from "./validate";

const net = { nodes: [{ id: "R1", type: "router" as const }, { id: "R2", type: "router" as const }] };

describe("validateChanges", () => {
  it("accepts a well-formed change", () => {
    const r = validateChanges([{ operation: "ADD_LINK", node_a: "R1", node_b: "R2" }], net);
    expect(r.errors).toEqual([]);
    expect(r.changes).toHaveLength(1);
  });
  it("accepts the {changes: [...]} wrapper used by the example files", () => {
    expect(validateChanges({ changes: [{ operation: "DELETE_LINK", node_a: "R1", node_b: "R2" }] }, net).errors).toEqual([]);
  });
  it("reports missing fields and unknown devices", () => {
    const r = validateChanges([{ operation: "ADD_ROUTE", router: "R9", destination: "10.0.0.0/24" }], net);
    expect(r.errors.join(" ")).toContain("missing next_hop");
    expect(r.errors.join(" ")).toContain('"R9" is not a device');
  });
  it("rejects unknown operations and non-lists", () => {
    expect(validateChanges([{ operation: "REBOOT" }], net).errors[0]).toContain("unknown operation");
    expect(validateChanges("x", net).errors).toHaveLength(1);
  });
  it("requires rule or node+rule_index for DELETE_ACL_RULE", () => {
    expect(validateChanges([{ operation: "DELETE_ACL_RULE" }], net).errors[0]).toContain("DELETE_ACL_RULE");
  });
});

describe("validateNetwork", () => {
  it("needs nodes", () => {
    expect(validateNetwork({})).not.toBeNull();
    expect(validateNetwork(net)).toBeNull();
  });
});
