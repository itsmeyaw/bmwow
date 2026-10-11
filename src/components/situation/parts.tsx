import { Badge } from "@/components/ui/badge";
import { pct } from "@/lib/format";
import { cn } from "@/lib/utils";

/** What each assessment means; shown as badge title and in the legend. */
export const ASSESSMENTS: Record<string, { label: string; className: string; hint: string }> = {
  gap: {
    label: "Gap",
    className: "bg-destructive/10 text-destructive",
    hint: "We fall short of what customers expect or competitors offer.",
  },
  demand: {
    label: "Demand",
    className: "bg-sky-500/10 text-sky-700 dark:text-sky-300",
    hint: "Customers or the market ask for more, regardless of competitors.",
  },
  hygiene_factor: {
    label: "Hygiene factor",
    className: "bg-amber-500/10 text-amber-700 dark:text-amber-300",
    hint: "A baseline expectation: customers complain, but competitors are no better. Keep the level, fix the complaints.",
  },
  strength: {
    label: "Strength",
    className: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
    hint: "We lead, or customers praise it. Keep it.",
  },
  unclear: {
    label: "Unclear",
    className: "bg-muted text-muted-foreground",
    hint: "Evidence too thin or contradictory to decide.",
  },
  not_assessed: {
    label: "Not assessed",
    className: "bg-muted text-muted-foreground",
    hint: "Not assessed in this run.",
  },
};

export function AssessmentBadge({ value, method }: { value: string; method?: string }) {
  const a = ASSESSMENTS[value] ?? ASSESSMENTS.unclear;
  return (
    <Badge
      variant="secondary"
      className={cn("font-medium", a.className)}
      title={`${a.hint}${method === "rule" ? " (Rule-based: computed from the numbers, low certainty.)" : ""}`}
    >
      {a.label}
      {method === "rule" && <span className="opacity-60">· rule</span>}
    </Badge>
  );
}

/** "intuitive ux" -> "Intuitive UX": first letter up, known acronyms in capitals. */
export const sentence = (label: string) =>
  (label.charAt(0).toUpperCase() + label.slice(1)).replace(/\b(ux|adas|ev|bev|phev)\b/gi, (m) =>
    m.toUpperCase(),
  );

export const INTENTS: Record<string, string> = {
  introduce: "Introduce",
  improve: "Improve",
  retain: "Retain",
  remove: "Remove",
};

/** A number as written in the data: no trailing zeros, thousands separated. */
export const num = (x: number | null | undefined) =>
  x == null ? "–" : x.toLocaleString("en", { maximumFractionDigits: 2 });

export function target(
  op: string | null,
  value: number | null,
  unit: string | null,
  condition: string | null,
) {
  if (value == null) return null;
  return `${op ?? ""} ${num(value)} ${unit ?? ""}${condition ? ` · ${condition}` : ""}`.trim();
}

const TONES: Record<string, string> = {
  problem: "bg-destructive",
  request: "bg-sky-500",
  strength: "bg-emerald-500",
  neutral: "bg-muted-foreground",
};

export const DIRECTION_LABEL: Record<string, string> = {
  problem: "Problem",
  request: "Request",
  strength: "Praise",
  neutral: "Neutral",
};

/** A share with its 95% interval: the bar is the share, the darker band the interval. */
export function ShareBar({
  share,
  ciLow,
  ciHigh,
  direction,
  max,
}: {
  share: number;
  ciLow: number;
  ciHigh: number;
  direction: string;
  max: number;
}) {
  const scale = (x: number) => `${Math.min(x / max, 1) * 100}%`;
  return (
    <div className="relative h-2.5 w-full min-w-24 rounded-full bg-muted">
      <div
        className={cn("absolute inset-y-0 left-0 rounded-full opacity-80", TONES[direction])}
        style={{ width: scale(share) }}
      />
      <div
        className="absolute inset-y-[-3px] rounded-sm border border-foreground/40"
        style={{ left: scale(ciLow), width: `calc(${scale(ciHigh)} - ${scale(ciLow)})` }}
        title={`95% interval ${pct(ciLow)}–${pct(ciHigh)}`}
      />
    </div>
  );
}

export function Section({
  title,
  hint,
  children,
  empty,
}: {
  title: string;
  hint?: string;
  children?: React.ReactNode;
  empty?: string | false;
}) {
  return (
    <section className="flex flex-col gap-3">
      <div>
        <h3 className="text-sm font-medium">{title}</h3>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </div>
      {empty ? <p className="text-sm text-muted-foreground">{empty}</p> : children}
    </section>
  );
}

export function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-muted/50 p-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-medium tabular-nums">{value}</dd>
    </div>
  );
}

/** Reasoning text with its [id, id] citations rendered as small chips. */
export function Cited({ text }: { text: string }) {
  const parts = text.split(/(\[[^\]]+\])/g);
  return (
    <p className="text-sm leading-relaxed">
      {parts.map((p, i) =>
        p.startsWith("[") && p.endsWith("]") ? (
          <span
            key={i}
            className="mx-0.5 inline-block rounded bg-muted px-1 align-baseline font-mono text-[10px] text-muted-foreground"
            title={p.slice(1, -1)}
          >
            {p.slice(1, -1).split(",").length} src
          </span>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </p>
  );
}
