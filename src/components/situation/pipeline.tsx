import {
  AiBrain01Icon,
  ArrowDown01Icon,
  ArrowRight01Icon,
  Car01Icon,
  ChartLineData01Icon,
  CheckmarkBadge01Icon,
  CodeIcon,
  DatabaseIcon,
  Layers01Icon,
  Message01Icon,
  RepeatIcon,
  Search01Icon,
  Shield01Icon,
  Target01Icon,
  UserGroupIcon,
  UserIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type Actor = "code" | "llm" | "human";
type Icon = typeof Car01Icon;

const ACTORS: Record<Actor, { label: string; className: string; icon: Icon }> = {
  code: {
    label: "Code",
    className: "bg-muted text-foreground",
    icon: CodeIcon,
  },
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

function Step({
  icon,
  title,
  actors,
  children,
  className,
}: {
  icon: Icon;
  title: string;
  actors: Actor[];
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-2 rounded-xl border bg-card p-3", className)}>
      <div className="flex items-center gap-2">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-muted">
          <HugeiconsIcon icon={icon} strokeWidth={2} className="size-4" />
        </span>
        <span className="min-w-0 text-sm leading-tight font-medium">{title}</span>
      </div>
      <div className="text-xs leading-relaxed text-muted-foreground">{children}</div>
      <Tags actors={actors} />
    </div>
  );
}

/** Arrow between columns: right on wide screens, down when the diagram stacks. */
function Flow() {
  return (
    <div className="flex items-center justify-center text-muted-foreground" aria-hidden>
      <HugeiconsIcon icon={ArrowRight01Icon} strokeWidth={2} className="hidden size-5 @4xl:block" />
      <HugeiconsIcon icon={ArrowDown01Icon} strokeWidth={2} className="size-5 @4xl:hidden" />
    </div>
  );
}

const AGENTS: { icon: Icon; title: string; text: string; actors: Actor[] }[] = [
  {
    icon: Car01Icon,
    title: "Our model",
    text: "Price-list values per variant, customer studies, sales.",
    actors: ["code"],
  },
  {
    icon: Search01Icon,
    title: "Competitors",
    text: "Same-segment rivals; values from approved pages, quotes checked by code.",
    actors: ["llm", "code"],
  },
  {
    icon: UserGroupIcon,
    title: "Customers",
    text: "Feedback shares with 95% intervals, per region; what exactly they mean.",
    actors: ["code", "llm"],
  },
  {
    icon: ChartLineData01Icon,
    title: "Trends",
    text: "Regulation, market and technology for a launch in 3–5 years.",
    actors: ["llm", "code"],
  },
];

/** The analysis pipeline as a diagram, for the overview page and the pitch. */
export function PipelineDiagram() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>How it works</CardTitle>
        <CardDescription>
          From one car and region to traceable requirements. Code computes every number and checks
          every LLM step; the LLM reads text and judges; the PM decides.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {/* Horizontal once the card itself is wide enough (container query), stacked otherwise. */}
        <div className="@container">
          <div className="grid items-center gap-3 @4xl:grid-cols-[minmax(0,0.7fr)_auto_minmax(0,2.4fr)_auto_minmax(0,1.4fr)_auto_minmax(0,1fr)_auto_minmax(0,1fr)]">
            <Step icon={Target01Icon} title="Input" actors={["human"]} className="justify-center">
              A car (e.g. G60) and its regions: EU, US, CN or all.
            </Step>
            <Flow />

            <div className="flex flex-col gap-2 rounded-xl border border-dashed p-2">
              <p className="px-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                Four agents in parallel
              </p>
              <div className="grid gap-2 @md:grid-cols-2">
                {AGENTS.map((a) => (
                  <Step key={a.title} icon={a.icon} title={a.title} actors={a.actors}>
                    {a.text}
                  </Step>
                ))}
              </div>
            </div>
            <Flow />

            <div className="flex flex-col gap-2">
              <Step icon={Shield01Icon} title="Validate" actors={["code"]}>
                Every claim cites a source; every number is in its source text.
              </Step>
              <Step icon={Layers01Icon} title="Structure per feature" actors={["code", "llm"]}>
                Evidence package: ours vs. like-for-like competitors (same unit, test standard,
                powertrain), customer shares, trends. Code suggests an assessment; the LLM judges
                with a rubric; code checks the judgment.
              </Step>
              <div className="flex items-center gap-1.5 rounded-lg bg-muted/60 px-2 py-1.5 text-[11px] text-muted-foreground">
                <HugeiconsIcon icon={RepeatIcon} strokeWidth={2} className="size-3.5 shrink-0" />
                Missing competitor data on an important feature: one targeted research round.
              </div>
            </div>
            <Flow />

            <Step
              icon={CheckmarkBadge01Icon}
              title="Requirement candidates"
              actors={["code", "llm"]}
            >
              Gap · demand · hygiene factor · strength. Quantitative targets from the competitor
              median or today&apos;s value; wording checked against the evidence.
            </Step>
            <Flow />

            <div className="flex flex-col gap-2">
              <Step icon={UserIcon} title="PM review" actors={["human"]}>
                Approve, reject, constrain targets.
              </Step>
              <Step icon={Message01Icon} title="Ask why" actors={["llm", "code"]}>
                Chat answers from this run only, citing requirements and feedback.
              </Step>
              <Step icon={DatabaseIcon} title="Stored" actors={["code"]}>
                Every run in SQL: findings, sources, reasoning.
              </Step>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
