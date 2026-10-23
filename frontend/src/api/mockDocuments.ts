// Mock document store for the admin area. Uploads and processing are simulated
// in the browser and reset on page reload. Phase 5 replaces this module with the
// real API; the backend must enforce all authorization.

import type { AdminDocument, DocumentUpload, DocumentVersion } from "../types/documents";
import { currentVersion, fileKindOf, processingSteps } from "../utils/documents";

const UPLOAD_DELAY_MS = 600;
const STAGE_DELAY_MS = 1200;

// Demo-only rules so every pipeline path can be shown on demand:
// a PDF whose name contains "scan" has scanned pages (runs OCR);
// a file whose name contains "fail" fails at the embedding stage.
const needsOcr = (fileName: string) => fileKindOf(fileName) === "pdf" && /scan/i.test(fileName);
const shouldFail = (fileName: string) => /fail/i.test(fileName);

let documents: AdminDocument[] = [
  {
    id: "doc-fees",
    title: "Fee Structure 2025-26",
    category: "Fees",
    semester: "All semesters",
    academicYear: "2025-26",
    effectiveDate: "2025-07-01",
    active: true,
    versions: [
      {
        version: 1,
        fileName: "fee-structure-2025-26-scan.pdf",
        fileKind: "pdf",
        sizeBytes: 2_480_000,
        uploadedAt: "2025-06-20T10:00:00Z",
        stage: "indexed",
        ocrRequired: true,
      },
    ],
  },
  {
    id: "doc-calendar",
    title: "Academic Calendar 2025-26",
    category: "Academic calendar",
    academicYear: "2025-26",
    effectiveDate: "2025-07-15",
    active: true,
    versions: [
      {
        version: 1,
        fileName: "academic-calendar-2025-26.docx",
        fileKind: "docx",
        sizeBytes: 164_000,
        uploadedAt: "2025-06-02T09:30:00Z",
        stage: "indexed",
        ocrRequired: false,
      },
      {
        version: 2,
        fileName: "academic-calendar-2025-26-revised.docx",
        fileKind: "docx",
        sizeBytes: 171_000,
        uploadedAt: "2025-07-10T14:15:00Z",
        stage: "indexed",
        ocrRequired: false,
      },
    ],
  },
  {
    id: "doc-exams",
    title: "Semester 5 Exam Timetable",
    category: "Examinations",
    semester: "Semester 5",
    academicYear: "2025-26",
    active: true,
    versions: [
      {
        version: 1,
        fileName: "sem5-exam-timetable-scan.pdf",
        fileKind: "pdf",
        sizeBytes: 3_900_000,
        uploadedAt: "2025-10-02T08:00:00Z",
        stage: "failed",
        failedAt: "ocr",
        error: "OCR could not read page 3 (image too blurry). Upload a clearer scan or reprocess.",
        ocrRequired: true,
      },
    ],
  },
  {
    id: "doc-campus",
    title: "Campus Information",
    category: "Campus & facilities",
    active: true,
    versions: [
      {
        version: 1,
        fileName: "campus-information.txt",
        fileKind: "txt",
        sizeBytes: 18_400,
        uploadedAt: "2025-05-12T11:00:00Z",
        stage: "indexed",
        ocrRequired: false,
      },
    ],
  },
  {
    id: "doc-hostel",
    title: "Hostel Rules 2024-25",
    category: "Policies & rules",
    academicYear: "2024-25",
    active: false,
    versions: [
      {
        version: 1,
        fileName: "hostel-rules-2024-25.doc",
        fileKind: "doc",
        sizeBytes: 96_000,
        uploadedAt: "2024-07-01T10:00:00Z",
        stage: "indexed",
        ocrRequired: false,
      },
    ],
  },
];

const listeners = new Set<() => void>();

function setDocuments(next: AdminDocument[]) {
  documents = next;
  listeners.forEach((listener) => listener());
}

function updateCurrentVersion(id: string, patch: Partial<DocumentVersion>) {
  setDocuments(
    documents.map((doc) =>
      doc.id === id
        ? { ...doc, versions: [...doc.versions.slice(0, -1), { ...currentVersion(doc), ...patch }] }
        : doc,
    ),
  );
}

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function runPipeline(id: string, simulateFailure: boolean) {
  const doc = documents.find((d) => d.id === id);
  if (!doc) return;

  for (const stage of processingSteps(currentVersion(doc).ocrRequired).slice(1)) {
    await delay(STAGE_DELAY_MS);
    updateCurrentVersion(id, { stage });
    if (simulateFailure && stage === "embedding") {
      await delay(STAGE_DELAY_MS);
      updateCurrentVersion(id, {
        stage: "failed",
        failedAt: "embedding",
        error: "The embedding service did not respond. Try reprocessing.",
      });
      return;
    }
  }
}

/** For useSyncExternalStore. */
export function subscribeDocuments(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getDocuments(): AdminDocument[] {
  return documents;
}

export async function uploadDocument(upload: DocumentUpload): Promise<void> {
  await delay(UPLOAD_DELAY_MS);

  const fileKind = fileKindOf(upload.file.name);
  if (!fileKind) throw new Error("Unsupported file type.");

  const metadata = {
    title: upload.title,
    category: upload.category,
    semester: upload.semester,
    academicYear: upload.academicYear,
    effectiveDate: upload.effectiveDate,
  };
  const existing = upload.replacesId ? documents.find((d) => d.id === upload.replacesId) : undefined;
  const version: DocumentVersion = {
    version: existing ? currentVersion(existing).version + 1 : 1,
    fileName: upload.file.name,
    fileKind,
    sizeBytes: upload.file.size,
    uploadedAt: new Date().toISOString(),
    stage: "uploaded",
    ocrRequired: needsOcr(upload.file.name),
  };

  let id: string;
  if (existing) {
    id = existing.id;
    setDocuments(
      documents.map((d) => (d.id === id ? { ...d, ...metadata, active: true, versions: [...d.versions, version] } : d)),
    );
  } else {
    id = crypto.randomUUID();
    setDocuments([{ id, ...metadata, active: true, versions: [version] }, ...documents]);
  }

  void runPipeline(id, shouldFail(upload.file.name));
}

export function reprocessDocument(id: string) {
  updateCurrentVersion(id, { stage: "uploaded", failedAt: undefined, error: undefined });
  void runPipeline(id, false);
}

export function setDocumentActive(id: string, active: boolean) {
  setDocuments(documents.map((d) => (d.id === id ? { ...d, active } : d)));
}
