# College Assistant Frontend

A chatbot screen for students plus a separate admin area for managing documents, built with React, Vite and TypeScript for the college website.

It talks to the FastAPI backend in `../backend` (see the root README). In development, Vite forwards `/api` requests to `http://127.0.0.1:8000`; set `VITE_API_BASE_URL` to call a backend on another origin.

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

Start the backend first (`python -m uvicorn college_rag.api:app --port 8000` in `backend/`), then open http://localhost:5173 in your browser. Press **Ctrl+C** in the terminal to stop the server.

Other commands:

```powershell
npm run typecheck   # TypeScript check only
npm run build       # type-check and build a production bundle into dist/
npm run preview     # serve the built bundle at http://localhost:4173
```

## Change the branding

Edit `src/config/branding.ts` to set the college name, logo, welcome text, example questions and attachment hint. To use a real logo, put the file in `public/` (for example `public/logo.svg`) and set `logoUrl: "/logo.svg"`.

Colours, spacing and fonts are CSS variables in `src/styles/tokens.css`.

## Student and admin profiles

- The app opens as a **student** on the chat screen. Answers show a status badge when relevant, numbered citations, warnings and a collapsible source list (document, page, snippet).
- A PNG/JPG screenshot (up to 5 MB) can be attached, with or without a typed question.
- **Admin sign in** uses the backend's `ADMIN_USERNAME` / `ADMIN_PASSWORD`. The session token is kept in memory only; reloading or **Switch to student** signs out.

## Admin document management

- Upload **PDF, DOCX, TXT, PNG or JPG** files up to 25 MB with title, category, semester, academic year and effective date.
- **Upload as → New version of …** adds a new version; the form is pre-filled. Exact duplicate files are rejected.
- Stages update live while processing: Uploaded → Extracting → OCR (scanned pages/images only) → Embedding → Indexed, or Failed with a reason.
- **Reprocess** re-runs processing, **Deactivate/Activate** removes or restores a document from answers, **Versions** lists earlier versions.

## Project structure

```
src/
  app/App.tsx                 app shell; switches between chat, admin login and admin views
  pages/
    ChatPage.tsx              student chat screen and conversation state
    AdminLoginPage.tsx        admin sign-in
    AdminDocumentsPage.tsx    upload form and document list
  components/
    ChatHeader.tsx            logo, college name, title, Admin sign in link
    BrandLogo.tsx             replaceable logo or initials
    ExampleQuestions.tsx      clickable example question chips
    MessageList.tsx           conversation list and "Preparing answer…" state
    MessageBubble.tsx         one message with status, warnings and sources
    AnswerText.tsx            safe rendering of answer text and [n] citations
    Composer.tsx              text box, attach button, send button
    Icons.tsx                 inline SVG icons
    admin/
      AdminHeader.tsx         admin header with Switch to student
      UploadForm.tsx          document upload form with file validation
      DocumentList.tsx        documents, status, actions, version history
      ProcessingStages.tsx    processing pipeline display
  api/
    client.ts                 fetch wrapper, auth token, error messages
    chat.ts                   POST /api/chat (text + optional screenshot)
    auth.ts                   admin sign-in
    documents.ts              document store backed by the API, polls while processing
  types/                      chat, documents, auth
  utils/documents.ts          file validation, stage order, formatting
  config/branding.ts          replaceable college branding and copy
  styles/                     tokens.css, global.css, components.css, admin.css
```

## Manual test checklist

With the backend running and the sample documents seeded:

1. Click **What is the Semester 5 fee?**: the answer cites *Fee Structure 2026-27, page 1*.
2. Type `hi`: an instant greeting with no sources.
3. Ask `What is the MBA programme fee?`: a *Not found in documents* badge; nothing is guessed.
4. Ask several questions at once (`What is the sem 5 fee? When are odd semester exams? Library hours?`): one answer with a section per question.
5. Attach a screenshot of a notice and ask about it.
6. Sign in as admin, upload a document, and watch it move through the stages to *Indexed*; then ask about it.
7. Deactivate a document and ask about it again: it is no longer used.
