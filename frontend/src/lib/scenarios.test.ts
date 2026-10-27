import { describe, expect, it } from "vitest";
import type { ExamplesResponse } from "../api/types";
import { draftExamples, exampleNetworkId, scenariosFor } from "./scenarios";

const net = { name: "n", nodes: [] } as unknown as ExamplesResponse["networks"][number]["network"];
const ex: ExamplesResponse = {
  networks: [{ id: "basic", title: "Three-tier", network: net }, { id: "enterprise", title: "Enterprise", network: net }],
  changes: [
    { id: "a", network: "basic", changes: [] },
    { id: "enterprise/b", network: "enterprise", changes: [] },
    { id: "enterprise/c", network: "enterprise", changes: [] },
  ],
};

describe("scenarios", () => {
  it("finds the example network by title", () => {
    expect(exampleNetworkId(ex, "Enterprise")).toBe("enterprise");
    expect(exampleNetworkId(ex, "my-upload.json")).toBeUndefined();
    expect(exampleNetworkId(null, "Enterprise")).toBeUndefined();
  });
  it("lists only the open network's scenarios", () => {
    expect(scenariosFor(ex, "enterprise").map((s) => s.id)).toEqual(["enterprise/b", "enterprise/c"]);
    expect(scenariosFor(ex, "basic").map((s) => s.id)).toEqual(["a"]);
    expect(scenariosFor(ex, undefined)).toEqual([]);
  });
});

describe("draftExamples", () => {
  it("uses the open network's device names, and has none for an uploaded network", () => {
    expect(draftExamples("basic")[0]).toContain("on FW");
    expect(draftExamples("enterprise")[0]).toContain("on DC-FW");
    expect(draftExamples(undefined)).toEqual([]);
    expect(draftExamples("my-upload")).toEqual([]);
  });
});
