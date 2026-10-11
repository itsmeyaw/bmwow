"use client";

import { AiIdeaIcon, Attachment01Icon, Tick02Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useRouter } from "next/navigation";
import { createContext, useContext, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import type { Evidence } from "@/server/analysis/queries";

/** A verbatim the user pinned to the chat, with the VFC Category and tone it was shown under. */
export type Attachment = Evidence & { category: string; tone: "Negative" | "Positive" };

/** Sends a message with these attachments; false when the chat is busy or not mounted. */
type Send = (text: string, cards: Attachment[]) => boolean;

const SOLUTION_PROMPT =
  "Propose what BMW could change to address this complaint (product, software, documentation, service). Check how widespread it is in similar feedback and how competitors or the industry handle it.";

function useChatState() {
  const [open, setOpen] = useState(true);
  const [attached, setAttached] = useState<Attachment[]>([]);
  const sendRef = useRef<Send | null>(null);
  const has = (id: string) => attached.some((a) => a.id === id);
  return {
    open,
    setOpen,
    attached,
    setAttached,
    sendRef,
    has,
    toggle(card: Attachment) {
      setOpen(true);
      setAttached(has(card.id) ? attached.filter((a) => a.id !== card.id) : [...attached, card]);
    },
    /** Sends a solution request with every attached card plus this one; attaches it if busy. */
    ask(card: Attachment) {
      setOpen(true);
      const cards = has(card.id) ? attached : [...attached, card];
      if (!sendRef.current?.(SOLUTION_PROMPT, cards)) setAttached(cards);
    },
  };
}

const ChatContext = createContext<ReturnType<typeof useChatState> | null>(null);

export function ChatProvider({ children }: { children: React.ReactNode }) {
  return <ChatContext value={useChatState()}>{children}</ChatContext>;
}

export function useChatContext() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChatContext needs a ChatProvider");
  return ctx;
}

/** Card buttons: ask the agent for a solution (closes the sheet), or pin the card to the chat. */
export function VerbatimActions({ card, closeHref }: { card: Attachment; closeHref: string }) {
  const { has, toggle, ask } = useChatContext();
  const router = useRouter();
  const added = has(card.id);
  // Hidden below lg, like the chat panel itself.
  return (
    <span className="ml-auto hidden gap-1 lg:flex">
      {card.tone === "Negative" && (
        <Button
          variant="outline"
          size="xs"
          onClick={() => {
            ask(card);
            router.push(closeHref, { scroll: false });
          }}
        >
          <HugeiconsIcon icon={AiIdeaIcon} strokeWidth={2} />
          Find solution
        </Button>
      )}
      <Button variant="ghost" size="xs" aria-pressed={added} onClick={() => toggle(card)}>
        <HugeiconsIcon icon={added ? Tick02Icon : Attachment01Icon} strokeWidth={2} />
        {added ? "Added" : "Add to chat"}
      </Button>
    </span>
  );
}
