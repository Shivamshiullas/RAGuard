import type { ReactNode } from "react";

// Renders the small subset of Markdown the assistant uses (paragraphs, bullet
// lists, **bold**) plus [n] citation markers. Builds React elements only;
// never injects HTML.

interface AnswerTextProps {
  text: string;
  /** Number of sources; markers outside 1..sourceCount are shown as plain text. */
  sourceCount: number;
  /** Stable prefix for element keys. */
  id: string;
}

const INLINE = /(\*\*[^*]+\*\*|\[\d+\])/g;
const BULLET = /^\s*(?:[-*•]|\d+[.)])\s+/;

function inline(text: string, sourceCount: number, keyPrefix: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    const key = `${keyPrefix}-${i}`;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }
    const cite = /^\[(\d+)\]$/.exec(part);
    if (cite && Number(cite[1]) >= 1 && Number(cite[1]) <= sourceCount) {
      return (
        <sup key={key} className="citation" title={`Source ${cite[1]}`}>
          <span className="visually-hidden">source </span>
          {cite[1]}
        </sup>
      );
    }
    return part;
  });
}

export default function AnswerText({ text, sourceCount, id }: AnswerTextProps) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  let ordered = false;

  const flushList = () => {
    if (list.length === 0) return;
    const items = list.map((item, i) => <li key={i}>{inline(item, sourceCount, `${id}-l${blocks.length}-${i}`)}</li>);
    blocks.push(ordered ? <ol key={blocks.length}>{items}</ol> : <ul key={blocks.length}>{items}</ul>);
    list = [];
  };

  for (const paragraph of text.split(/\n{2,}/)) {
    const lines = paragraph.split("\n");
    let prose: string[] = [];
    const flushProse = () => {
      if (prose.length === 0) return;
      blocks.push(<p key={blocks.length}>{inline(prose.join("\n"), sourceCount, `${id}-p${blocks.length}`)}</p>);
      prose = [];
    };
    for (const line of lines) {
      if (BULLET.test(line)) {
        flushProse();
        if (list.length === 0) ordered = /^\s*\d/.test(line);
        list.push(line.replace(BULLET, ""));
      } else {
        flushList();
        prose.push(line);
      }
    }
    flushProse();
    flushList();
  }

  return <div className="answer-text">{blocks}</div>;
}
