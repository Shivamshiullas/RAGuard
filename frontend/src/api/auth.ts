// Admin sign-in. The backend checks the credentials and issues a session
// token that is kept in memory only (cleared on reload or sign-out).

import type { AdminSession } from "../types/auth";
import { apiFetch, setAuthToken } from "./client";

interface LoginResponse {
  token: string;
  username: string;
  role: "admin";
}

export async function signInAdmin(username: string, password: string): Promise<AdminSession> {
  if (!username.trim() || !password) {
    throw new Error("Enter a username and password.");
  }
  const res = await apiFetch<LoginResponse>("/api/admin/login", {
    method: "POST",
    body: JSON.stringify({ username: username.trim(), password }),
  });
  setAuthToken(res.token);
  return { username: res.username, role: "admin", token: res.token };
}

export function signOutAdmin() {
  setAuthToken(null);
}
