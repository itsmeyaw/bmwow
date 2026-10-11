"use client";

import { Handle, MarkerType, Position, type Edge, type Node, type NodeProps } from "@xyflow/react";
import { FlowCanvas } from "@/components/introduction/pipeline-graph";

type Column = { name: string; type: string; note: string; key?: "PK" | "FK" };
type TableData = { name: string; text: string; columns: Column[] };
type TableNode = Node<TableData, "table">;

// Handles are invisible: the graph is read-only, they only anchor edges.
const hidden = "!border-0 !bg-transparent";

/** One table; every key column gets its own handle so the edge lands on the right row. */
function Table({ data }: NodeProps<TableNode>) {
  return (
    <div className="w-[30rem] overflow-hidden rounded-xl border bg-card text-card-foreground shadow-xs">
      <div className="border-b bg-muted/50 px-3 py-2">
        <p className="font-mono text-sm font-medium">{data.name}</p>
        <p className="text-xs text-muted-foreground">{data.text}</p>
      </div>
      {data.columns.map((c) => (
        <div
          key={c.name}
          className="relative grid grid-cols-[10.5rem_6rem_1fr] items-start gap-2 border-b px-3 py-1.5 text-xs last:border-b-0"
        >
          <span className="flex items-center gap-1 font-mono font-medium">
            {c.name}
            {c.key && (
              <span className="rounded bg-amber-500/10 px-1 text-[9px] text-amber-700 dark:text-amber-300">
                {c.key}
              </span>
            )}
          </span>
          <span className="font-mono text-muted-foreground">{c.type}</span>
          <span className="leading-snug text-muted-foreground">{c.note}</span>
          {c.key === "PK" && (
            <Handle id={c.name} type="target" position={Position.Right} className={hidden} />
          )}
          {c.key === "FK" && (
            <Handle id={c.name} type="source" position={Position.Left} className={hidden} />
          )}
        </div>
      ))}
    </div>
  );
}

const nodeTypes = { table: Table };

// Mirrors migrations/0000_init.sql; update both together.
const nodes: TableNode[] = [
  {
    id: "feedback_entries",
    type: "table",
    position: { x: 0, y: 0 },
    data: {
      name: "feedback_entries",
      text: "One row per feedback: the vehicle it is about and the customer's verbatim.",
      columns: [
        { name: "id", type: "uuid", note: "Row key, generated.", key: "PK" },
        {
          name: "feedback_explorer_id",
          type: "text",
          note: "The feedback's ID in Feedback Explorer; unique.",
        },
        { name: "source", type: "text", note: "Channel it came through (Source A–D)." },
        { name: "brand", type: "text", note: "Vehicle brand." },
        { name: "sales_description", type: "text", note: 'Marketing name, e.g. "BMW 1 Series".' },
        { name: "country", type: "text", note: "Market the customer is in." },
        { name: "derivate_code", type: "text", note: "Model code, e.g. G60." },
        { name: "engine_type", type: "text", note: "ICE, PHEV or BEV." },
        { name: "raw_feedback", type: "text", note: "The verbatim, exactly as written." },
        { name: "embedding", type: "vector", note: "1536-dim vector for semantic search." },
        {
          name: "search_tsv",
          type: "tsvector",
          note: "Generated from the verbatim for keyword search.",
        },
        { name: "created_at", type: "timestamptz", note: "When the row was loaded." },
      ],
    },
  },
  {
    id: "feedback_aspects",
    type: "table",
    position: { x: 640, y: 0 },
    data: {
      name: "feedback_aspects",
      text: "One row per aspect: one thing a feedback says about one part of the vehicle.",
      columns: [
        { name: "id", type: "uuid", note: "Row key, generated.", key: "PK" },
        {
          name: "feedback_entry_id",
          type: "uuid",
          note: "The feedback this aspect belongs to; deleted with it.",
          key: "FK",
        },
        {
          name: "feedback_type",
          type: "text",
          note: "Likes, Difficult to Use, Wants or Defect; per aspect, not per feedback.",
        },
        { name: "vfc_category", type: "text", note: "One of 16 coarse buckets for the part." },
        { name: "aspect_term", type: "text", note: "VFC level 2: the component or feature." },
        { name: "aspect_label_raw", type: "text", note: "VFC level 3: what was said about it." },
        { name: "issue_type", type: "text", note: "One of 11 buckets, e.g. Malfunction, Praise." },
        { name: "quote_snippet", type: "text", note: "Supporting passage; inferred aspects only." },
        {
          name: "sentiment",
          type: "text",
          note: "Positive, Negative or Neutral, from issue type.",
        },
        { name: "sentiment_score", type: "numeric", note: "Signed intensity, −1 to +1." },
        {
          name: "extraction_source",
          type: "text",
          note: "vfc_label (curated by a human) or llm (inferred).",
        },
        { name: "created_at", type: "timestamptz", note: "When the row was loaded." },
      ],
    },
  },
];

const edges: Edge[] = [
  {
    id: "aspect-entry",
    source: "feedback_aspects",
    sourceHandle: "feedback_entry_id",
    target: "feedback_entries",
    targetHandle: "id",
    type: "smoothstep",
    markerEnd: { type: MarkerType.ArrowClosed },
    label: "N aspects : 1 feedback",
  },
];

/** The feedback tables and how they join, as a read-only graph. */
export function SchemaGraph() {
  return <FlowCanvas nodes={nodes} edges={edges} nodeTypes={nodeTypes} className="aspect-[2/1]" />;
}
