import type { ChatMessage } from "../types/chat";
import { PaperclipIcon } from "./Icons";

interface MessageBubbleProps {
  message: ChatMessage;
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  return (
    <li className={`message message--${message.role}`}>
      <span className="visually-hidden">{isUser ? "You:" : "Assistant:"}</span>
      <div className="message__bubble">
        <p className="message__text">{message.text}</p>
        {message.attachmentName && (
          <p className="message__attachment">
            <PaperclipIcon size={14} />
            {message.attachmentName}
          </p>
        )}
      </div>
    </li>
  );
}
