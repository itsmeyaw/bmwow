import type { UIMessage } from "ai";
import { chat } from "@/server/chat/agent";

export async function POST(req: Request) {
  const { messages, page }: { messages: UIMessage[]; page: unknown } = await req.json();
  return chat(messages, page);
}
