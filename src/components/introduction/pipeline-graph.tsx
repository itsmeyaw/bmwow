"use client";

import {
  AiBrain01Icon,
  Car01Icon,
  ChartLineData01Icon,
  CheckmarkBadge01Icon,
  CodeIcon,
  DatabaseIcon,
  FullScreenIcon,
  Layers01Icon,
  Message01Icon,
  MinimizeScreenIcon,
  Search01Icon,
  Shield01Icon,
  Target01Icon,
  UserGroupIcon,
  UserIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import {
  ControlButton,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useEffect, useRef, useSyncExternalStore, type RefObject } from "react";
import { cn } from "@/lib/utils";

type Actor = "code" | "llm" | "human";
type Icon = typeof Car01Icon;

const ACTORS: Record<Actor, { label: string; className: string; icon: Icon }> = {
  code: { label: "Code", className: "bg-muted text-foreground", icon: CodeIcon },
  llm: {
    label: "LLM",
    className: "bg-sky-500/10 text-sky-700 dark:text-sky-300",
    icon: AiBrain01Icon,
  },
  human: {
    label: "PM",
    className: "bg-amber-500/10 text-amber-700 dark:text-amber-300",
    icon: UserIcon,
  },
};

function Tags({ actors }: { actors: Actor[] }) {
  return (
    <span className="flex flex-wrap gap-1">
      {actors.map((a) => (
        <span
          key={a}
          className={cn(
            "inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium",
            ACTORS[a].className,
          )}
        >
          <HugeiconsIcon icon={ACTORS[a].icon} strokeWidth={2} className="size-3" />
          {ACTORS[a].label}
        </span>
      ))}
    </span>
  );
}

/** Who does what: code, the LLM or the PM. */
export function ActorLegend() {
  return <Tags actors={["code", "llm", "human"]} />;
}

type StepData = { icon: Icon; title: string; text: string; actors: Actor[] };
type LaneData = { label: string };
type StepNode = Node<StepData, "step">;
type LaneNode = Node<LaneData, "lane">;

// Handles are invisible: the graph is read-only, they only anchor edges.
const hidden = "!border-0 !bg-transparent";

function Step({ data }: NodeProps<StepNode>) {
  return (
    <div className="flex w-56 flex-col gap-2 rounded-xl border bg-card p-3 text-card-foreground shadow-xs">
      <div className="flex items-center gap-2">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-muted">
          <HugeiconsIcon icon={data.icon} strokeWidth={2} className="size-4" />
        </span>
        <span className="min-w-0 text-sm leading-tight font-medium">{data.title}</span>
      </div>
      <p className="text-xs leading-relaxed text-muted-foreground">{data.text}</p>
      <Tags actors={data.actors} />
      <Handle type="target" position={Position.Left} className={hidden} />
      <Handle type="source" position={Position.Right} className={hidden} />
      <Handle id="top" type="source" position={Position.Top} className={hidden} />
      <Handle id="right" type="target" position={Position.Right} className={hidden} />
    </div>
  );
}

function Lane({ data }: NodeProps<LaneNode>) {
  return (
    <div className="size-full rounded-xl border border-dashed p-2">
      <p className="px-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
        {data.label}
      </p>
    </div>
  );
}

const nodeTypes = { step: Step, lane: Lane };

const step = (id: string, x: number, y: number, data: StepData, parentId?: string): StepNode => ({
  id,
  type: "step",
  position: { x, y },
  data,
  parentId,
  extent: parentId ? "parent" : undefined,
});

// ponytail: positions by hand for a fixed ~12-node graph; add dagre/elk if it grows or changes often.
const nodes: (StepNode | LaneNode)[] = [
  step("input", 0, 320, {
    icon: Target01Icon,
    title: "Input",
    text: "A car (e.g. G60) and its regions: EU, US, CN or all.",
    actors: ["human"],
  }),
  {
    id: "agents",
    type: "lane",
    position: { x: 280, y: 0 },
    data: { label: "Four agents in parallel" },
    style: { width: 256, height: 726 },
    selectable: false,
  },
  step(
    "baseline",
    16,
    36,
    {
      icon: Car01Icon,
      title: "Our model",
      text: "Price-list values per variant, customer studies, sales.",
      actors: ["code"],
    },
    "agents",
  ),
  step(
    "competition",
    16,
    206,
    {
      icon: Search01Icon,
      title: "Competitors",
      text: "Same-segment rivals; values from approved pages, quotes checked by code.",
      actors: ["llm", "code"],
    },
    "agents",
  ),
  step(
    "feedback",
    16,
    376,
    {
      icon: UserGroupIcon,
      title: "Customers",
      text: "Feedback shares with 95% intervals, per region; what exactly they mean.",
      actors: ["code", "llm"],
    },
    "agents",
  ),
  step(
    "trends",
    16,
    546,
    {
      icon: ChartLineData01Icon,
      title: "Trends",
      text: "Regulation, market and technology for a launch in 3–5 years.",
      actors: ["llm", "code"],
    },
    "agents",
  ),
  step("validate", 600, 320, {
    icon: Shield01Icon,
    title: "Validate",
    text: "Every claim cites a source; every number is in its source text.",
    actors: ["code"],
  }),
  step("structure", 870, 290, {
    icon: Layers01Icon,
    title: "Structure per feature",
    text: "Evidence package: ours vs. like-for-like competitors (same unit, test standard, powertrain), customer shares, trends. Code suggests an assessment; the LLM judges with a rubric; code checks the judgment.",
    actors: ["code", "llm"],
  }),
  step("candidates", 1140, 302, {
    icon: CheckmarkBadge01Icon,
    title: "Requirement candidates",
    text: "Gap · demand · hygiene factor · strength. Quantitative targets from the competitor median or today's value; wording checked against the evidence.",
    actors: ["code", "llm"],
  }),
  step("review", 1410, 170, {
    icon: UserIcon,
    title: "PM review",
    text: "Approve, reject, constrain targets.",
    actors: ["human"],
  }),
  step("ask", 1410, 320, {
    icon: Message01Icon,
    title: "Ask why",
    text: "Chat answers from this run only, citing requirements and feedback.",
    actors: ["llm", "code"],
  }),
  step("stored", 1410, 470, {
    icon: DatabaseIcon,
    title: "Stored",
    text: "Every run in SQL: findings, sources, reasoning.",
    actors: ["code"],
  }),
];

const AGENTS = ["baseline", "competition", "feedback", "trends"];
const arrow = { type: MarkerType.ArrowClosed };
const edge = (source: string, target: string): Edge => ({
  id: `${source}-${target}`,
  source,
  target,
  type: "smoothstep",
  markerEnd: arrow,
});

const edges: Edge[] = [
  ...AGENTS.map((a) => edge("input", a)),
  ...AGENTS.map((a) => edge(a, "validate")),
  edge("validate", "structure"),
  edge("structure", "candidates"),
  edge("candidates", "review"),
  edge("candidates", "ask"),
  edge("candidates", "stored"),
  {
    id: "gap-fill",
    source: "structure",
    sourceHandle: "top",
    target: "competition",
    targetHandle: "right",
    type: "smoothstep",
    markerEnd: arrow,
    animated: true,
    style: { strokeDasharray: "6 4" },
  },
];

// The app's dark mode follows the OS (globals.css). colorMode="system" would render "light" on the
// server and mismatch on hydration, so read the media query as an external store instead.
const DARK = "(prefers-color-scheme: dark)";
const subscribeDark = (onChange: () => void) => {
  const q = matchMedia(DARK);
  q.addEventListener("change", onChange);
  return () => q.removeEventListener("change", onChange);
};
const isDark = () => (matchMedia(DARK).matches ? "dark" : "light");

const subscribeFullscreen = (onChange: () => void) => {
  document.addEventListener("fullscreenchange", onChange);
  return () => document.removeEventListener("fullscreenchange", onChange);
};

/** Fullscreen toggle in the controls; re-fits the graph whenever the size changes. */
function FullscreenButton({
  target,
  full,
}: {
  target: RefObject<HTMLDivElement | null>;
  full: boolean;
}) {
  const { fitView } = useReactFlow();
  useEffect(() => {
    const id = requestAnimationFrame(() => fitView());
    return () => cancelAnimationFrame(id);
  }, [full, fitView]);
  return (
    <ControlButton
      title={full ? "Exit full screen" : "Full screen"}
      aria-label={full ? "Exit full screen" : "Full screen"}
      onClick={() => (full ? document.exitFullscreen() : target.current?.requestFullscreen())}
    >
      <HugeiconsIcon icon={full ? MinimizeScreenIcon : FullScreenIcon} strokeWidth={2} />
    </ControlButton>
  );
}

/** A read-only React Flow canvas: pan and zoom, nothing to edit, with a fullscreen toggle. */
export function FlowCanvas({
  nodes,
  edges,
  nodeTypes,
  className,
}: {
  nodes: Node[];
  edges: Edge[];
  nodeTypes: NodeTypes;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const full = useSyncExternalStore(
    subscribeFullscreen,
    () => document.fullscreenElement !== null && document.fullscreenElement === ref.current,
    () => false,
  );
  return (
    // bg-card: the fullscreen element would otherwise sit on the browser's black backdrop.
    <div ref={ref} className={cn("min-h-80 w-full bg-card", className)}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        className="!bg-transparent"
        colorMode={useSyncExternalStore(subscribeDark, isDark, () => "light")}
        fitView
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        zoomOnScroll={full}
        preventScrolling={full}
        minZoom={0.2}
      >
        <Controls showInteractive={false}>
          <FullscreenButton target={ref} full={full} />
        </Controls>
      </ReactFlow>
    </div>
  );
}

/** The analysis pipeline as a read-only graph. */
export function PipelineGraph() {
  return <FlowCanvas nodes={nodes} edges={edges} nodeTypes={nodeTypes} className="aspect-[5/2]" />;
}
