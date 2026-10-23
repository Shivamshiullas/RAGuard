import { useState, useSyncExternalStore } from "react";
import {
  getDocuments,
  getDocumentsError,
  reprocessDocument,
  setDocumentActive,
  subscribeDocuments,
  uploadDocument,
} from "../api/documents";
import AdminHeader from "../components/admin/AdminHeader";
import DocumentList from "../components/admin/DocumentList";
import UploadForm from "../components/admin/UploadForm";
import type { AdminSession } from "../types/auth";

interface AdminDocumentsPageProps {
  session: AdminSession;
  onSwitchToStudent: () => void;
}

export default function AdminDocumentsPage({ session, onSwitchToStudent }: AdminDocumentsPageProps) {
  const documents = useSyncExternalStore(subscribeDocuments, getDocuments);
  const loadError = useSyncExternalStore(subscribeDocuments, getDocumentsError);
  const [actionError, setActionError] = useState<string | null>(null);

  function runAction(action: Promise<void>) {
    setActionError(null);
    action.catch((err) => setActionError(err instanceof Error ? err.message : "That action failed. Try again."));
  }

  const error = actionError ?? loadError;

  return (
    <div className="admin-page">
      <AdminHeader username={session.username} onSwitchToStudent={onSwitchToStudent} />

      <main className="admin-main">
        <section className="admin-section" aria-labelledby="upload-heading">
          <h2 id="upload-heading" className="admin-section__title">
            Upload a document
          </h2>
          <UploadForm documents={documents} onUpload={uploadDocument} />
        </section>

        <section className="admin-section" aria-labelledby="documents-heading">
          <h2 id="documents-heading" className="admin-section__title">
            Documents <span className="admin-count">{documents.length}</span>
          </h2>
          {error && (
            <p className="form-message form-message--error" role="alert">
              {error}
            </p>
          )}
          <DocumentList
            documents={documents}
            onReprocess={(id) => runAction(reprocessDocument(id))}
            onSetActive={(id, active) => runAction(setDocumentActive(id, active))}
          />
        </section>
      </main>
    </div>
  );
}
