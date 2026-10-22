import { Fragment, useEffect, useState, type ReactNode } from "react";
import { getDigest } from "./api";

interface Props {
  runId: string;
  version: number; // bumped when the digest was rebuilt (coach pack / context saved)
}

const isUnknown = (text: string) => text.includes("UNKNOWN");

/** Inline markdown: `code` and **bold** only (as text nodes, never HTML). */
function inline(text: string): ReactNode {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
  return parts.map((p, i) =>
    p.startsWith("`") && p.endsWith("`") && p.length > 1 ? (
      <code key={i}>{p.slice(1, -1)}</code>
    ) : p.startsWith("**") && p.endsWith("**") && p.length > 3 ? (
      <strong key={i}>{p.slice(2, -2)}</strong>
    ) : (
      <Fragment key={i}>{p}</Fragment>
    ),
  );
}

const cells = (row: string) => row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

/** Tiny renderer for the digest's markdown subset: headings, bullet lists (nested by indent), tables, paragraphs. */
function renderMarkdown(md: string): ReactNode[] {
  const out: ReactNode[] = [];
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (!line.trim()) {
      i++;
    } else if (heading) {
      const level = heading[1].length;
      out.push(
        <div key={i} className={`md-h md-h${level}`} role="heading" aria-level={level + 2}>
          {inline(heading[2])}
        </div>,
      );
      i++;
    } else if (line.trim().startsWith("|")) {
      const rows: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(lines[i++]);
      const body = rows.filter((r, k) => !(k === 1 && /^[\s|:-]+$/.test(r)));
      const [head, ...rest] = body;
      out.push(
        <div key={i} className="md-table-wrap">
          <table className="md-table">
            <thead>
              <tr>
                {cells(head).map((c, k) => (
                  <th key={k}>{inline(c)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rest.map((r, k) => (
                <tr key={k} className={isUnknown(r) ? "md-unknown" : undefined}>
                  {cells(r).map((c, j) => (
                    <td key={j}>{inline(c)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
    } else if (/^\s*[-*]\s/.test(line)) {
      const items: { depth: number; text: string; key: number }[] = [];
      while (i < lines.length && /^\s*[-*]\s/.test(lines[i])) {
        const m = /^(\s*)[-*]\s+(.*)$/.exec(lines[i])!;
        items.push({ depth: Math.floor(m[1].length / 2), text: m[2], key: i });
        i++;
      }
      out.push(
        <ul key={i} className="md-list">
          {items.map((it) => (
            <li
              key={it.key}
              className={isUnknown(it.text) ? "md-unknown" : undefined}
              style={{ marginLeft: `${it.depth * 1.4}em` }}
            >
              {inline(it.text)}
            </li>
          ))}
        </ul>,
      );
    } else {
      out.push(
        <p key={i} className={`md-p ${isUnknown(line) ? "md-unknown" : ""}`}>
          {inline(line)}
        </p>,
      );
      i++;
    }
  }
  return out;
}

/** Collapsible view of runs/<id>/digest.md, with UNKNOWN lines highlighted. */
export default function Digest({ runId, version }: Props) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setText(null);
    setError(null);
  }, [runId, version]);

  useEffect(() => {
    if (!open || text != null) return;
    let alive = true;
    getDigest(runId)
      .then((d) => alive && setText(d.text))
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, [open, text, runId]);

  const unknowns = text ? text.split("\n").filter(isUnknown).length : 0;
  return (
    <details className="panel coach-box digest" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary className="coach-summary">
        Digest
        {text != null && (
          <span className="digest-count">
            {unknowns} UNKNOWN {unknowns === 1 ? "line" : "lines"}
          </span>
        )}
      </summary>
      {error && <p className="coach-error">{error}</p>}
      {open && text == null && !error && <p className="muted-dark">Loading…</p>}
      {text != null && <div className="md">{renderMarkdown(text)}</div>}
    </details>
  );
}
