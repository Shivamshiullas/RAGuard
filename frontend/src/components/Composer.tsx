import { useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { branding } from "../config/branding";
import type { OutgoingMessage } from "../types/chat";
import { PaperclipIcon, SendIcon } from "./Icons";

interface ComposerProps {
  onSend: (message: OutgoingMessage) => void;
  disabled?: boolean;
}

// Phase 1: basic attach control only. Preview and file validation come in Phase 3.
export default function Composer({ onSend, disabled }: ComposerProps) {
  const [text, setText] = useState("");
  const [attachment, setAttachment] = useState<File | undefined>();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const canSend = !disabled && text.trim().length > 0;

  function clearAttachment() {
    setAttachment(undefined);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function submit() {
    if (!canSend) return;
    onSend({ text: text.trim(), attachment });
    setText("");
    clearAttachment();
    textareaRef.current?.focus();
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    submit();
  }

  // Enter sends; Shift+Enter inserts a new line.
  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <form className="composer" onSubmit={handleSubmit}>
      {attachment && (
        <div className="composer__attachment">
          <PaperclipIcon size={14} />
          <span className="composer__attachment-name">{attachment.name}</span>
          <button
            type="button"
            className="composer__attachment-remove"
            onClick={clearAttachment}
            aria-label={`Remove attachment ${attachment.name}`}
          >
            ×
          </button>
        </div>
      )}

      <div className="composer__row">
        <input
          ref={fileInputRef}
          type="file"
          accept="image/png,image/jpeg"
          className="visually-hidden"
          tabIndex={-1}
          aria-hidden="true"
          onChange={(e) => setAttachment(e.target.files?.[0])}
        />
        <button
          type="button"
          className="icon-button"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled}
          aria-label="Attach a screenshot"
          title="Attach a screenshot"
        >
          <PaperclipIcon />
        </button>

        <label htmlFor="composer-input" className="visually-hidden">
          Type your question
        </label>
        <textarea
          ref={textareaRef}
          id="composer-input"
          className="composer__input"
          rows={1}
          placeholder="Ask a question about the college…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          aria-describedby="composer-hint"
        />

        <button type="submit" className="send-button" disabled={!canSend}>
          <SendIcon />
          <span className="send-button__label">Send</span>
        </button>
      </div>

      <p id="composer-hint" className="composer__hint">
        {branding.attachmentHint}. Press Enter to send, Shift+Enter for a new line.
      </p>
    </form>
  );
}
