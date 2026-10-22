# Critic rubric (coach tips)

Used by the critic pass (`python -m vodreview critic-pack`). Derived from the rules in
`coach/system_prompt.md` (cited as R<n>) plus critic-only items. Score each tip item by item:
**pass / fail / n.a.**, and cite the evidence for every fail.

**Current scope: BASTION ROUTE macro choice** (which route to play from the chalice/entry, and why).
For other tips, only check items 1–3 and 11; don't rewrite them.

| # | Item | Fail when… | Source |
|---|---|---|---|
| 1 | **Known-at-time only** | the tip leans on something the player couldn't see/know at `t_start_s` (later frames, where a rampart/fortress turned out to be, F3-label rampart types read when the player stood on them, the learner's catalogue notes about this run). `known_at_time` names a source that isn't an observation ("catalogue note", "not confirmed"). | R2 |
| 2 | **Evidence is real** | timestamps outside the run/split, coordinates/dimension/items that don't match the CSVs, ids that don't exist (see the automatic checks), or a claim built on a digest field marked UNKNOWN without a frame/tool result backing it. | R4, R5, R10 |
| 3 | **Concrete** | it doesn't state all of: (a) what exactly went wrong, with evidence; (b) the specific better alternative; (c) how the player can tangibly improve/apply it. "Route lost ~40 s" alone fails. | R12 |
| 4 | **Root cause** | it describes the symptom (slow, hesitated, wandered) without saying why (wrong table row, misread rampart, lacked an item, unknown route). | R14 |
| 5 | **Merged recurring issues** | the same issue appears as several tips, or one tip mixes unrelated issues. | R13 |
| 6 | **Non-standard actions accounted for** | extra time is blamed on the route while part of it went to actions outside the standard route (crafting, fighting, looting a side chest, a detour). Those must be attributed separately. | R15 |
| 7 | **Rampart knowledge established first** | the route verdict assumes a rampart state (left/right, single/triple, known/unknown) without showing how it was established at decision time (frame on the approach/chalice; anything visible from the player's POV counts). If it is truly unknown, the tip must use the "Neither" row, not guess. | R16 |
| 8 | **Resources the route needs** | it recommends a route/technique the inventory didn't allow (e.g. cs with only leaves/wood; TNT gold without TNT), or misses that a needed item was available and unused. | R17 |
| 9 | **Reference route cited** | a bastion route tip has `reference_route` null although `knowledge/routes.md` has an entry with the same bastion type + entry; or cites one of the wrong type/side/variant (e.g. flammable vs normal). | R10 |
| 10 | **Justified deviations recognised** | the player deviated from the table/standard route for a visible, good reason (e.g. a hoglin or piglin in the way, lava, missing blocks) and the tip flags it as a plain mistake. A good tip names the reason, judges whether the deviation was reasonable, and only then discusses a better handling (e.g. moving the hoglin). | critic-only (not yet in the coach prompt) |
| 11 | **Calibrated** | `est_seconds_lost` not explained or implausible; `confidence` higher than the evidence supports (R7); `severity_rank` ignores ease of fix (R8). | R3, R7, R8 |

Verdicts:
- **keep** — passes every applicable item (minor wording issues allowed).
- **revise** — the core finding stands but ≥1 item fails and can be fixed from the available evidence.
- **drop** — item 1 or 2 fails at the core of the claim, or the tip can't satisfy item 3 with the evidence.
