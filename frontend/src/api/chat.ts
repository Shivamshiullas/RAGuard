// Chat API: one request per message, optional screenshot as multipart.

import type { ChatResponse, OutgoingMessage } from "../types/chat";
import { apiFetch } from "./client";

export async function sendMessage(message: OutgoingMessage): Promise<ChatResponse> {
  const form = new FormData();
  form.append("message", message.text);
  if (message.attachment) form.append("image", message.attachment);
  return apiFetch<ChatResponse>("/api/chat", { method: "POST", body: form });
}
