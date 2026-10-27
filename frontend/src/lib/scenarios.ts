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
