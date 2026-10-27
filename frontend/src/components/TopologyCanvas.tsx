import {
  BaseEdge, Background, BackgroundVariant, ControlButton, Controls, Handle, MarkerType, MiniMap, Position, ReactFlow, ReactFlowProvider,
  useReactFlow, type Edge, type EdgeProps, type Node, type NodeProps,
} from "@xyflow/react";
import clsx from "clsx";
import { BrickWall, Globe, Maximize2, Minimize2, Monitor, Router, Server, type LucideIcon } from "lucide-react";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import type { NodeType, Topology } from "../api/types";
import { toneVar, type Tone } from "../lib/format";

export interface PathOverlay { id: string; nodes: string[]; tone: Tone }
export type CanvasView = "plain" | "before" | "after";

interface Props {
  topology: Topology;
  /** plain: current network. before/after: how links that the change removes or adds are drawn. */
  view?: CanvasView;
  overlays?: PathOverlay[];
  /** Rings on specific devices, e.g. where a flow stops. */
  marks?: Record<string, Tone>;
  selected?: string | null;
  onSelect?: (id: string | null) => void;
  minimap?: boolean;
  /** Hide the legend, e.g. in small previews. */
  hideLegend?: boolean;
  className?: string;
  ariaLabel: string;
}

const R = 22; // node radius in px
const ICONS: Record<NodeType, LucideIcon> = { router: Router, firewall: BrickWall, host: Monitor, server: Server, internet: Globe };
export const TYPE_LABEL: Record<NodeType, string> = { router: "Router", firewall: "Firewall", host: "Host", server: "Server", internet: "Internet" };

interface DeviceData extends Record<string, unknown> { id: string; label: string; ip: string | null; type: NodeType; mark?: Tone; selected: boolean; dim: boolean; onPath: boolean }
type DeviceNode = Node<DeviceData, "device">;

const DeviceNodeView = memo(function DeviceNodeView({ data }: NodeProps<DeviceNode>) {
  const Icon = ICONS[data.type];
  const ring = data.mark ? toneVar[data.mark] : data.onPath ? toneVar.net : undefined;
  const infra = data.type === "router" || data.type === "firewall";
  return (
    <div className={clsx("relative transition-opacity", data.dim && "opacity-50")} style={{ width: 2 * R, height: 2 * R }}>
      <div
        className={clsx("grid place-items-center w-full h-full bg-panel border-[1.5px]",
          data.type === "server" || data.type === "firewall" ? "rounded-md" : "rounded-full",
          data.type === "internet" && "border-dashed",
          data.selected && "outline outline-2 outline-offset-[3px] outline-net")}
        style={{ borderColor: ring ?? "rgb(var(--line-strong))", boxShadow: data.mark ? `0 0 0 3px color-mix(in srgb, ${toneVar[data.mark]} 22%, transparent)` : undefined }}
      >
        <Icon size={19} strokeWidth={1.75} className={infra ? "text-net" : "text-fg"} aria-hidden />
      </div>
      <div className="absolute left-1/2 top-full mt-1.5 -translate-x-1/2 text-center whitespace-nowrap">
        <div className="text-xs font-medium text-fg leading-tight">{data.label}</div>
        {data.ip && <div className="mono !text-[10.5px] text-faint leading-tight">{data.ip}</div>}
      </div>
      {/* React Flow needs handles to anchor edges; edges here are drawn from explicit coordinates. */}
      <Handle type="target" position={Position.Top} style={{ opacity: 0, pointerEvents: "none", top: "50%", left: "50%" }} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0, pointerEvents: "none", top: "50%", left: "50%" }} />
    </div>
  );
});

type WireStyle = "link" | "added" | "removed" | "ghost" | "path";
interface WireData extends Record<string, unknown> { x1: number; y1: number; x2: number; y2: number; style: WireStyle; tone?: Tone; offset: number; dim: boolean }
type WireEdge = Edge<WireData, "wire">;

const WireView = memo(function WireView({ data, markerEnd }: EdgeProps<WireEdge>) {
  if (!data) return null;
  const { x1, y1, x2, y2, style, tone, offset, dim } = data;
  const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1;
  const ux = dx / len, uy = dy / len, px = -uy, py = ux;
  const gap = style === "path" ? R + 4 : R;
  const sx = x1 + ux * gap + px * offset, sy = y1 + uy * gap + py * offset;
  const ex = x2 - ux * gap + px * offset, ey = y2 - uy * gap + py * offset;
  const stroke = style === "path" ? toneVar[tone ?? "net"] : style === "added" ? toneVar.safe : style === "removed" || style === "ghost" ? toneVar.bad : "rgb(var(--line-strong))";
  const width = style === "path" ? 3 : style === "added" ? 2.5 : 1.75;
  return (
    <BaseEdge path={`M ${sx} ${sy} L ${ex} ${ey}`} markerEnd={style === "path" ? markerEnd : undefined}
      className={clsx(style === "path" && "path-flow")}
      style={{ stroke, strokeWidth: width, opacity: style === "ghost" ? 0.35 : dim ? 0.35 : 1,
        strokeDasharray: style === "removed" || style === "ghost" ? "5 5" : undefined }} />
  );
});

const nodeTypes = { device: DeviceNodeView };
const edgeTypes = { wire: WireView };

function Legend({ view, hasOverlay }: { view: CanvasView; hasOverlay: boolean }) {
  const Row = ({ swatch, text }: { swatch: React.ReactNode; text: string }) => <li className="flex items-center gap-2">{swatch}<span>{text}</span></li>;
  const line = (color: string, dash?: boolean, h = 2) => <span className="inline-block w-5" style={{ borderTop: `${h}px ${dash ? "dashed" : "solid"} ${color}` }} />;
  return (
    <ul className="flex flex-wrap gap-x-5 gap-y-1 border-t border-line bg-panel px-3 py-2 text-xs text-muted">
      <Row swatch={line("rgb(var(--line-strong))")} text="Link" />
      {view === "before" && <Row swatch={line(toneVar.bad, true)} text="Removed by the change" />}
      {view === "after" && <Row swatch={line(toneVar.safe, false, 3)} text="Added by the change" />}
      {view === "after" && <Row swatch={<span className="inline-block w-5" style={{ borderTop: `2px dashed ${toneVar.bad}`, opacity: 0.4 }} />} text="Removed (no longer present)" />}
      {hasOverlay && <Row swatch={line(toneVar.net, false, 3)} text="Selected traffic path" />}
      {hasOverlay && <Row swatch={<span className="inline-block size-3 rounded-full border-2" style={{ borderColor: toneVar.bad }} />} text="Where traffic stops" />}
    </ul>
  );
}

const FIT = { padding: 0.22 };

/**
 * Expands the map (with its legend) to fill the window, and asks for true fullscreen where the
 * browser allows it; embedded browsers often refuse, and the expanded view still works there.
 * Esc or the button again closes it. The map re-fits after every size change.
 */
function useFullscreen() {
  const ref = useRef<HTMLDivElement>(null);
  const [full, setFull] = useState(false);
  const { fitView } = useReactFlow();
  // Re-fit once the new size has settled; React Flow measures it on the next frames.
  const first = useRef(true);
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    const t = setTimeout(() => void fitView(FIT), 200);
    return () => clearTimeout(t);
  }, [full, fitView]);
  useEffect(() => {
    if (!full) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setFull(false); };
    // Leaving true fullscreen (Esc is handled by the browser then) also closes the expanded view.
    const onChange = () => { if (!document.fullscreenElement) setFull(false); };
    document.addEventListener("keydown", onKey);
    document.addEventListener("fullscreenchange", onChange);
    return () => { document.removeEventListener("keydown", onKey); document.removeEventListener("fullscreenchange", onChange); };
  }, [full]);
  const toggle = () => {
    if (full) {
      setFull(false);
      if (document.fullscreenElement) void document.exitFullscreen().catch(() => {});
    } else {
      setFull(true);
      if (document.fullscreenEnabled) void ref.current?.requestFullscreen().catch(() => {});
    }
  };
  return { ref, full, toggle };
}

function Inner({ topology, view = "plain", overlays = [], marks = {}, selected, onSelect, minimap, hideLegend, ariaLabel }: Props) {
  const fs = useFullscreen();
  const { nodes, edges } = useMemo(() => {
    const raw = topology.nodes;
    const xs = raw.map((n) => n.x), ys = raw.map((n) => n.y);
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const extra = Math.max(0, raw.length - 12);
    const W = 900 + extra * 30, H = 520 + extra * 18;
    const pos: Record<string, { x: number; y: number }> = {};
    for (const n of raw) pos[n.id] = { x: ((n.x - x0) / (x1 - x0 || 1)) * W, y: ((n.y - y0) / (y1 - y0 || 1)) * H };
    const onPath = new Set(overlays.flatMap((o) => o.nodes));
    const dimOthers = overlays.length > 0;

    const nodes: DeviceNode[] = raw.map((n) => ({
      // A fixed size: the minimap skips nodes without one, and these nodes are never resized.
      id: n.id, type: "device", position: { x: pos[n.id].x - R, y: pos[n.id].y - R }, width: 2 * R, height: 2 * R, draggable: false, selectable: true,
      data: { id: n.id, label: n.label || n.id, ip: n.ip, type: n.type, mark: marks[n.id], selected: selected === n.id, dim: dimOthers && !onPath.has(n.id), onPath: onPath.has(n.id) },
    }));

    const edges: WireEdge[] = [];
    for (const l of topology.links) {
      if (view === "before" && l.status === "added") continue;
      const style: WireStyle = l.status === "added" ? "added" : l.status === "removed" ? (view === "after" ? "ghost" : "removed") : "link";
      edges.push({ id: `l:${l.source}|${l.destination}`, type: "wire", source: l.source, target: l.destination, zIndex: 0, selectable: false,
        data: { x1: pos[l.source].x, y1: pos[l.source].y, x2: pos[l.destination].x, y2: pos[l.destination].y, style, offset: 0, dim: dimOthers } });
    }
    overlays.forEach((o, oi) => {
      for (let i = 0; i + 1 < o.nodes.length; i++) {
        const a = o.nodes[i], b = o.nodes[i + 1];
        if (!pos[a] || !pos[b] || a === b) continue;
        edges.push({ id: `p:${o.id}:${i}`, type: "wire", source: a, target: b, zIndex: 10 + oi, selectable: false,
          markerEnd: { type: MarkerType.ArrowClosed, color: toneVar[o.tone], width: 14, height: 14 },
          data: { x1: pos[a].x, y1: pos[a].y, x2: pos[b].x, y2: pos[b].y, style: "path", tone: o.tone, offset: oi * 6, dim: false } });
      }
    });
    return { nodes, edges };
  }, [topology, view, overlays, marks, selected]);

  return (
    <div ref={fs.ref} className={clsx("flex flex-col", fs.full ? "fixed inset-0 z-50 bg-ink" : "h-full w-full")} role="img" aria-label={ariaLabel}>
      <div className="relative min-h-0 flex-1">
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
        fitView fitViewOptions={FIT} minZoom={0.2} maxZoom={2.5}
        nodesDraggable={false} nodesConnectable={false} edgesFocusable={false}
        onNodeClick={(_, n) => onSelect?.(n.id === selected ? null : n.id)} onPaneClick={() => onSelect?.(null)}>
        <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="rgb(var(--line))" />
        <Controls showInteractive={false} position="top-right" fitViewOptions={FIT}>
          <ControlButton onClick={fs.toggle} title={fs.full ? "Exit fullscreen (Esc)" : "Fullscreen"} aria-label={fs.full ? "Exit fullscreen" : "Fullscreen"}
            className="react-flow__controls-fullscreen">
            {fs.full ? <Minimize2 style={{ fill: "none" }} strokeWidth={2.25} /> : <Maximize2 style={{ fill: "none" }} strokeWidth={2.25} />}
          </ControlButton>
        </Controls>
        {minimap && <MiniMap pannable zoomable nodeColor="rgb(var(--muted))" nodeBorderRadius={22} maskColor="rgb(14 17 22 / 0.7)" />}
      </ReactFlow>
      </div>
      {!hideLegend && <Legend view={view} hasOverlay={overlays.length > 0} />}
    </div>
  );
}

/** Interactive topology. Remounts (and so re-fits) when the set of devices changes. */
export function TopologyCanvas(props: Props) {
  const key = useMemo(() => props.topology.nodes.map((n) => n.id).join(","), [props.topology]);
  return (
    <div className={clsx("min-h-0", props.className)}>
      <ReactFlowProvider key={key}><Inner {...props} /></ReactFlowProvider>
    </div>
  );
}
