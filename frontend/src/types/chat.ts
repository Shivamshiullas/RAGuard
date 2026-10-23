// Chat message model and the backend chat contract (POST /api/chat).

export type MessageRole = "user" | "assistant";

export type AnswerStatus =
  | "general"
  | "success"
  | "partial"
  | "no_evidence"
  | "degraded"
  | "failed"
  | "clarification"
  | "declined";

export type Route = "general" | "college_specific" | "multi_task" | "unclear" | "out_of_scope";

export interface Source {
  filename: string;
  page: number;
  title: string;
  docId: string;
  version: number;
  snippet: string;
}

export interface TaskItem {
  taskId: string;
  question: string;
  status: "success" | "partial" | "no_evidence" | "degraded" | "failed" | "skipped";
  agent: string;
}

export interface ChatResponse {
  answer: string;
  status: AnswerStatus;
  route: Route;
  sources: Source[];
  warnings: string[];
  tasks: { completed: number; total: number; items: TaskItem[] };
  agents: string[];
  recovery: { attempted: boolean; method: string | null; status: "not_needed" | "recovered" | "failed" };
  requestId: string;
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  text: string;
  /** File name of an attached screenshot, if the user added one. */
  attachmentName?: string;
  /** Object URL for a thumbnail of the attached screenshot. */
  attachmentPreview?: string;
  /** Full backend response for assistant replies. */
  response?: ChatResponse;
  /** Set when the request itself failed (network or validation). */
  error?: boolean;
}

export interface OutgoingMessage {
  text: string;
  attachment?: File;
}
