# Mistake catalogue

<!-- Learner-authored. One entry per mistake. Copy the template; keep ids stable (coach tips cite them). -->

Fields:
- `id`: kebab-case, stable
- `split`: overworld | entered_nether | found_bastion | found_fortress | finding_stronghold | found_stronghold | entered_end (or "post-route" etc. in words if it spans splits)
- `category`: {macro|micro} × {knowledge|mechanics}, e.g. `micro/mechanics`
- `fix_type`: easy (just do it differently next time) | practice (needs reps / judgement)
- `typical_seconds_lost`: rough number or range
- `noticed`: what information was available *at that moment* that should have triggered the right choice
- `detect`: CV signals that could find it automatically, or `needs <reader>`
- `notes`
- `status`: draft | confirmed

Template:

```
### <short title>
- id:
- split:
- category:
- fix_type:
- typical_seconds_lost:
- noticed:
- detect:
- notes:
- status: draft
```

---

### Bastion: placing a gold block instead of breaking one to anger piglins
- id: bastion-gold-block-place-vs-break
- split: found_bastion
- category: micro/knowledge
- fix_type: easy
- typical_seconds_lost: ~2
- noticed: Learner wording: "not breaking a gold block to anger piglins, instead pulling out (placing/using) a gold block." The gold blocks in the bastion are visible at the time the piglins need to be angered.
- detect: needs HUD reader (hotbar slot / held item = gold block) + block-break detector; partial signal: hotbar change then place action near piglins in the bastion split
- notes: Learner's estimate; verify the exact sequence on a VOD frame before confirming.
- status: draft

### Searching for flint instead of doing a wood light
- id: flint-search-vs-wood-light
- split: overworld
- category: macro/knowledge
- fix_type: easy
- typical_seconds_lost: ~60
- noticed: Learner wording: "spending ~1 min searching for flint instead of doing a wood light (lighting the portal with wood/fire instead of flint and steel)." At the time: no flint in inventory yet, portal frame ready, wood available.
- detect: needs HUD/inventory reader (flint count, held item) + optical flow (repeated gravel digging); partial signal: long overworld time between portal-frame completion and "We Need to Go Deeper" / nether entry
- notes: Applies when the portal frame is otherwise ready and flint hasn't dropped.
- status: draft

### Post-bastion, pre-fortress: choosing low terrain when high terrain looks more open
- id: low-terrain-when-high-open
- split: found_bastion → found_fortress (post-route)
- category: macro/knowledge
- fix_type: practice
- typical_seconds_lost: unknown (varies)
- noticed: Learner wording: "choosing low terrain when high terrain looks more open — not always true, requires reasoning." At the time: how open each height level looks from where the player stands after leaving the bastion.
- detect: F3 y-level after bastion exit (digest section f, y range) + needs explored-map reader (how open each height was)
- notes: Not a fixed rule — the coach should reason case by case from what was visible, not apply it blindly.
- status: draft

### Hoglin knockback without flint and steel ("hog tech")
- id: hoglin-knockback-no-fire
- split: found_bastion
- category: micro/knowledge
- fix_type: easy
- typical_seconds_lost: varies (death, recovery time, damage from falls/lava)
- noticed: Learner wording: when the player can foresee getting knocked back by a hoglin, they can use flint and steel to light themselves on fire, which nullifies the knockback. At the time: hoglin close and about to hit, player has flint and steel, a dangerous drop or lava nearby.
- detect: needs health reader (damage taken), death screen, sudden position jump/fall (F3 or flow), flint and steel in hotbar (HUD reader); hoglins visible (LLM on frame for now)
- notes: Only raise it when the hit had LARGE consequences (death, big damage from knockback/falling in lava, time spent recovering). Mundane, apply-immediately knowledge — no practice needed.
- status: draft

### Missed or incorrect Ninjabrain Bot calculation
- id: ninjabrain-miscalc
- split: finding_stronghold
- category: macro/mechanics
- fix_type: practice
- typical_seconds_lost: ~60–120 (portal far from the stronghold)
- noticed: Learner: a blind portal far from the stronghold usually means the player didn't use Ninjabrain correctly (bad throw/measurement or misread result).
- detect: eye throws + Ninjabrain overlay output (needs eye-throw reader + Ninjabrain overlay OCR); blind distance to stronghold from F3
- notes: Usually the root cause when the blind portal lands far from the stronghold.
- status: draft

### Bridge: breaking gold by hand when TNT was available
- id: bridge-gold-no-tnt
- split: found_bastion
- category: micro/knowledge
- fix_type: easy
- typical_seconds_lost: ~10–20
- noticed: Learner: with TNT in inventory, break the top-middle gold block and light a TNT in the hole instead of breaking every gold block by hand.
- detect: needs HUD/inventory reader (TNT count) + gold-breaking time in the bastion
- notes: Not applicable if the player had no TNT.
- status: draft

### Unsure route choice → hesitation (bridge)
- id: bridge-route-hesitation
- split: found_bastion
- category: macro/knowledge
- fix_type: practice
- typical_seconds_lost: ~20–45
- noticed: Learner: stalling at the chalice usually means the player is unsure which route to do. Typical case: a rampart was visible from the POV, which fixes the table row, but the player played a different (less efficient) route.
- detect: idle/low-motion time at the chalice + rampart knowledge (needs rampart reader) vs route taken
- notes: Teach the table row and decision chain so the choice becomes automatic.
- status: draft
