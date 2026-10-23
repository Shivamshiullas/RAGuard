import React from 'react';
import { RiskLevel } from '../../types';

interface RiskBadgeProps {
  level: RiskLevel;
  size?: 'sm' | 'md' | 'lg';
  showDot?: boolean;
}

export const RiskBadge: React.FC<RiskBadgeProps> = ({
  level,
  size = 'md',
  showDot = true,
}) => {
  const sizeClasses = {
    sm: 'text-xs px-2 py-0.5 font-medium',
    md: 'text-xs px-2.5 py-1 font-semibold',
    lg: 'text-sm px-3.5 py-1.5 font-bold tracking-wide',
  };

  const config = {
    HIGH: {
      bg: 'bg-rose-50 border-rose-200 text-rose-700',
      dot: 'bg-rose-500',
      glow: 'shadow-rose-100',
      label: 'HIGH RISK',
    },
    MEDIUM: {
      bg: 'bg-amber-50 border-amber-200 text-amber-700',
      dot: 'bg-amber-500',
      glow: 'shadow-amber-100',
      label: 'MEDIUM RISK',
    },
    LOW: {
      bg: 'bg-emerald-50 border-emerald-200 text-emerald-700',
      dot: 'bg-emerald-500',
      glow: 'shadow-emerald-100',
      label: 'LOW RISK',
    },
    // No prediction exists: never shown as a risk level.
    UNRATED: {
      bg: 'bg-slate-100 border-slate-300 text-slate-600',
      dot: 'bg-slate-400',
      glow: 'shadow-slate-100',
      label: 'NOT RATED',
    },
  }[level];

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border shadow-xs ${config.bg} ${config.glow} ${sizeClasses[size]}`}
    >
      {showDot && (
        <span
          className={`h-2 w-2 rounded-full ${config.dot} ${
            level === 'HIGH' ? 'animate-pulse' : ''
          }`}
        />
      )}
      <span>{config.label}</span>
    </span>
  );
};
