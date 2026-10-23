import type { AdminDocument } from "../../types/documents";
import { currentVersion, FILE_KIND_LABELS, formatBytes, formatDate, isProcessing } from "../../utils/documents";
import ProcessingStages from "./ProcessingStages";

interface DocumentListProps {
  documents: AdminDocument[];
  onReprocess: (id: string) => void;
  onSetActive: (id: string, active: boolean) => void;
}

export default function DocumentList({ documents, onReprocess, onSetActive }: DocumentListProps) {
  if (documents.length === 0) {
    return <p className="admin-empty">No documents uploaded yet.</p>;
  }
  return (
    <ul className="doc-list">
      {documents.map((doc) => (
        <DocumentItem key={doc.id} doc={doc} onReprocess={onReprocess} onSetActive={onSetActive} />
      ))}
    </ul>
  );
}

interface DocumentItemProps {
  doc: AdminDocument;
  onReprocess: (id: string) => void;
  onSetActive: (id: string, active: boolean) => void;
}

function DocumentItem({ doc, onReprocess, onSetActive }: DocumentItemProps) {
  const version = currentVersion(doc);
  const busy = isProcessing(version);
  const status = statusOf(doc);

  const meta = [
    doc.category,
    doc.semester,
    doc.academicYear && `AY ${doc.academicYear}`,
    doc.effectiveDate && `Effective ${formatDate(doc.effectiveDate)}`,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <li className={`doc-item${doc.active ? "" : " doc-item--inactive"}`}>
      <div className="doc-item__head">
        <div className="doc-item__info">
          <h3 className="doc-item__title">{doc.title}</h3>
          <p className="doc-item__meta">{meta}</p>
          <p className="doc-item__file">
            <span className="file-tag">{FILE_KIND_LABELS[version.fileKind]}</span>
            {version.fileName} · {formatBytes(version.sizeBytes)} · v{version.version}
            {version.ocrRequired && " · scanned pages (OCR)"}
          </p>
        </div>
        <span className={`badge badge--${status.tone}`}>{status.label}</span>
      </div>

      <ProcessingStages version={version} />
      {version.stage === "failed" && version.error && <p className="doc-item__error">{version.error}</p>}

      <div className="doc-item__footer">
        <details className="doc-item__versions">
          <summary>Versions ({doc.versions.length})</summary>
          <ol>
            {[...doc.versions].reverse().map((v) => (
              <li key={v.version}>
                v{v.version} · {v.fileName} · uploaded {formatDate(v.uploadedAt)}
                {v === version ? " · current" : " · superseded"}
              </li>
            ))}
          </ol>
        </details>
        <div className="doc-item__actions">
          <button type="button" className="button button--secondary" onClick={() => onReprocess(doc.id)} disabled={busy}>
            Reprocess
          </button>
          <button
            type="button"
            className="button button--secondary"
            onClick={() => onSetActive(doc.id, !doc.active)}
            disabled={busy}
          >
            {doc.active ? "Deactivate" : "Activate"}
          </button>
        </div>
      </div>
    </li>
  );
}

function statusOf(doc: AdminDocument): { label: string; tone: "success" | "error" | "info" | "muted" } {
  const { stage } = currentVersion(doc);
  if (stage === "failed") return { label: "Failed", tone: "error" };
  if (stage !== "indexed") return { label: "Processing", tone: "info" };
  if (!doc.active) return { label: "Inactive", tone: "muted" };
  return { label: "Indexed", tone: "success" };
}
