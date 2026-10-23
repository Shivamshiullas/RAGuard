import type { AdminDocument, DocumentVersion, FileKind, ProcessingStage } from "../types/documents";

export const ACCEPTED_FILE_TYPES = ".pdf,.doc,.docx,.txt";
export const MAX_UPLOAD_MB = 25;

export const DOCUMENT_CATEGORIES = [
  "Fees",
  "Academic calendar",
  "Admissions",
  "Examinations",
  "Campus & facilities",
  "Policies & rules",
  "Other",
];

export const SEMESTERS = ["All semesters", ...Array.from({ length: 8 }, (_, i) => `Semester ${i + 1}`)];

export const FILE_KIND_LABELS: Record<FileKind, string> = {
  pdf: "PDF",
  doc: "DOC",
  docx: "DOCX",
  txt: "TXT",
};

export const STAGE_LABELS: Record<ProcessingStage, string> = {
  uploaded: "Uploaded",
  extracting: "Extracting text & images",
  ocr: "OCR",
  embedding: "Embedding",
  indexed: "Indexed",
  failed: "Failed",
};

/** Pipeline steps in order. OCR only runs when the file has scanned pages. */
export function processingSteps(ocrRequired: boolean): ProcessingStage[] {
  return ocrRequired
    ? ["uploaded", "extracting", "ocr", "embedding", "indexed"]
    : ["uploaded", "extracting", "embedding", "indexed"];
}

export function currentVersion(doc: AdminDocument): DocumentVersion {
  return doc.versions[doc.versions.length - 1];
}

export function isProcessing(version: DocumentVersion): boolean {
  return version.stage !== "indexed" && version.stage !== "failed";
}

export function fileKindOf(fileName: string): FileKind | null {
  const ext = fileName.split(".").pop()?.toLowerCase();
  return ext === "pdf" || ext === "doc" || ext === "docx" || ext === "txt" ? ext : null;
}

/** Returns an error message, or null when the file can be uploaded. */
export function validateUploadFile(file: File): string | null {
  if (!fileKindOf(file.name)) return "Unsupported file type. Upload a PDF, DOC, DOCX or TXT file.";
  if (file.size === 0) return "This file is empty.";
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return `This file is larger than ${MAX_UPLOAD_MB} MB.`;
  return null;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Formats an ISO timestamp or a date-only "YYYY-MM-DD" string. */
export function formatDate(value: string): string {
  const date = new Date(value.length === 10 ? `${value}T00:00:00` : value);
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}
