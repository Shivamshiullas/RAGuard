// Mock admin sign-in for the demo. Any non-empty username and password is
// accepted and nothing is stored. Real authorization must be enforced by the
// backend (Phase 5).

import type { AdminSession } from "../types/auth";

const MOCK_DELAY_MS = 600;

export async function signInAdmin(username: string, password: string): Promise<AdminSession> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_DELAY_MS));
  if (!username.trim() || !password) {
    throw new Error("Enter a username and password.");
  }
  return { username: username.trim(), role: "admin" };
}
