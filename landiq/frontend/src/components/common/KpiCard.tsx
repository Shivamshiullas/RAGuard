import React from 'react';
import { LucideIcon } from 'lucide-react';

interface KpiCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon?: LucideIcon;
  variant?: 'default' | 'rose' | 'amber' | 'emerald' | 'blue';
  trend?: {
    value: string;
    isPositive: boolean;
    label: string;
  };
  onClick?: () => void;
  className?: string;
}

const VARIANTS = {
  default: { iconBox: 'bg-slate-100 text-slate-600', accent: 'bg-slate-400' },
  rose: { iconBox: 'bg-rose-50 text-rose-600', accent: 'bg-rose-500' },
  amber: { iconBox: 'bg-amber-50 text-amber-600', accent: 'bg-amber-500' },
  emerald: { iconBox: 'bg-emerald-50 text-emerald-600', accent: 'bg-emerald-500' },
  blue: { iconBox: 'bg-blue-50 text-blue-600', accent: 'bg-blue-500' },
};

export const KpiCard: React.FC<KpiCardProps> = ({
  title,
  value,
  subtitle,
  icon: Icon,
  variant = 'default',
  trend,
  onClick,
  className = '',
}) => {
  const style = VARIANTS[variant];

  return (
    <div
      onClick={onClick}
      className={`rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition-colors ${
        onClick ? 'cursor-pointer hover:border-slate-300 hover:bg-slate-50/60' : ''
      } ${className}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1.5 min-w-0">
          <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500">
            <span className={`h-1.5 w-1.5 rounded-full ${style.accent}`} />
            {title}
          </p>
          <p className="text-3xl font-semibold tracking-tight text-slate-900 tabular-nums">{value}</p>
          {subtitle && <p className="text-xs text-slate-500">{subtitle}</p>}
        </div>

        {Icon && (
          <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${style.iconBox}`}>
            <Icon className="h-[18px] w-[18px]" />
          </div>
        )}
      </div>

      {trend && (
        <div className="mt-4 flex items-center gap-1.5 border-t border-slate-100 pt-3 text-xs text-slate-500">
          <span className={`font-semibold ${trend.isPositive ? 'text-emerald-600' : 'text-rose-600'}`}>{trend.value}</span>
          <span>{trend.label}</span>
        </div>
      )}
    </div>
  );
};
