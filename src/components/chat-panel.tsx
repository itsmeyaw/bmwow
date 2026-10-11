"use client";

import { useChat } from "@ai-sdk/react";
import type { UIMessage } from "ai";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Streamdown } from "streamdown";
import { HugeiconsIcon } from "@hugeicons/react";
import {
  AiChat02Icon,
  MessageAdd01Icon,
  SentIcon,
  SidebarRightIcon,
  StopIcon,
} from "@hugeicons/core-free-icons";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Textarea } from "@/components/ui/textarea";
import { countryName } from "@/lib/format";

const MIN_WIDTH = 320;
const WIDTH_KEY = "chat-width";
/** Citation markers the agent writes, e.g. `[G70-0042]`. */
const CITATION = /\[([A-Z0-9]{2,8}-\d+)\]/g;
/** Step labels per tool: [running, done]. */
const TOOL_LABEL: Record<string, [string, string]> = {
  searchFeedback: ["Searching feedback…", "Searched feedback"],
  getRanking: ["Comparing rankings…", "Read ranking"],
  getCategoryDetail: ["Reading category detail…", "Read category detail"],
  getEvidence: ["Reading verbatims…", "Read verbatims"],
  searchWeb: ["Searching the web…", "Searched the web"],
};

type Cited = {
  id: string;
  derivate: string | null;
  country: string | null;
  engine: string | null;
  source: string | null;
  text: string;
  quote: string | null;
};
const noSubscribe = () => () => {};
type ToolPart = {
  type: string;
  state: string;
  input?: Record<string, unknown>;
  output?: unknown;
  errorText?: string;
};

const toolParts = (m: UIMessage) =>
  m.parts.filter((p) => p.type.startsWith("tool-")) as unknown as ToolPart[];

/** Every verbatim a tool returned in this thread, by feedback id; only these can be cited. */
function citedIndex(messages: UIMessage[]) {
  const index = new Map<string, Cited>();
  for (const m of messages)
    for (const p of toolParts(m))
      if (p.state === "output-available" && Array.isArray(p.output))
        for (const x of p.output as Cited[]) if (x?.id && x.text) index.set(x.id, x);
  return index;
}

export function ChatPanel() {
  const [open, setOpen] = useState(true);
  const saved = useSyncExternalStore(
    noSubscribe,
    () => Math.max(Number(localStorage.getItem(WIDTH_KEY)) || 0, MIN_WIDTH),
    () => MIN_WIDTH,
  );
  /** Width while dragging; `null` falls back to the saved width. */
  const [drag, setDrag] = useState<number | null>(null);
  const width = drag ?? saved;
  const [input, setInput] = useState("");
  const scroller = useRef<HTMLDivElement>(null);
  const derivate = usePathname().match(/^\/analysis\/([^/]+)/)?.[1] ?? null;
  const search = useSearchParams();
  const page = { derivate, region: search.get("region"), engine: search.get("engine") };
  const { messages, sendMessage, setMessages, status, stop, error } = useChat();
  const cited = useMemo(() => citedIndex(messages), [messages]);
  const busy = status === "submitted" || status === "streaming";

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [messages]);

  const send = (text: string) => {
    if (!text.trim() || busy) return;
    sendMessage({ text, metadata: { page } }, { body: { page } });
    setInput("");
  };

  const startResize = (e: React.PointerEvent) => {
    const startX = e.clientX;
    let last = width;
    const move = (ev: PointerEvent) => {
      last = Math.min(Math.max(width + startX - ev.clientX, MIN_WIDTH), window.innerWidth / 2);
      setDrag(last);
    };
    const up = () => {
      localStorage.setItem(WIDTH_KEY, String(Math.round(last)));
      setDrag(null);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    setDrag(width);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const suggestions = derivate
    ? [
        `What is the most pressing issue of the ${derivate}?`,
        `What should be improved from this ${derivate}?`,
        `What should be added to this ${derivate}?`,
      ]
    : [
        "Which car has the most pressing issue?",
        "What should be improved across all cars?",
        "What should be added to our cars?",
      ];
  const last = messages.at(-1);

  return (
    <aside
      data-open={open}
      style={open ? { width } : undefined}
      className={`sticky top-0 hidden h-svh shrink-0 flex-col py-2 pr-2 text-sidebar-foreground data-[open=false]:w-12 lg:flex ${drag != null ? "select-none" : "transition-[width] duration-200"}`}
    >
      {open && (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize chat"
          onPointerDown={startResize}
          className="absolute inset-y-0 left-0 w-1.5 cursor-col-resize hover:bg-border"
        />
      )}
      <div className="flex h-12 items-center gap-2 px-2">
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={open ? "Collapse chat" : "Expand chat"}
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          <HugeiconsIcon icon={open ? SidebarRightIcon : AiChat02Icon} strokeWidth={2} />
        </Button>
        {open && (
          <>
            <span className="flex-1 text-sm font-medium">Ask about this view</span>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="New chat"
              disabled={!messages.length}
              onClick={() => {
                stop();
                setMessages([]);
              }}
            >
              <HugeiconsIcon icon={MessageAdd01Icon} strokeWidth={2} />
            </Button>
          </>
        )}
      </div>
      {open && (
        <>
          <div ref={scroller} className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-2">
            {!messages.length && (
              <div className="m-auto flex flex-col gap-2">
                {suggestions.map((s) => (
                  <Button
                    key={s}
                    variant="outline"
                    className="h-auto justify-start px-3 py-2 text-left whitespace-normal"
                    onClick={() => send(s)}
                  >
                    {s}
                  </Button>
                ))}
              </div>
            )}
            {messages.map((m) =>
              m.role === "user" ? (
                <div
                  key={m.id}
                  className="ml-6 self-end rounded-lg bg-muted px-3 py-2 text-sm whitespace-pre-wrap"
                >
                  {m.parts.map((p) => (p.type === "text" ? p.text : "")).join("")}
                </div>
              ) : (
                <div key={m.id} className="flex min-w-0 flex-col gap-3 text-sm">
                  {m.parts.map((p, i) =>
                    p.type === "text" ? (
                      <Answer key={i} text={p.text} cited={cited} animating={busy && m === last} />
                    ) : p.type.startsWith("tool-") ? (
                      <Step key={i} part={p as unknown as ToolPart} />
                    ) : null,
                  )}
                </div>
              ),
            )}
            {status === "submitted" && (
              <p className="animate-pulse text-xs text-muted-foreground">Thinking…</p>
            )}
            {error && <p className="text-xs text-destructive">Something went wrong. Try again.</p>}
          </div>
          <form
            className="flex items-end gap-2 p-2"
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
          >
            <Textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  send(input);
                }
              }}
              placeholder="Ask a question…"
              aria-label="Chat message"
              className="max-h-40 min-h-9 resize-none"
              rows={1}
            />
            {busy ? (
              <Button type="button" size="icon" aria-label="Stop" onClick={() => stop()}>
                <HugeiconsIcon icon={StopIcon} strokeWidth={2} />
              </Button>
            ) : (
              <Button size="icon" aria-label="Send" disabled={!input.trim()}>
                <HugeiconsIcon icon={SentIcon} strokeWidth={2} />
              </Button>
            )}
          </form>
        </>
      )}
    </aside>
  );
}

function Answer({
  text,
  cited,
  animating,
}: {
  text: string;
  cited: Map<string, Cited>;
  animating: boolean;
}) {
  return (
    <Streamdown
      isAnimating={animating}
      className="[&_table]:text-xs"
      components={{
        a: ({ href, children, ...rest }) => {
          const id = href?.startsWith("#cite-") ? href.slice(6) : null;
          if (!id)
            return (
              <a href={href} target="_blank" rel="noreferrer" className="underline" {...rest}>
                {children}
              </a>
            );
          const c = cited.get(id);
          return c ? <Citation c={c} /> : <span className="font-mono text-xs">[{id}]</span>;
        },
      }}
    >
      {text.replace(CITATION, (_, id) => `[${id}](#cite-${id})`)}
    </Streamdown>
  );
}

function Citation({ c }: { c: Cited }) {
  const at = c.quote ? c.text.toLowerCase().indexOf(c.quote.toLowerCase()) : -1;
  return (
    <Popover>
      <PopoverTrigger className="mx-0.5 inline-flex cursor-pointer rounded bg-muted px-1 align-baseline font-mono text-[0.7rem] hover:bg-accent">
        {c.id}
      </PopoverTrigger>
      <PopoverContent className="w-96 gap-2">
        <blockquote className="max-h-60 overflow-y-auto leading-relaxed whitespace-pre-line">
          {at < 0 ? (
            c.text
          ) : (
            <>
              {c.text.slice(0, at)}
              <mark className="rounded bg-yellow-200/70 px-0.5 dark:bg-yellow-500/30 dark:text-inherit">
                {c.text.slice(at, at + c.quote!.length)}
              </mark>
              {c.text.slice(at + c.quote!.length)}
            </>
          )}
        </blockquote>
        <p className="flex flex-wrap gap-x-3 text-xs text-muted-foreground">
          <span className="font-mono">{c.id}</span>
          {c.derivate && <span>{c.derivate}</span>}
          <span>{countryName(c.country)}</span>
          {c.engine && <span>{c.engine}</span>}
          {c.source && <span>{c.source}</span>}
        </p>
      </PopoverContent>
    </Popover>
  );
}

/** One-line digest of a tool call's arguments: query or topic, category, sentiment, scope. */
function stepArgs(input: Record<string, unknown> = {}) {
  const { query, topic, category, sentiment, derivate, country, engine } = input;
  const scope =
    "derivate" in input ? [derivate ?? "all cars", country, engine].filter(Boolean).join(" ") : "";
  const q = query ?? topic;
  return [q && `"${q}"`, category, sentiment, scope].filter(Boolean).join(" · ");
}

type WebResult = { summary: string; sources: { title: string; url: string }[] };
const isWeb = (x: unknown): x is WebResult => Array.isArray((x as WebResult | null)?.sources);

/** A tool call, collapsed to a summary line; expand to see what it returned. */
function Step({ part }: { part: ToolPart }) {
  const [running, done] = TOOL_LABEL[part.type.slice(5)] ?? ["Working…", part.type.slice(5)];
  const { state, output } = part;
  if (state.startsWith("input"))
    return <p className="animate-pulse text-xs text-muted-foreground">{running}</p>;
  const count = Array.isArray(output)
    ? ` · ${output.length} results`
    : isWeb(output)
      ? ` · ${output.sources.length} sources`
      : "";
  return (
    <details className="group rounded-md border text-xs">
      <summary className="cursor-pointer list-none truncate px-2 py-1 text-muted-foreground hover:text-foreground">
        <span className="mr-1 inline-block transition-transform group-open:rotate-90">›</span>
        {state === "output-error" ? `${done} failed` : done}
        {" · "}
        {stepArgs(part.input)}
        {count}
      </summary>
      <div className="max-h-72 overflow-auto border-t p-2">
        {state === "output-error" ? (
          <p className="text-destructive">{part.errorText}</p>
        ) : Array.isArray(output) && output.every((x) => x?.id && x.text) ? (
          <ul className="flex flex-col gap-1.5">
            {(output as Cited[]).map((c) => (
              <li key={c.id} className="flex items-start gap-1">
                <Citation c={c} />
                <span className="line-clamp-2">{c.text}</span>
              </li>
            ))}
          </ul>
        ) : isWeb(output) ? (
          <ul className="flex flex-col gap-1">
            {output.sources.length ? (
              output.sources.map((s) => (
                <li key={s.url} className="truncate">
                  <a href={s.url} target="_blank" rel="noreferrer" className="underline">
                    {s.title}
                  </a>{" "}
                  <span className="text-muted-foreground">{new URL(s.url).hostname}</span>
                </li>
              ))
            ) : (
              <li className="text-muted-foreground">{output.summary}</li>
            )}
          </ul>
        ) : (
          <pre className="font-mono text-[0.7rem] whitespace-pre">
            {typeof output === "string" ? output : JSON.stringify(output, null, 2)}
          </pre>
        )}
      </div>
    </details>
  );
}
