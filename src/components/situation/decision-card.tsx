"use client";

import { Tick02Icon, Undo02Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";

type Output = {
  decision?: { id: string; undoneAt: string | null };
  label?: string;
  text?: string;
  error?: string;
};

/** A PM decision the chat recorded (recordDecision tool result), with Undo. */
export function DecisionCard({ state, output }: { state: string; output?: unknown }) {
  const router = useRouter();
  const [undone, setUndone] = useState(false);
  const [busy, setBusy] = useState(false);
  if (state.startsWith("input"))
    return <p className="animate-pulse text-xs text-muted-foreground">Recording decision…</p>;
  const o = (output ?? {}) as Output;
  if (state === "output-error" || o.error || !o.decision)
    return <p className="text-xs text-destructive">Decision not recorded: {o.error ?? "error"}</p>;
  const id = o.decision.id;
  const undo = async () => {
    setBusy(true);
    const res = await fetch("/api/situation/decisions/undo", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ id }),
    });
    setBusy(false);
    if (res.ok) {
      setUndone(true);
      router.refresh(); // the run page shows the decision badges
    }
  };
  return (
    <div
      className={
        "flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs"
      }
    >
      <HugeiconsIcon icon={Tick02Icon} strokeWidth={2} className="mt-0.5 size-3.5 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="font-medium">
          {undone ? "Decision undone" : "Decision recorded"}
          <span className="font-normal text-muted-foreground"> · {o.label}</span>
        </p>
        <p className={undone ? "text-muted-foreground line-through" : ""}>{o.text}</p>
      </div>
      {!undone && (
        <Button variant="ghost" size="xs" onClick={undo} disabled={busy}>
          <HugeiconsIcon icon={Undo02Icon} strokeWidth={2} />
          Undo
        </Button>
      )}
    </div>
  );
}
