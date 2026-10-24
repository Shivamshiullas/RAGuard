import React, { useEffect, useRef, useState } from 'react';
import { MessagesSquare, Send, Loader2, FileText, Info, AlertTriangle, RotateCcw } from 'lucide-react';
import { AcquisitionCase, PageView, ProjectInfo } from '../../types';
import { api, ApiChatAnswer, ApiChatCitation, ApiChatTurn } from '../../api/client';

interface ChatViewProps {
  project: ProjectInfo;
  cases: AcquisitionCase[];
  onNavigate: (page: PageView) => void;
}

type Message =
  | { id: number; role: 'user'; text: string }
  | { id: number; role: 'assistant'; reply: ApiChatAnswer }
  | { id: number; role: 'error'; text: string };

const STATUS_NOTE: Record<ApiChatAnswer['status'], { title: string; tone: string } | null> = {
  ANSWERED: null,
  EVIDENCE_ONLY: {
    title: 'No generated answer. Showing the most relevant passages instead.',
    tone: 'bg-amber-50 border-amber-200 text-amber-900',
  },
  INSUFFICIENT_EVIDENCE: {
    title: 'The indexed documents do not answer this question.',
    tone: 'bg-slate-50 border-slate-200 text-slate-700',
  },
};

const SUGGESTIONS = [
  'Which cases have a pending legal dispute?',
  'What compensation awards have been notified, and how much is disbursed?',
  'Which approvals or clearances are delayed?',
];

/** Renders answer text with [E1]-style labels as small inline markers. */
const AnswerText: React.FC<{ text: string }> = ({ text }) => (
  <p className="text-sm leading-relaxed text-slate-800 whitespace-pre-wrap">
    {text.split(/(\[E\d+\])/g).map((part, i) =>
      /^\[E\d+\]$/.test(part) ? (
        <span key={i} className="mx-0.5 inline-flex items-center rounded bg-blue-50 px-1 text-[10px] font-semibold text-blue-700 align-[1px]">
          {part.slice(1, -1)}
        </span>
      ) : (
        <React.Fragment key={i}>{part}</React.Fragment>
      ),
    )}
  </p>
);

const CitationChips: React.FC<{ citations: ApiChatCitation[]; expandFirst?: boolean }> = ({ citations, expandFirst }) => {
  const [open, setOpen] = useState<string | null>(expandFirst ? citations[0]?.label ?? null : null);
  if (!citations.length) return null;
  const active = citations.find((c) => c.label === open);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {citations.map((c) => (
          <button
            key={c.label}
            onClick={() => setOpen(open === c.label ? null : c.label)}
            aria-expanded={open === c.label}
            className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] transition-colors ${
              open === c.label ? 'border-blue-300 bg-blue-50 text-blue-800' : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
            }`}
          >
            <span className="font-semibold">{c.label}</span>
            <FileText className="h-3 w-3" />
            <span className="max-w-48 truncate">{c.document}</span>
            <span className="text-slate-400">p.{c.page}</span>
          </button>
        ))}
      </div>
      {active && (
        <blockquote className="rounded-md border-l-2 border-blue-400 bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-700">
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-slate-400">
            {active.label} · {active.document} · page {active.page}
          </div>
          {active.snippet}
        </blockquote>
      )}
    </div>
  );
};

const AssistantMessage: React.FC<{ reply: ApiChatAnswer }> = ({ reply }) => {
  const note = STATUS_NOTE[reply.status];
  return (
    <div className="space-y-3">
      {note && (
        <div className={`flex items-start gap-2 rounded-md border px-3 py-2 text-xs ${note.tone}`}>
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <div>
            <div className="font-semibold">{note.title}</div>
            {reply.note && <div className="mt-0.5 opacity-80">{reply.note}</div>}
          </div>
        </div>
      )}
      {reply.answer && <AnswerText text={reply.answer} />}
      <CitationChips citations={reply.citations} expandFirst={reply.status === 'EVIDENCE_ONLY'} />
    </div>
  );
};

export const ChatView: React.FC<ChatViewProps> = ({ project, cases }) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState('');
  const [caseId, setCaseId] = useState('');
  const [sending, setSending] = useState(false);
  const nextId = useRef(1);
  const endRef = useRef<HTMLDivElement>(null);

  const documentCases = cases.filter((c) => !c.isSynthetic);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, sending]);

  const history = (): ApiChatTurn[] =>
    messages
      .flatMap((m): ApiChatTurn[] => {
        if (m.role === 'user') return [{ role: 'user', content: m.text }];
        if (m.role === 'assistant') return [{ role: 'assistant', content: m.reply.answer ?? m.reply.note ?? '' }];
        return [];
      })
      .slice(-4);

  const send = async (text: string) => {
    const q = text.trim();
    if (!q || sending) return;
    const turns = history();
    setMessages((prev) => [...prev, { id: nextId.current++, role: 'user', text: q }]);
    setQuestion('');
    setSending(true);
    try {
      const reply = await api.chat(project.id, q, { caseId: caseId || null, history: turns });
      setMessages((prev) => [...prev, { id: nextId.current++, role: 'assistant', reply }]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { id: nextId.current++, role: 'error', text: err instanceof Error ? err.message : 'The question could not be sent.' },
      ]);
    } finally {
      setSending(false);
    }
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    void send(question);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void send(question);
    }
  };

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col gap-4">
      <div className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm md:flex-row md:items-end md:justify-between">
        <div>
          <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500 flex items-center gap-1.5">
            <MessagesSquare className="h-3.5 w-3.5" /> Document Q&amp;A
          </span>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-900">Ask the Documents</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Answers come only from this project's indexed documents, with a citation for every statement.
          </p>
        </div>
        <div className="flex items-end gap-2">
          <label className="text-xs text-slate-600">
            <span className="mb-1 block font-medium">Scope</span>
            <select
              value={caseId}
              onChange={(e) => setCaseId(e.target.value)}
              disabled={!documentCases.length}
              className="w-56 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[13px] text-slate-800 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 disabled:bg-slate-50 disabled:text-slate-400"
            >
              <option value="">All documents in this project</option>
              {documentCases.map((c) => (
                <option key={c.uid} value={c.uid}>
                  Case {c.id}
                  {c.villageName && !c.villageName.startsWith('Unknown') ? ` · ${c.villageName}` : ''}
                </option>
              ))}
            </select>
          </label>
          {messages.length > 0 && (
            <button
              onClick={() => setMessages([])}
              className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
            >
              <RotateCcw className="h-3.5 w-3.5" /> New conversation
            </button>
          )}
        </div>
      </div>

      {project.isDemo && (
        <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          The synthetic demo corridor has no source documents, so questions here will find no evidence. Select a project with uploaded
          documents to use the assistant.
        </div>
      )}

      <div className="flex-1 overflow-y-auto rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        {messages.length === 0 && !sending ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
            <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
              <MessagesSquare className="h-5 w-5" />
            </div>
            <div>
              <p className="text-sm font-semibold text-slate-900">Ask a question about this project's documents</p>
              <p className="mt-1 text-xs text-slate-500">Every answer cites the file and page it comes from.</p>
            </div>
            <div className="flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => void send(s)}
                  className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-5">
            {messages.map((m) =>
              m.role === 'user' ? (
                <div key={m.id} className="flex justify-end">
                  <div className="max-w-[75%] rounded-lg bg-slate-900 px-3.5 py-2 text-sm text-white whitespace-pre-wrap">{m.text}</div>
                </div>
              ) : m.role === 'assistant' ? (
                <div key={m.id} className="flex gap-3">
                  <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-blue-600 text-white">
                    <MessagesSquare className="h-3.5 w-3.5" />
                  </div>
                  <div className="min-w-0 max-w-[85%] flex-1">
                    <AssistantMessage reply={m.reply} />
                  </div>
                </div>
              ) : (
                <div key={m.id} role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
                  {m.text}
                </div>
              ),
            )}
            {sending && (
              <div className="flex items-center gap-2 text-xs text-slate-500" role="status">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Searching the documents…
              </div>
            )}
            <div ref={endRef} />
          </div>
        )}
      </div>

      <form onSubmit={onSubmit} className="flex items-end gap-2 rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={onKeyDown}
          maxLength={1000}
          rows={2}
          aria-label="Your question"
          placeholder="Ask about cases, awards, statuses, dates… (Enter to send, Shift+Enter for a new line)"
          className="flex-1 resize-none rounded-md border-0 px-2 py-1.5 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none"
        />
        <div className="flex flex-col items-end gap-1">
          <span className="text-[10px] text-slate-400 tabular-nums">{question.length}/1000</span>
          <button
            type="submit"
            disabled={!question.trim() || sending}
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:bg-slate-300"
          >
            {sending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
            Send
          </button>
        </div>
      </form>
    </div>
  );
};
