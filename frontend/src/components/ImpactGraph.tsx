import { Background, BackgroundVariant, Controls, Handle, MarkerType, Position, ReactFlow, ReactFlowProvider, type Edge, type Node, type NodeProps } from "@xyflow/react";
import clsx from "clsx";
import { memo, useMemo } from "react";
import type { ImpactGraph as IG, Step } from "../api/types";
import { toneVar, type Tone } from "../lib/format";

export const KIND_LABEL: Record<Step["kind"], string> = {
  change: "Change", routing: "Forwarding decision", path: "Path", enforcement: "Enforcement point", policy: "Policy", impact: "Impact",
};
const KIND_TONE: Record<Step["kind"], Tone> = { change: "net", routing: "muted", path: "net", enforcement: "warn", policy: "bad", impact: "bad" };
const ORDER: Step["kind"][] = ["change", "routing", "path", "enforcement", "policy", "impact"];

interface StepData extends Record<string, unknown> { kind: Step["kind"]; label: string; dim: boolean }
type StepNode = Node<StepData, "step">;

const StepView = memo(function StepView({ data }: NodeProps<StepNode>) {
  return (
    <div className={clsx("w-[210px] rounded-md border bg-panel px-2.5 py-2 text-xs transition-opacity", data.dim && "opacity-35")} style={{ borderColor: toneVar[KIND_TONE[data.kind]] }}>
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} /><Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
      <div className="mb-0.5 text-[11px] text-muted">{KIND_LABEL[data.kind]}</div>
      <div className="text-fg leading-snug">{data.label}</div>
    </div>
  );
});
const nodeTypes = { step: StepView };

/** The Configuration Impact Graph the backend merges from every finding's propagation chain. */
function Inner({ graph, highlight }: { graph: IG; highlight: Set<string> | null }) {
  const { nodes, edges } = useMemo(() => {
    const col: Record<string, number> = {};
    const nodes: StepNode[] = graph.nodes.map((n) => {
      const ci = ORDER.indexOf(n.kind);
      const row = (col[n.kind] = (col[n.kind] ?? -1) + 1);
      return { id: n.id, type: "step", position: { x: ci * 270, y: row * 96 }, draggable: false, data: { kind: n.kind, label: n.label, dim: !!highlight && !highlight.has(n.id) } };
    });
    const edges: Edge[] = graph.edges.map((e, i) => {
      const on = !highlight || (highlight.has(e.source) && highlight.has(e.target));
      return { id: `e${i}`, source: e.source, target: e.target, type: "smoothstep", markerEnd: { type: MarkerType.ArrowClosed, color: on ? toneVar.net : "rgb(var(--line-strong))", width: 14, height: 14 },
        style: { stroke: on ? toneVar.net : "rgb(var(--line-strong))", strokeWidth: on ? 2 : 1, opacity: on ? 1 : 0.5 } };
    });
    return { nodes, edges };
  }, [graph, highlight]);
  return (
    <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.15 }} minZoom={0.2} maxZoom={1.8}
      nodesDraggable={false} nodesConnectable={false}>
      <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="rgb(var(--line))" />
      <Controls showInteractive={false} position="top-right" />
    </ReactFlow>
  );
}

export function ImpactGraph({ graph, highlight }: { graph: IG; highlight: Set<string> | null }) {
  const key = graph.nodes.map((n) => n.id).join("|");
  return <div className="h-full w-full" role="img" aria-label="Configuration impact graph"><ReactFlowProvider key={key}><Inner graph={graph} highlight={highlight} /></ReactFlowProvider></div>;
}
