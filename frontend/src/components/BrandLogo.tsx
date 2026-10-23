import { branding } from "../config/branding";

export default function BrandLogo() {
  return branding.logoUrl ? (
    <img className="brand-logo" src={branding.logoUrl} alt={`${branding.collegeName} logo`} />
  ) : (
    <div className="brand-logo brand-logo--initials" aria-hidden="true">
      {branding.logoInitials}
    </div>
  );
}
