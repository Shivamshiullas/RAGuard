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
  const variantStyles = {
    default: {
      card: 'border-slate-200/90 bg-white hover:border-slate-300',
      iconBox: 'bg-slate-100 text-slate-700',
      valueText: 'text-slate-900',
      titleText: 'text-slate-600',
      highlightBar: 'bg-slate-800',
    },
    rose: {
      card: 'border-rose-200/80 bg-gradient-to-br from-white via-rose-50/20 to-white hover:border-rose-300',
      iconBox: 'bg-rose-100/80 text-rose-700',
      valueText: 'text-rose-700',
      titleText: 'text-rose-700',
      highlightBar: 'bg-rose-600',
    },
    amber: {
      card: 'border-amber-200/80 bg-gradient-to-br from-white via-amber-50/20 to-white hover:border-amber-300',
      iconBox: 'bg-amber-100/80 text-amber-700',
      valueText: 'text-amber-700',
      titleText: 'text-amber-700',
      highlightBar: 'bg-amber-500',
    },
    emerald: {
      card: 'border-emerald-200/80 bg-gradient-to-br from-white via-emerald-50/20 to-white hover:border-emerald-300',
      iconBox: 'bg-emerald-100/80 text-emerald-700',
      valueText: 'text-emerald-700',
      titleText: 'text-emerald-700',
      highlightBar: 'bg-emerald-600',
    },
    blue: {
      card: 'border-blue-200/80 bg-gradient-to-br from-white via-blue-50/20 to-white hover:border-blue-300',
      iconBox: 'bg-blue-100/80 text-blue-700',
      valueText: 'text-blue-900',
      titleText: 'text-blue-800',
      highlightBar: 'bg-blue-600',
    },
  }[variant];

  return (
    <div
      onClick={onClick}
      className={`group relative overflow-hidden rounded-xl border p-5 shadow-xs transition-all duration-200 ${
        onClick ? 'cursor-pointer hover:-translate-y-0.5 hover:shadow-md' : ''
      } ${variantStyles.card} ${className}`}
    >
      <div className={`absolute top-0 left-0 right-0 h-1 ${variantStyles.highlightBar}`} />

      <div className="flex items-start justify-between">
        <div className="space-y-1">
          <p className={`text-xs font-semibold tracking-wider uppercase ${variantStyles.titleText}`}>
            {title}
          </p>
          <div className="flex items-baseline gap-2">
            <span className={`font-display text-3xl font-extrabold tracking-tight ${variantStyles.valueText}`}>
              {value}
            </span>
          </div>
          {subtitle && (
            <p className="text-xs text-slate-600">{subtitle}</p>
          )}
        </div>

        {Icon && (
          <div className={`flex h-10 w-10 items-center justify-center rounded-lg transition-transform group-hover:scale-105 ${variantStyles.iconBox}`}>
            <Icon className="h-5 w-5" />
          </div>
        )}
      </div>

      {trend && (
        <div className="mt-3 flex items-center gap-1.5 pt-3 border-t border-slate-100 text-xs text-slate-500">
          <span
            className={`font-semibold ${
              trend.isPositive ? 'text-emerald-600' : 'text-rose-600'
            }`}
          >
            {trend.value}
          </span>
          <span>{trend.label}</span>
        </div>
      )}
    </div>
  );
};
