# College Assistant Frontend

A chatbot screen for students plus a separate admin area for managing documents, built with React, Vite and TypeScript for the college website.

**Everything uses mock data.** Nothing connects to a backend yet: chat replies are sample text, admin sign-in accepts any username and password, and document uploads and processing are simulated in the browser (reset on reload).

## Requirements

- Node.js 20 or newer (check with `node -v`)
- npm (comes with Node.js)

## Run it (Windows PowerShell / VS Code terminal)

Open the VS Code terminal with **Ctrl+`** and run these commands from the repository root:

```powershell
cd frontend
npm install
npm run dev
```

Then open http://localhost:5173 in your browser. Press **Ctrl+C** in the terminal to stop the server.

Other commands:

```powershell
npm run typecheck   # TypeScript check only
npm run build       # type-check and build a production bundle into dist/
npm run preview     # serve the built bundle at http://localhost:4173
```

## Change the branding

Edit `src/config/branding.ts` to set the college name, logo, welcome text, example questions and attachment hint. To use a real logo, put the file in `public/` (for example `public/logo.svg`) and set `logoUrl: "/logo.svg"`.

Colours, spacing and fonts are CSS variables in `src/styles/tokens.css`.

## Demo profiles: student and admin

- The app opens as a **student** on the chat screen.
- Click **Admin sign in** (top right) to open the admin login. In demo mode any username and password works.
- In the admin area, **Switch to student** signs out and returns to the chat.

The admin session is kept in memory only. Reloading the page returns to the student view.

## Admin document management

- Upload **PDF, DOC, DOCX or TXT** files up to 25 MB with title, category, semester, academic year and effective date.
- Choose **Upload as → New version of …** to add a new version of an existing document; the form is pre-filled from it.
- Each document shows its processing stages: Uploaded → Extracting text & images → OCR (only for scanned pages) → Embedding → Indexed, or Failed with a reason.
- **Reprocess** re-runs processing, **Deactivate/Activate** hides or restores a document, and **Versions** lists earlier versions.

Demo-only rules so every path can be shown on demand:

| File name contains | Simulated result |
|---|---|
| `scan` (PDF only) | Scanned pages detected, OCR stage runs |
| `fail` (any type) | Fails at the embedding stage; Reprocess then succeeds |

## Project structure

```
src/
  app/App.tsx                 app shell; switches between chat, admin login and admin views
  pages/
    ChatPage.tsx              student chat screen and conversation state
    AdminLoginPage.tsx        mock admin sign-in
    AdminDocumentsPage.tsx    upload form and document list
  components/
    ChatHeader.tsx            logo, college name, title, Admin sign in link
    BrandLogo.tsx             replaceable logo or initials
    ExampleQuestions.tsx      clickable example question chips
    MessageList.tsx           conversation list and "Preparing answer…" state
    MessageBubble.tsx         one user or assistant message
    Composer.tsx              text box, attach button, send button
    Icons.tsx                 inline SVG icons
    admin/
      AdminHeader.tsx         admin header with Switch to student
      UploadForm.tsx          document upload form with file validation
      DocumentList.tsx        documents, status, actions, version history
      ProcessingStages.tsx    processing pipeline display
  api/
    mockChat.ts               mock chat replies
    mockAuth.ts               mock admin sign-in
    mockDocuments.ts          in-memory document store and simulated processing
  types/                      chat, documents, auth
  utils/documents.ts          file validation, stage order, formatting
  config/branding.ts          replaceable college branding and copy
  styles/                     tokens.css, global.css, components.css, admin.css
```

## Manual test checklist

1. The page opens on the chat screen with the header, welcome message and three example questions.
2. Clicking an example question sends it, shows "Preparing answer…", then a demo reply.
3. Typing a question and pressing **Enter** sends it; **Shift+Enter** adds a new line.
4. The Send button is disabled while the box is empty and while a reply is loading.
5. The paperclip button opens a file picker for PNG or JPG images. The chosen file name appears above the text box, × removes it, and the name is shown on the sent message.
6. Keyboard only: **Tab** moves through the chips, attach button, text box and Send button, each with a visible focus outline.
7. Narrow the browser (or use DevTools device mode, **Ctrl+Shift+M**) to phone width: nothing scrolls sideways and the Send button becomes an icon.

Admin area:

8. Click **Admin sign in**, enter any username and password, and sign in. The Document management page opens with five sample documents (one failed, one inactive).
9. Choose a `.png` or other unsupported file: an error appears and the upload is blocked.
10. Upload a PDF named like `timetable-scan.pdf`: it appears at the top and moves through Uploaded → Extracting → OCR → Embedding → Indexed.
11. Upload a `.docx` or `.txt`: same, without the OCR stage.
12. Choose **Upload as → New version of: Campus Information** and upload a file named like `notes-fail.txt`: it fails at Embedding; **Versions (2)** lists v2 and v1. Click **Reprocess** and it reaches Indexed.
13. Click **Deactivate** / **Activate** on a document and check the badge changes.
14. Click **Switch to student**: you are back on the chat screen as a student.

## Coming in later phases

- Phase 2: answer status, source citations, warnings, error states
- Phase 3: screenshot preview, validation and upload progress
- Phase 5: real backend connection via `VITE_API_BASE_URL`; the backend enforces admin authorization
