import { useEffect, useState } from "react";
import { ApiError, coachPack, getContext, importTips, putContext } from "./api";
import type { Tip } from "./types";

interface Props {
  runId: string;
  onTipsImported: (tips: Tip[]) => void;
  onDigestChanged: () => void;
}

type Status = { tone: "ok" | "error"; lines: string[] } | null;

const errLines = (e: unknown) => (e instanceof ApiError ? e.errors : [String(e)]);

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // no clipboard API (insecure context): hidden textarea + execCommand
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    if (!ok) throw new Error("Clipboard unavailable - open runs/<id>/coach_prompt.md instead");
  }
}

function StatusLine({ status }: { status: Status }) {
  if (!status) return null;
  return (
    <div className={status.tone === "ok" ? "coach-ok" : "coach-error"} role="status">
      {status.lines.length === 1 ? (
        status.lines[0]
      ) : (
        <ul>
          {status.lines.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Manual LLM-coach loop: context.md editor -> copy coach prompt -> paste Claude's reply -> tips. */
export default function CoachPanel({ runId, onTipsImported, onDigestChanged }: Props) {
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [values, setValues] = useState<Record<string, string>>({});
  const [extra, setExtra] = useState("");
  const [dirty, setDirty] = useState(false);
  const [ctxStatus, setCtxStatus] = useState<Status>(null);
  const [packStatus, setPackStatus] = useState<Status>(null);
  const [reply, setReply] = useState("");
  const [importStatus, setImportStatus] = useState<Status>(null);
  const [busy, setBusy] = useState<"save" | "pack" | "import" | null>(null);

  useEffect(() => {
    setCtxStatus(null);
    setPackStatus(null);
    setImportStatus(null);
    setReply("");
    setDirty(false);
    getContext(runId)
      .then((c) => {
        setKeys(c.keys);
        setValues(c.values);
        setExtra(c.extra);
      })
      .catch((e) => setCtxStatus({ tone: "error", lines: errLines(e) }));
  }, [runId]);

  const save = async () => {
    setBusy("save");
    try {
      const c = await putContext(runId, values, extra);
      setValues(c.values);
      setExtra(c.extra);
      setDirty(false);
      setCtxStatus({ tone: "ok", lines: ["Saved context.md"] });
      onDigestChanged();
    } catch (e) {
      setCtxStatus({ tone: "error", lines: errLines(e) });
    } finally {
      setBusy(null);
    }
  };

  const copyPrompt = async () => {
    setBusy("pack");
    try {
      if (dirty) await save();
      const pack = await coachPack(runId);
      onDigestChanged();
      await copyText(pack.text);
      setPackStatus({
        tone: "ok",
        lines: [`Copied coach prompt: ~${pack.approx_tokens.toLocaleString()} tokens (${pack.chars.toLocaleString()} chars)`],
      });
    } catch (e) {
      setPackStatus({ tone: "error", lines: errLines(e) });
    } finally {
      setBusy(null);
    }
  };

  const doImport = async () => {
    setBusy("import");
    try {
      const res = await importTips(runId, reply);
      onTipsImported(res.tips);
      setReply("");
      setImportStatus({
        tone: "ok",
        lines: [`Imported ${res.imported} coach tip(s)`, ...res.warnings.map((w) => `Warning: ${w}`)],
      });
    } catch (e) {
      setImportStatus({ tone: "error", lines: errLines(e) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="panel coach-box coach-panel">
      <h3 className="coach-heading">Coach</h3>

      <div className="coach-step">
        <div className="coach-step-title">1. Context (what the CV can't see yet)</div>
        <div className="coach-fields">
          {Object.entries(keys).map(([key, label]) => (
            <label key={key} className="coach-field">
              <span className="coach-label">{label}</span>
              <input
                className="coach-input"
                type="text"
                maxLength={500}
                value={values[key] ?? ""}
                placeholder="unknown"
                onChange={(e) => {
                  setValues({ ...values, [key]: e.target.value });
                  setDirty(true);
                }}
              />
            </label>
          ))}
        </div>
        <label className="coach-field">
          <span className="coach-label">Other notes</span>
          <textarea
            className="coach-input"
            rows={3}
            maxLength={8000}
            value={extra}
            onChange={(e) => {
              setExtra(e.target.value);
              setDirty(true);
            }}
          />
        </label>
        <div className="coach-actions">
          <button type="button" className="mc-button" onClick={save} disabled={busy != null || !dirty}>
            {busy === "save" ? "Saving…" : dirty ? "Save context" : "Saved"}
          </button>
          <StatusLine status={ctxStatus} />
        </div>
      </div>

      <div className="coach-step">
        <div className="coach-step-title">2. Ask Claude</div>
        <div className="coach-actions">
          <button type="button" className="mc-button" onClick={copyPrompt} disabled={busy != null}>
            {busy === "pack" ? "Building…" : "Copy coach prompt"}
          </button>
          <StatusLine status={packStatus} />
        </div>
      </div>

      <div className="coach-step">
        <div className="coach-step-title">3. Paste Claude's reply</div>
        <textarea
          className="coach-input coach-reply"
          rows={6}
          value={reply}
          placeholder="Paste the whole reply - the ```json block is extracted"
          onChange={(e) => setReply(e.target.value)}
        />
        <div className="coach-actions">
          <button type="button" className="mc-button" onClick={doImport} disabled={busy != null || !reply.trim()}>
            {busy === "import" ? "Importing…" : "Import tips"}
          </button>
          <StatusLine status={importStatus} />
        </div>
      </div>
    </div>
  );
}
