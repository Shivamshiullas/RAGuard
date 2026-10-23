import { branding } from "../config/branding";
import BrandLogo from "./BrandLogo";

interface ChatHeaderProps {
  onAdminSignIn: () => void;
}

export default function ChatHeader({ onAdminSignIn }: ChatHeaderProps) {
  return (
    <header className="chat-header">
      <div className="chat-header__inner">
        <BrandLogo />
        <div>
          <p className="chat-header__college">{branding.collegeName}</p>
          <h1 className="chat-header__title">{branding.assistantTitle}</h1>
          <p className="chat-header__subtitle">{branding.subtitle}</p>
        </div>
        <div className="profile-switch">
          <span className="profile-pill">Student</span>
          <button type="button" className="link-button" onClick={onAdminSignIn}>
            Admin sign in
          </button>
        </div>
      </div>
    </header>
  );
}
