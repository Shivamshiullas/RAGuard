// Admin document store backed by the API. The list is refreshed after every
// action and polled while any document is still being processed, so the
// processing stages update live.

import type { AdminDocument, DocumentUpload } from "../types/documents";
import { currentVersion, isProcessing } from "../utils/documents";
import { apiFetch } from "./client";

const POLL_MS = 1200;

let documents: AdminDocument[] = [];
let loadError: string | null = null;
let pollTimer: ReturnType<typeof setTimeout> | null = null;
const listeners = new Set<() => void>();

function notify() {
  listeners.forEach((listener) => listener());
}

function schedulePoll() {
  if (pollTimer || listeners.size === 0) return;
  if (!documents.some((d) => isProcessing(currentVersion(d)))) return;
  pollTimer = setTimeout(() => {
    pollTimer = null;
    void refreshDocuments();
  }, POLL_MS);
}

export async function refreshDocuments(): Promise<void> {
  try {
    documents = await apiFetch<AdminDocument[]>("/api/documents");
    loadError = null;
  } catch (err) {
    loadError = err instanceof Error ? err.message : "Could not load documents.";
  }
  notify();
  schedulePoll();
}

function replaceDocument(doc: AdminDocument) {
  const exists = documents.some((d) => d.id === doc.id);
  documents = exists ? documents.map((d) => (d.id === doc.id ? doc : d)) : [doc, ...documents];
  notify();
  schedulePoll();
}

/** For useSyncExternalStore. Starts loading on first subscribe. */
export function subscribeDocuments(listener: () => void) {
  listeners.add(listener);
  if (listeners.size === 1) void refreshDocuments();
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  };
}

export function getDocuments(): AdminDocument[] {
  return documents;
}

export function getDocumentsError(): string | null {
  return loadError;
}

export function clearDocuments() {
  documents = [];
  loadError = null;
  notify();
}

export async function uploadDocument(upload: DocumentUpload): Promise<void> {
  const form = new FormData();
  form.append("file", upload.file);
  form.append("title", upload.title);
  form.append("category", upload.category);
  if (upload.semester) form.append("semester", upload.semester);
  if (upload.academicYear) form.append("academicYear", upload.academicYear);
  if (upload.effectiveDate) form.append("effectiveDate", upload.effectiveDate);
  if (upload.replacesId) form.append("replacesId", upload.replacesId);
  replaceDocument(await apiFetch<AdminDocument>("/api/documents", { method: "POST", body: form }));
}

export async function reprocessDocument(id: string): Promise<void> {
  replaceDocument(await apiFetch<AdminDocument>(`/api/documents/${id}/reprocess`, { method: "POST" }));
}

export async function setDocumentActive(id: string, active: boolean): Promise<void> {
  replaceDocument(
    await apiFetch<AdminDocument>(`/api/documents/${id}/active`, {
      method: "POST",
      body: JSON.stringify({ active }),
    }),
  );
}
