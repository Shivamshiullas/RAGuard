// Mock chat service for Phase 1. It does NOT contact any backend.
// Phase 5 replaces this module with a typed API client.

import type { OutgoingMessage } from "../types/chat";

const MOCK_DELAY_MS = 900;

const DEMO_NOTICE =
  "(Demo mode: this is a sample reply. The assistant is not connected to college documents yet.)";

function mockReplyFor(text: string, hasAttachment: boolean): string {
  const q = text.toLowerCase();

  if (/^(hi|hello|hey|good (morning|afternoon|evening))\b/.test(q)) {
    return "Hello! I can help with questions about fees, registration, admissions, and campus information.";
  }
  if (q.includes("fee")) {
    return `Fee details will come from the official fee schedule once the assistant is connected. ${DEMO_NOTICE}`;
  }
  if (q.includes("registration") || q.includes("register")) {
    return `Registration deadlines will be taken from the current academic calendar. ${DEMO_NOTICE}`;
  }
  if (q.includes("campus") || q.includes("located") || q.includes("location")) {
    return `The campus address and directions will be answered from official college information. ${DEMO_NOTICE}`;
  }
  if (hasAttachment) {
    return `Thanks, I received your screenshot. Reading screenshots will be added in a later version. ${DEMO_NOTICE}`;
  }
  return `I received your question. ${DEMO_NOTICE}`;
}

export async function sendMockMessage(message: OutgoingMessage): Promise<string> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_DELAY_MS));
  return mockReplyFor(message.text.trim(), Boolean(message.attachment));
}
