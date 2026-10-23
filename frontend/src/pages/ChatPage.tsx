import { useState } from "react";
import { sendMessage } from "../api/chat";
import ChatHeader from "../components/ChatHeader";
import Composer from "../components/Composer";
import ExampleQuestions from "../components/ExampleQuestions";
import MessageList from "../components/MessageList";
import { branding } from "../config/branding";
import type { ChatMessage, OutgoingMessage } from "../types/chat";

interface ChatPageProps {
  onAdminSignIn: () => void;
}

export default function ChatPage({ onAdminSignIn }: ChatPageProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  async function handleSend(outgoing: OutgoingMessage) {
    setMessages((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        role: "user",
        text: outgoing.text,
        attachmentName: outgoing.attachment?.name,
        attachmentPreview: outgoing.attachment ? URL.createObjectURL(outgoing.attachment) : undefined,
      },
    ]);
    setIsLoading(true);

    try {
      const response = await sendMessage(outgoing);
      setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: "assistant", text: response.answer, response }]);
    } catch (err) {
      const text = err instanceof Error ? err.message : "Something went wrong. Please try again.";
      setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: "assistant", text, error: true }]);
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="chat-page">
      <ChatHeader onAdminSignIn={onAdminSignIn} />

      <main className="chat-main">
        <div className="chat-column">
          {messages.length === 0 ? (
            <section className="welcome" aria-labelledby="welcome-heading">
              <h2 id="welcome-heading" className="welcome__heading">
                {branding.welcomeHeading}
              </h2>
              <p className="welcome__text">{branding.welcomeText}</p>
              <p className="welcome__label">Try asking</p>
              <ExampleQuestions
                questions={branding.exampleQuestions}
                onSelect={(q) => handleSend({ text: q })}
                disabled={isLoading}
              />
            </section>
          ) : (
            <MessageList messages={messages} isLoading={isLoading} />
          )}
        </div>
      </main>

      <footer className="chat-footer">
        <div className="chat-column">
          <Composer onSend={handleSend} disabled={isLoading} />
          <p className="demo-note">Answers come from official college documents. Check the cited sources for important decisions.</p>
        </div>
      </footer>
    </div>
  );
}
