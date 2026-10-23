import React from 'react';
import { Database, FlaskConical, Ban } from 'lucide-react';
import type { PredictionStatus } from '../../types';

/** Persistent "Illustrative Data" label for synthetic figures. */
export const IllustrativeBadge: React.FC<{ text?: string }> = ({ text = 'Illustrative Data' }) => (
  <span className="inline-flex items-center gap-1 text-[11px] text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded-md font-medium">
    <Database className="h-3 w-3" />
    {text}
  </span>
);

export const PredictionChip: React.FC<{ status: PredictionStatus; className?: string }> = ({ status, className = '' }) => {
  const config = {
    NOT_READY: { cls: 'bg-slate-100 text-slate-700 border-slate-300', icon: Ban, label: 'Prediction: NOT READY' },
    DEMO_ONLY: { cls: 'bg-amber-50 text-amber-800 border-amber-200', icon: FlaskConical, label: 'Prediction: DEMO ONLY' },
    READY: { cls: 'bg-emerald-50 text-emerald-800 border-emerald-200', icon: FlaskConical, label: 'Prediction: READY' },
  }[status];
  const Icon = config.icon;
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] font-semibold border px-2 py-0.5 rounded-md ${config.cls} ${className}`}>
      <Icon className="h-3 w-3" />
      {config.label}
    </span>
  );
};

export const FieldStatusChip: React.FC<{ status?: string }> = ({ status }) => {
  if (!status || status === 'KNOWN') return null;
  const cls = {
    CONFLICT: 'bg-rose-100 text-rose-800 border-rose-200',
    UNVERIFIED: 'bg-amber-50 text-amber-800 border-amber-200',
    UNKNOWN: 'bg-slate-100 text-slate-600 border-slate-200',
  }[status] ?? 'bg-slate-100 text-slate-600 border-slate-200';
  return <span className={`text-[10px] font-bold uppercase border px-1.5 py-0.5 rounded ${cls}`}>{status}</span>;
};
