# knowledge/

Learner-authored notes the coach reads (pasted into every `coach-pack`). The coach treats them as
the learner's current understanding: it may disagree, but must say why — the learner has final say.

- `general.md` — 1.16.1 mechanics and strategy, by topic. Short bullet facts, one idea per line.
- `bastions.md` — bastion types, identification, routes, piglin mechanics (researched draft).
- `bridge_routes.md` — bridge bastion route choice: which `bridge-*` route in `routes.md` to play when.
- `mistakes.md` — catalogue of recurring mistakes, one entry per mistake (format at the top of the file).
- `routes.md` — your bastion route library: YouTube VODs of good routes (type, entry, url, start/end).
  The coach cites a route id in `reference_route`; the UI's "Compare with reference" plays it beside your run.

Writing entries:
- Keep each entry short; the whole folder is pasted into the prompt, so tokens matter.
- Write what *you* believe now. Mark unsure entries `status: draft`; switch to `status: confirmed`
  once you've checked them (practice, VODs of top players, guides).
- Give every mistake a stable `id` (kebab-case). Coach tips cite it in `catalogue_id`.
- "What the player must have noticed" = information visible *at that moment* in the run. If you can't
  name it, the mistake is hindsight, not a mistake.
- When the coach disagrees with an entry (`disagrees_with_catalogue`), decide and edit the entry.
