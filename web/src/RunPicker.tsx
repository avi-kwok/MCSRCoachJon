import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import type { RunSummary } from "./types";
import { runTitle } from "./format";

interface Props {
  runs: RunSummary[] | null;
  value: string | null;
  onChange: (id: string) => void;
}

const OUTCOME_CLASS = { Won: "run-won", Lost: "run-lost", Forfeit: "run-forfeit" } as const;

/** One run's title: date — Won/Lost/Forfeit (coloured) final time [Private room]. */
function Title({ run, showId = false }: { run: RunSummary; showId?: boolean }) {
  const t = runTitle(run);
  return (
    <span className="run-title">
      <span className="run-date">{t.date}</span>
      {t.estimated && <span className="run-est"> est.</span>}
      <span className="run-sep"> — </span>
      {t.outcome && <span className={OUTCOME_CLASS[t.outcome]}>{t.outcome} </span>}
      <span className="run-time">{t.time}</span>
      {t.privateRoom && <span className="run-tag"> Private room</span>}
      {showId && t.date !== run.id && <span className="run-id"> · {run.id}</span>}
    </span>
  );
}

/**
 * Minecraft-style run dropdown. A native <select> can't colour single words
 * ("Won" gold, "Lost" red, "Forfeit" grey), so this is a button + listbox (ARIA combobox-less
 * "listbox button" pattern): Enter/Space/Arrow keys open it, arrows move,
 * Enter picks, Esc closes, Home/End jump.
 */
export default function RunPicker({ runs, value, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const listId = useId();

  const list = runs ?? [];
  const current = list.find((r) => r.id === value) ?? null;
  const disabled = list.length === 0;

  const openList = () => {
    setActive(Math.max(0, list.findIndex((r) => r.id === value)));
    setOpen(true);
  };
  const close = (refocus = true) => {
    setOpen(false);
    if (refocus) buttonRef.current?.focus();
  };
  const pick = (i: number) => {
    const run = list[i];
    if (run) onChange(run.id);
    close();
  };

  // Focus the list when it opens; close on a click outside.
  useEffect(() => {
    if (!open) return;
    listRef.current?.focus();
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) close(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  // Keep the active option scrolled into view.
  useEffect(() => {
    if (open) listRef.current?.children[active]?.scrollIntoView({ block: "nearest" });
  }, [open, active]);

  const onButtonKey = (e: KeyboardEvent) => {
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) {
      e.preventDefault();
      openList();
    }
  };

  const onListKey = (e: KeyboardEvent) => {
    const last = list.length - 1;
    const keys: Record<string, () => void> = {
      ArrowDown: () => setActive((i) => Math.min(last, i + 1)),
      ArrowUp: () => setActive((i) => Math.max(0, i - 1)),
      Home: () => setActive(0),
      End: () => setActive(last),
      Enter: () => pick(active),
      " ": () => pick(active),
      Escape: () => close(),
      Tab: () => close(false),
    };
    const action = keys[e.key];
    if (!action) return;
    if (e.key !== "Tab") e.preventDefault();
    e.stopPropagation(); // Esc here must not also clear the selected split
    action();
  };

  return (
    <div className="picker" ref={rootRef}>
      <span className="picker-label" id={`${listId}-label`}>
        Run
      </span>
      <div className="dropdown">
        <button
          ref={buttonRef}
          type="button"
          className="dropdown-button"
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-labelledby={`${listId}-label ${listId}-value`}
          aria-controls={open ? listId : undefined}
          disabled={disabled}
          title={current ? runTitle(current).tooltip : undefined}
          onClick={() => (open ? close() : openList())}
          onKeyDown={onButtonKey}
        >
          <span id={`${listId}-value`} className="dropdown-value">
            {current ? <Title run={current} /> : runs ? "No runs yet" : "Loading…"}
          </span>
          <span className="dropdown-arrow" aria-hidden>
            {open ? "▲" : "▼"}
          </span>
        </button>
        {open && (
          <ul
            ref={listRef}
            id={listId}
            className="dropdown-list"
            role="listbox"
            tabIndex={-1}
            aria-labelledby={`${listId}-label`}
            aria-activedescendant={`${listId}-opt-${active}`}
            onKeyDown={onListKey}
          >
            {list.map((r, i) => (
              <li
                key={r.id}
                id={`${listId}-opt-${i}`}
                role="option"
                aria-selected={r.id === value}
                className={`dropdown-option ${i === active ? "active" : ""} ${r.id === value ? "selected" : ""}`}
                title={runTitle(r).tooltip}
                onMouseEnter={() => setActive(i)}
                onClick={() => pick(i)}
              >
                <Title run={r} showId />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
