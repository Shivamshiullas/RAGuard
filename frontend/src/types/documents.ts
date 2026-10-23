export type FileKind = "pdf" | "doc" | "docx" | "txt";

export type ProcessingStage = "uploaded" | "extracting" | "ocr" | "embedding" | "indexed" | "failed";

export interface DocumentVersion {
  version: number;
  fileName: string;
  fileKind: FileKind;
  sizeBytes: number;
  /** ISO timestamp. */
  uploadedAt: string;
  /** Current stage. When "failed", `failedAt` holds the stage that failed. */
  stage: ProcessingStage;
  failedAt?: ProcessingStage;
  error?: string;
  /** True when the file has scanned pages that must be read with OCR. Decided by the backend. */
  ocrRequired: boolean;
}

export interface AdminDocument {
  id: string;
  title: string;
  category: string;
  semester?: string;
  academicYear?: string;
  /** Date only, "YYYY-MM-DD". */
  effectiveDate?: string;
  active: boolean;
  /** Oldest first; the last entry is the current version. */
  versions: DocumentVersion[];
}

export interface DocumentUpload {
  title: string;
  category: string;
  semester?: string;
  academicYear?: string;
  effectiveDate?: string;
  file: File;
  /** When set, the file is uploaded as a new version of this document. */
  replacesId?: string;
}
