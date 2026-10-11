"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import { Analytics01Icon, BookOpen01Icon, Car01Icon, Task01Icon } from "@hugeicons/core-free-icons";
import { NavUser } from "@/components/nav-user";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";

// ponytail: placeholder until auth exists.
const user = { name: "Product Manager", email: "pm@bmw.example" };

const NAV = [
  { href: "/introduction", label: "Introduction", icon: BookOpen01Icon },
  { href: "/feedback", label: "Feedback", icon: Task01Icon }, // stroke-only; ClipboardListIcon's filled outline renders bold
  { href: "/analysis", label: "Analysis", icon: Analytics01Icon },
];

/** The page links; the active one follows the URL (read inside Suspense, so prerendering is not blocked). */
function NavItems({ pathname }: { pathname: string | null }) {
  return NAV.map(({ href, label, icon }) => (
    <SidebarMenuItem key={href}>
      <SidebarMenuButton
        tooltip={label}
        isActive={pathname?.startsWith(href) ?? false}
        render={<Link href={href} />}
      >
        <HugeiconsIcon icon={icon} strokeWidth={2} />
        <span>{label}</span>
      </SidebarMenuButton>
    </SidebarMenuItem>
  ));
}

function ActiveNavItems() {
  return <NavItems pathname={usePathname()} />;
}

export function AppSidebar(props: React.ComponentProps<typeof Sidebar>) {
  return (
    <Sidebar variant="inset" collapsible="icon" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" render={<Link href="/feedback" />}>
              <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                <HugeiconsIcon icon={Car01Icon} strokeWidth={2} className="size-4" />
              </div>
              <div className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-medium">BMWow</span>
                <span className="truncate text-xs">Customer feedback</span>
              </div>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarMenu>
            <Suspense fallback={<NavItems pathname={null} />}>
              <ActiveNavItems />
            </Suspense>
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <NavUser user={user} />
      </SidebarFooter>
    </Sidebar>
  );
}
