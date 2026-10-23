import { useEffect, useRef, useState, type ChangeEvent, type FormEvent, type KeyboardEvent } from "react";
import { branding } from "../config/branding";
import type { OutgoingMessage } from "../types/chat";
import { validateScreenshot } from "../utils/documents";
import { PaperclipIcon, SendIcon } from "./Icons";

interface ComposerProps {
  onSend: (message: OutgoingMessage) => void;
  disabled?: boolean;
}

// Text box with an optional screenshot. A screenshot alone can be sent; the
// assistant then explains it using the college documents.
export default function Composer({ onSend, disabled }: ComposerProps) {
  const [text, setText] = useState("");
  const [attachment, setAttachment] = useState<File | undefined>();
  const [preview, setPreview] = useState<string | undefined>();
  const [attachError, setAttachError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const canSend = !disabled && (text.trim().length > 0 || Boolean(attachment));

  useEffect(() => {
    if (!attachment) {
      setPreview(undefined);
      return;
    }
    const url = URL.createObjectURL(attachment);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [attachment]);

  function clearAttachment() {
    setAttachment(undefined);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const error = validateScreenshot(file);
    setAttachError(error);
    if (error) {
      clearAttachment();
      return;
    }
    setAttachment(file);
  }

  function submit() {
    if (!canSend) return;
    onSend({ text: text.trim(), attachment });
    setText("");
    clearAttachment();
    setAttachError(null);
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
      {attachError && (
        <p className="composer__error" role="alert">
          {attachError}
        </p>
      )}
      {attachment && (
        <div className="composer__attachment">
          {preview ? <img className="composer__thumb" src={preview} alt="" /> : <PaperclipIcon size={14} />}
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
          onChange={handleFileChange}
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
