// Phase 1 message model. The full backend contract (ChatResponse, Evidence,
// answer_status) is introduced in Phase 2.

export type MessageRole = "user" | "assistant";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  text: string;
  /** File name of an attached screenshot, if the user added one. */
  attachmentName?: string;
}

export interface OutgoingMessage {
  text: string;
  attachment?: File;
}
