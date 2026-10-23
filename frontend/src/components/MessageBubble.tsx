import type { AnswerStatus, ChatMessage, ChatResponse } from "../types/chat";
import AnswerText from "./AnswerText";
import { PaperclipIcon } from "./Icons";

interface MessageBubbleProps {
  message: ChatMessage;
}

// Statuses worth flagging to the student. Plain successful and conversational
// replies show no badge.
const STATUS_BADGES: Partial<Record<AnswerStatus, { label: string; tone: "info" | "warning" | "error" | "muted" }>> = {
  partial: { label: "Partial answer", tone: "warning" },
  no_evidence: { label: "Not found in documents", tone: "muted" },
  degraded: { label: "Limited answer", tone: "warning" },
  failed: { label: "Couldn't answer", tone: "error" },
};

const RECOVERY_LABELS: Record<string, string> = {
  bm25_fallback: "keyword search",
  evidence_only: "source passages only",
  ocr_preprocess_retry: "image enhanced and re-read",
  vision_fallback: "image read by the vision model",
  cross_agent_text: "answered from your typed question",
  cross_agent_image: "answered from your screenshot",
};

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const response = message.response;

  return (
    <li className={`message message--${message.role}`}>
      <span className="visually-hidden">{isUser ? "You:" : "Assistant:"}</span>
      <div className={`message__bubble${message.error ? " message__bubble--error" : ""}`}>
        {response && <StatusBadge status={response.status} />}
        {isUser || !response ? (
          <p className="message__text">{message.text}</p>
        ) : (
          <AnswerText text={response.answer} sourceCount={response.sources.length} id={message.id} />
        )}

        {message.attachmentName && (
          <div className="message__attachment">
            {message.attachmentPreview && (
              <img className="message__thumb" src={message.attachmentPreview} alt="Attached screenshot" />
            )}
            <span>
              <PaperclipIcon size={14} />
              {message.attachmentName}
            </span>
          </div>
        )}

        {response && <ResponseDetails response={response} />}
      </div>
    </li>
  );
}

function StatusBadge({ status }: { status: AnswerStatus }) {
  const badge = STATUS_BADGES[status];
  if (!badge) return null;
  return <span className={`answer-badge answer-badge--${badge.tone}`}>{badge.label}</span>;
}

function ResponseDetails({ response }: { response: ChatResponse }) {
  const { sources, warnings, recovery, tasks } = response;
  const recoveryMethods = (recovery.method ?? "")
    .split(", ")
    .map((m) => RECOVERY_LABELS[m])
    .filter(Boolean);

  return (
    <>
      {warnings.length > 0 && (
        <ul className="answer-warnings">
          {warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}

      {tasks.total > 1 && (
        <p className="answer-meta">
          Answered {tasks.completed} of {tasks.total} parts of your question.
        </p>
      )}
      {recovery.attempted && recoveryMethods.length > 0 && (
        <p className="answer-meta">
          {recovery.status === "recovered" ? "Recovered using " : "Tried "}
          {recoveryMethods.join(", ")}.
        </p>
      )}

      {sources.length > 0 && (
        <details className="sources">
          <summary>
            {sources.length} {sources.length === 1 ? "source" : "sources"}
          </summary>
          <ol className="sources__list">
            {sources.map((s, i) => (
              <li key={`${s.docId}-${s.page}-${i}`} className="sources__item">
                <span className="sources__title">
                  {s.title || s.filename} · page {s.page}
                </span>
                <span className="sources__file">{s.filename}</span>
                {s.snippet && <q className="sources__snippet">{s.snippet}</q>}
              </li>
            ))}
          </ol>
        </details>
      )}
    </>
  );
}
