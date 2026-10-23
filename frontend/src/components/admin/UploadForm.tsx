import { useId, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import type { AdminDocument, DocumentUpload } from "../../types/documents";
import {
  ACCEPTED_FILE_TYPES,
  DOCUMENT_CATEGORIES,
  MAX_UPLOAD_MB,
  SEMESTERS,
  validateUploadFile,
} from "../../utils/documents";

interface UploadFormProps {
  documents: AdminDocument[];
  onUpload: (upload: DocumentUpload) => Promise<void>;
}

type Status = { kind: "idle" } | { kind: "uploading" } | { kind: "success" | "error"; message: string };

export default function UploadForm({ documents, onUpload }: UploadFormProps) {
  const id = useId();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [replacesId, setReplacesId] = useState("");
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState(DOCUMENT_CATEGORIES[0]);
  const [semester, setSemester] = useState("");
  const [academicYear, setAcademicYear] = useState("");
  const [effectiveDate, setEffectiveDate] = useState("");
  const [file, setFile] = useState<File | undefined>();
  const [fileError, setFileError] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  const uploading = status.kind === "uploading";

  // Uploading a new version pre-fills the form from the existing document.
  function handleReplacesChange(value: string) {
    setReplacesId(value);
    const doc = documents.find((d) => d.id === value);
    if (doc) {
      setTitle(doc.title);
      setCategory(doc.category);
      setSemester(doc.semester ?? "");
      setAcademicYear(doc.academicYear ?? "");
      setEffectiveDate(doc.effectiveDate ?? "");
    }
  }

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const selected = e.target.files?.[0];
    setFile(selected);
    setFileError(selected ? validateUploadFile(selected) : null);
  }

  function reset() {
    setReplacesId("");
    setTitle("");
    setCategory(DOCUMENT_CATEGORIES[0]);
    setSemester("");
    setAcademicYear("");
    setEffectiveDate("");
    setFile(undefined);
    setFileError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!file) {
      setFileError("Choose a file to upload.");
      return;
    }
    const error = validateUploadFile(file);
    if (error) {
      setFileError(error);
      return;
    }

    const uploadedTitle = title.trim();
    if (!uploadedTitle) {
      setStatus({ kind: "error", message: "Enter a title." });
      return;
    }
    setStatus({ kind: "uploading" });
    try {
      await onUpload({
        title: uploadedTitle,
        category,
        semester: semester || undefined,
        academicYear: academicYear.trim() || undefined,
        effectiveDate: effectiveDate || undefined,
        file,
        replacesId: replacesId || undefined,
      });
      reset();
      setStatus({ kind: "success", message: `Uploaded "${uploadedTitle}". Processing has started below.` });
    } catch (err) {
      setStatus({ kind: "error", message: err instanceof Error ? err.message : "Upload failed. Try again." });
    }
  }

  return (
    <form className="upload-form" onSubmit={handleSubmit}>
      <div className="field field--wide">
        <label className="field__label" htmlFor={`${id}-replaces`}>
          Upload as
        </label>
        <select
          id={`${id}-replaces`}
          className="input"
          value={replacesId}
          onChange={(e) => handleReplacesChange(e.target.value)}
        >
          <option value="">New document</option>
          {documents.map((d) => (
            <option key={d.id} value={d.id}>
              New version of: {d.title}
            </option>
          ))}
        </select>
      </div>

      <div className="field field--wide">
        <label className="field__label" htmlFor={`${id}-title`}>
          Title <span aria-hidden="true">*</span>
        </label>
        <input
          id={`${id}-title`}
          className="input"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g. Fee Structure 2025-26"
          required
        />
      </div>

      <div className="field">
        <label className="field__label" htmlFor={`${id}-category`}>
          Category <span aria-hidden="true">*</span>
        </label>
        <select id={`${id}-category`} className="input" value={category} onChange={(e) => setCategory(e.target.value)}>
          {DOCUMENT_CATEGORIES.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
      </div>

      <div className="field">
        <label className="field__label" htmlFor={`${id}-semester`}>
          Semester
        </label>
        <select id={`${id}-semester`} className="input" value={semester} onChange={(e) => setSemester(e.target.value)}>
          <option value="">Not specific</option>
          {SEMESTERS.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </div>

      <div className="field">
        <label className="field__label" htmlFor={`${id}-year`}>
          Academic year
        </label>
        <input
          id={`${id}-year`}
          className="input"
          value={academicYear}
          onChange={(e) => setAcademicYear(e.target.value)}
          placeholder="e.g. 2025-26"
        />
      </div>

      <div className="field">
        <label className="field__label" htmlFor={`${id}-date`}>
          Effective date
        </label>
        <input
          id={`${id}-date`}
          type="date"
          className="input"
          value={effectiveDate}
          onChange={(e) => setEffectiveDate(e.target.value)}
        />
      </div>

      <div className="field field--wide">
        <label className="field__label" htmlFor={`${id}-file`}>
          File <span aria-hidden="true">*</span>
        </label>
        <input
          ref={fileInputRef}
          id={`${id}-file`}
          type="file"
          className="input input--file"
          accept={ACCEPTED_FILE_TYPES}
          onChange={handleFileChange}
          aria-describedby={`${id}-file-hint${fileError ? ` ${id}-file-error` : ""}`}
          aria-invalid={Boolean(fileError)}
        />
        <p id={`${id}-file-hint`} className="field__hint">
          PDF, DOC, DOCX or TXT, up to {MAX_UPLOAD_MB} MB. PDFs can contain images and scanned pages; scanned
          pages are read with OCR.
        </p>
        {fileError && (
          <p id={`${id}-file-error`} className="field__error" role="alert">
            {fileError}
          </p>
        )}
      </div>

      <div className="upload-form__submit field--wide">
        <button type="submit" className="button button--primary" disabled={uploading}>
          {uploading ? "Uploading…" : replacesId ? "Upload new version" : "Upload document"}
        </button>
        {status.kind === "success" && (
          <p className="form-message form-message--success" role="status">
            {status.message}
          </p>
        )}
        {status.kind === "error" && (
          <p className="form-message form-message--error" role="alert">
            {status.message}
          </p>
        )}
      </div>
    </form>
  );
}
