# College Assistant Frontend (Phase 1)

A chatbot screen built with React, Vite and TypeScript for the college website.

**Phase 1 uses mock data only.** It does not connect to any backend, and every reply is sample text marked as demo mode.

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

## Project structure

```
src/
  app/App.tsx                 app shell (a router is added in Phase 4)
  pages/ChatPage.tsx          main chat screen and conversation state
  components/
    ChatHeader.tsx            logo, college name, title, subtitle
    ExampleQuestions.tsx      clickable example question chips
    MessageList.tsx           conversation list and "Preparing answer…" state
    MessageBubble.tsx         one user or assistant message
    Composer.tsx              text box, attach button, send button
    Icons.tsx                 inline SVG icons
  api/mockChat.ts             mock replies (replaced by a real API client in Phase 5)
  types/chat.ts               message types
  config/branding.ts          replaceable college branding and copy
  styles/                     tokens.css, global.css, components.css
```

## Manual test checklist

1. The page opens on the chat screen with the header, welcome message and three example questions.
2. Clicking an example question sends it, shows "Preparing answer…", then a demo reply.
3. Typing a question and pressing **Enter** sends it; **Shift+Enter** adds a new line.
4. The Send button is disabled while the box is empty and while a reply is loading.
5. The paperclip button opens a file picker for PNG or JPG images. The chosen file name appears above the text box, × removes it, and the name is shown on the sent message.
6. Keyboard only: **Tab** moves through the chips, attach button, text box and Send button, each with a visible focus outline.
7. Narrow the browser (or use DevTools device mode, **Ctrl+Shift+M**) to phone width: nothing scrolls sideways and the Send button becomes an icon.

## Coming in later phases

- Phase 2: answer status, source citations, warnings, error states
- Phase 3: screenshot preview, validation and upload progress
- Phase 4: separate admin login and document management
- Phase 5: real backend connection via `VITE_API_BASE_URL`
