import React from 'react';
import { Inbox } from 'lucide-react';

interface EmptyStateProps {
  title: string;
  message: string;
  action?: { label: string; onClick: () => void };
}

export const EmptyState: React.FC<EmptyStateProps> = ({ title, message, action }) => (
  <div className="bg-white p-10 rounded-xl border border-slate-200/90 shadow-sm text-center space-y-3">
    <div className="h-12 w-12 mx-auto rounded-xl bg-slate-100 text-slate-500 flex items-center justify-center">
      <Inbox className="h-6 w-6" />
    </div>
    <h2 className="font-display text-lg font-bold text-slate-900">{title}</h2>
    <p className="text-sm text-slate-500 max-w-lg mx-auto">{message}</p>
    {action && (
      <button
        onClick={action.onClick}
        className="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-xl text-xs font-bold"
      >
        {action.label}
      </button>
    )}
  </div>
);
