import { branding } from "../../config/branding";
import BrandLogo from "../BrandLogo";

interface AdminHeaderProps {
  username: string;
  onSwitchToStudent: () => void;
}

export default function AdminHeader({ username, onSwitchToStudent }: AdminHeaderProps) {
  return (
    <header className="chat-header">
      <div className="chat-header__inner admin-header__inner">
        <BrandLogo />
        <div>
          <p className="chat-header__college">{branding.collegeName}</p>
          <h1 className="chat-header__title">Document management</h1>
          <p className="chat-header__subtitle">Admin area</p>
        </div>
        <div className="profile-switch">
          <span className="profile-pill profile-pill--admin">Admin: {username}</span>
          <button type="button" className="link-button" onClick={onSwitchToStudent}>
            Switch to student
          </button>
        </div>
      </div>
    </header>
  );
}
