import { branding } from "../config/branding";

export default function ChatHeader() {
  return (
    <header className="chat-header">
      <div className="chat-header__inner">
        {branding.logoUrl ? (
          <img className="chat-header__logo" src={branding.logoUrl} alt={`${branding.collegeName} logo`} />
        ) : (
          <div className="chat-header__logo chat-header__logo--initials" aria-hidden="true">
            {branding.logoInitials}
          </div>
        )}
        <div>
          <p className="chat-header__college">{branding.collegeName}</p>
          <h1 className="chat-header__title">{branding.assistantTitle}</h1>
          <p className="chat-header__subtitle">{branding.subtitle}</p>
        </div>
      </div>
    </header>
  );
}
