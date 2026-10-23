import { useEffect, useState } from "react";
import { signOutAdmin } from "../api/auth";
import { setUnauthorizedHandler } from "../api/client";
import { clearDocuments } from "../api/documents";
import AdminDocumentsPage from "../pages/AdminDocumentsPage";
import AdminLoginPage from "../pages/AdminLoginPage";
import ChatPage from "../pages/ChatPage";
import type { AdminSession } from "../types/auth";

type View = "chat" | "adminLogin" | "adminDocuments";

// App shell. Views are switched with state; the admin session token lives in
// memory only and is cleared on reload or when switching back to the student profile.
export default function App() {
  const [view, setView] = useState<View>("chat");
  const [session, setSession] = useState<AdminSession | null>(null);

  // An expired admin session sends the admin back to the sign-in screen.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      signOutAdmin();
      clearDocuments();
      setSession(null);
      setView("adminLogin");
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  if (view === "adminDocuments" && session) {
    return (
      <AdminDocumentsPage
        session={session}
        onSwitchToStudent={() => {
          signOutAdmin();
          clearDocuments();
          setSession(null);
          setView("chat");
        }}
      />
    );
  }

  if (view === "adminLogin") {
    return (
      <AdminLoginPage
        onSignedIn={(s) => {
          setSession(s);
          setView("adminDocuments");
        }}
        onBack={() => setView("chat")}
      />
    );
  }

  return <ChatPage onAdminSignIn={() => setView("adminLogin")} />;
}
