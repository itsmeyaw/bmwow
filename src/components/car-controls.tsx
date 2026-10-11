"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Sheet, SheetContent } from "@/components/ui/sheet";

const ALL = "all";

/** A dropdown bound to one URL search param; "all" removes the param. */
export function ScopeSelect({
  param,
  label,
  allLabel,
  options,
}: {
  param: string;
  label: string;
  allLabel: string;
  options: { value: string; label: string }[];
}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const items = [{ value: ALL, label: allLabel }, ...options];
  return (
    <label className="flex flex-col gap-1 text-xs text-muted-foreground">
      {label}
      <Select
        items={items}
        value={params.get(param) ?? ALL}
        onValueChange={(v) => {
          const next = new URLSearchParams(params);
          if (!v || v === ALL) next.delete(param);
          else next.set(param, v);
          next.delete("n");
          router.push(`${pathname}?${next}`, { scroll: false });
        }}
      >
        <SelectTrigger className="min-w-44 text-foreground">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {items.map((o) => (
            <SelectItem key={o.value} value={o.value}>
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </label>
  );
}

/** The evidence drawer; its open state lives in the URL so views can be shared. */
export function AspectSheet({
  open,
  closeHref,
  children,
}: {
  open: boolean;
  closeHref: string;
  children: React.ReactNode;
}) {
  const router = useRouter();
  return (
    <Sheet open={open} onOpenChange={(o) => !o && router.push(closeHref, { scroll: false })}>
      <SheetContent className="w-full gap-0 overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-2xl">
        {children}
      </SheetContent>
    </Sheet>
  );
}
