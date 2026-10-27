import type { ExampleChange, ExamplesResponse } from "../api/types";

/** Id of the example network whose title is `label`, or undefined for a network loaded from a file. */
export function exampleNetworkId(examples: ExamplesResponse | null, label: string): string | undefined {
  return examples?.networks.find((n) => n.title === label)?.id;
}

/** The example scenarios written for one example network. */
export function scenariosFor(examples: ExamplesResponse | null, networkId: string | undefined): ExampleChange[] {
  if (!examples || !networkId) return [];
  return examples.changes.filter((c) => c.network === networkId);
}

/** Example sentences for the Drafter, in the device names of each built-in network. */
const DRAFT_EXAMPLES: Record<string, string[]> = {
  basic: [
    "block ssh from USER to DB on FW",
    "send DB traffic on R1 via R3",
    "R1(config)#\nip route 10.0.7.0 255.255.255.0 R3",
    "USER must never reach DB",
  ],
  enterprise: [
    "block ssh from GUEST1 to JUMP on DC-FW",
    "send DB1 traffic on DC-R via SAN-R",
    "DC-R(config)#\nip route 10.20.7.0 255.255.255.0 SAN-R",
    "DEV1 must never reach DB1",
  ],
};

/** Drafter examples for an example network; none for a network loaded from a file. */
export function draftExamples(networkId: string | undefined): string[] {
  return (networkId && DRAFT_EXAMPLES[networkId]) || [];
}
