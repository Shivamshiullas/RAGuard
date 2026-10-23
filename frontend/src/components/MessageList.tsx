import { useEffect, useRef } from "react";
import type { ChatMessage } from "../types/chat";
import MessageBubble from "./MessageBubble";

interface MessageListProps {
  messages: ChatMessage[];
  isLoading: boolean;
}

export default function MessageList({ messages, isLoading }: MessageListProps) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages, isLoading]);

  return (
    <section className="message-list" aria-label="Conversation">
      <ol className="message-list__items" aria-live="polite">
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
        {isLoading && (
          <li className="message message--assistant">
            <div className="message__bubble message__bubble--pending">
              <p className="message__text">Preparing answer…</p>
            </div>
          </li>
        )}
      </ol>
      <div ref={endRef} />
    </section>
  );
}
