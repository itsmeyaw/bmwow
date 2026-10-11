import { Suspense } from "react";
import { AppSidebar } from "@/components/app-sidebar";
import { ChatProvider } from "@/components/chat-context";
import { ChatPanel } from "@/components/chat-panel";
import { Crumbs } from "@/components/crumbs";
import { Separator } from "@/components/ui/separator";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <ChatProvider>
      <SidebarProvider>
        <AppSidebar />
        <SidebarInset className="min-w-0">
          <header className="flex h-16 shrink-0 items-center gap-2 border-b px-4">
            <SidebarTrigger className="-ml-1" />
            <Separator
              orientation="vertical"
              className="mr-2 data-vertical:h-4 data-vertical:self-auto"
            />
            <Suspense>
              <Crumbs />
            </Suspense>
          </header>
          <div className="flex flex-1 flex-col gap-6 p-6">{children}</div>
        </SidebarInset>
        <Suspense>
          <ChatPanel />
        </Suspense>
      </SidebarProvider>
    </ChatProvider>
  );
}
