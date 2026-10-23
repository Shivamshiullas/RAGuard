import type { AdminDocument, DocumentVersion, FileKind, ProcessingStage } from "../types/documents";

export const ACCEPTED_FILE_TYPES = ".pdf,.docx,.txt,.png,.jpg,.jpeg";
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
  docx: "DOCX",
  txt: "TXT",
  png: "PNG",
  jpg: "JPG",
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
  if (ext === "jpeg") return "jpg";
  return ext === "pdf" || ext === "docx" || ext === "txt" || ext === "png" || ext === "jpg" ? ext : null;
}

/** Returns an error message, or null when the file can be uploaded. */
export function validateUploadFile(file: File): string | null {
  if (!fileKindOf(file.name)) return "Unsupported file type. Upload a PDF, DOCX, TXT, PNG or JPG file.";
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

export const ACCEPTED_IMAGE_TYPES = ["image/png", "image/jpeg"];
export const MAX_IMAGE_MB = 5;

/** Validates a chat screenshot. Returns an error message, or null when it can be sent. */
export function validateScreenshot(file: File): string | null {
  if (!ACCEPTED_IMAGE_TYPES.includes(file.type)) return "Attach a PNG or JPG image.";
  if (file.size === 0) return "This image is empty.";
  if (file.size > MAX_IMAGE_MB * 1024 * 1024) return `Images can be at most ${MAX_IMAGE_MB} MB.`;
  return null;
}
