import { useSyncExternalStore } from "react";
import {
  getDocuments,
  reprocessDocument,
  setDocumentActive,
  subscribeDocuments,
  uploadDocument,
} from "../api/mockDocuments";
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

  return (
    <div className="admin-page">
      <AdminHeader username={session.username} onSwitchToStudent={onSwitchToStudent} />

      <main className="admin-main">
        <p className="admin-demo-note">
          Demo mode: uploads and processing are simulated in this browser and reset on reload. Put “scan” in a PDF
          file name to simulate scanned pages (OCR), or “fail” in any file name to simulate a processing failure.
        </p>

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
          <DocumentList documents={documents} onReprocess={reprocessDocument} onSetActive={setDocumentActive} />
        </section>
      </main>
    </div>
  );
}
