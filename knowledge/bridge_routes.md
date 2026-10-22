status: draft (transcribed from spreadsheet, awaiting learner review)

# Bridge bastion: CHALICE START route decision table

Scope: these routes apply ONLY when the player starts the bridge bastion at the **chalice**. Other start positions have other routes (not covered here yet). Never apply this table to a non-chalice start.

Source: spreadsheet by Joomz, routes by doogile (left dk / right dk), last updated 10/10/2025.
https://docs.google.com/spreadsheets/d/1TYV8RBFb4sV2VRQRZGKPjN-hTPS6bx9UllXKChZyIa0

## Names
- **dk** = donkey kong (route). **left dk** / **right dk**.
- **cs** = cracksmoker (route).
- **soog** = silver/doogile right dk.
- **triple / single** = the variant of each rampart (left and right) (learner, ranked player):
  - **Exterior:** a triple rampart is TALLER than a single.
  - **Interior:** a triple's room has a double chest AND a single chest; a single's room has only one chest. (In CV terms: opening a double chest shows the 6-row chest GUI; a single chest shows the 3-row GUI.)
- **Knowledge of a rampart** = the player has seen its exterior height clearly, or has been inside its room. Anything else counts as unknown.

- **Left / right** (objective labels, learner): stand at the chalice FACING the ramparts; left rampart = on your left, right rampart = on your right.
- **TNT for gold** (learner): the reference videos use TNT to break gold blocks. Without TNT this isn't possible. With TNT: break the top-middle gold block and light a TNT in the hole, instead of breaking all the blocks by hand (saves ~10–20 s).

## Decision table
The deciding variable is **what the player knows about the two ramparts** (left / right, triple / single) at the chalice.

| Rampart knowledge | Situation | Route |
|---|---|---|
| Both ramparts | Left triple only | left dk |
| Both ramparts | Right triple only | cs |
| Both ramparts | Double single | soog (silver/doogile right dk) |
| Both ramparts | Double triple | cs (see exception 1) |
| Left only | Left triple | left dk |
| Left only | Left single | right dk, then on seeing the right rampart: right triple → cs; right single → soog |
| Right only | Right triple | cs |
| Right only | Right single | start left dk and check the left rampart: left triple → left dk; left single → left dk → cs |
| Neither | (unknown) | start left dk and check: left triple → left dk; left single + right single → left dk → cs; left single + right triple → left dk → cs |

## Important exceptions
1. **Double triple:** if the player knows where the fortress is and it is closer to the left triple, play **left dk**. If no fortress has been seen, pie-chart (piedar) the fortress direction *before* choosing the route (double triple only): left → left dk; otherwise → right dk (cs). Use whichever triple is played to scout where the spawner is or isn't.

## Misc. variants (details not in the sheet)
- left dk with leaves/wood
- right dk with leaves/wood
- flint and steel hog tech: lighting yourself on fire nullifies hoglin knockback. A feedback tip, not a route choice (see mistakes.md `hoglin-knockback-no-fire`).

**Flammable building blocks (learner, ranked player):** if the player's only building blocks are leaves or wood (logs/planks), they can burn, so the recommended route MUST be the leaves/wood version (left dk / right dk with leaves/wood). If the player has adequate non-flammable building blocks (**30+ blocks**, learner), the normal routes apply. Check the hotbar/inventory at the decision moment.
- **There is no cs with leaves/wood.** When the table says cs but the player only has flammable blocks (leaves and/or wood, < 30 non-flammable), the optimal route is **right dk with leaves/wood**. Say it like: "Due to you only having leaf/wood blocks, the optimal route is Right DK (leaves/wood) instead of CS."
- Right dk with leaves is basically the same setup as cs: nothing changes macro-wise, the player just places extra blocks to eliminate the lava (learner). So for any row whose chain ends in cs (incl. left dk → cs), the leaves/wood player follows the same decision chain with right dk (leaves/wood) in place of cs.

## Choosing the BEST route: start point + route + destination (learner, ranked player)
The chalice table above is only one start point. The best plan minimises, using ONLY what the player knew at the time:
  time to reach the start point (from where the player approached) + route time + time from the route's end to the next goal (fortress),
weighed by each route's subjective risk vs the opponent gap.
- **Start point:** routes exist from other start points (e.g. a left-triple start). If one was faster/easier to reach from the player's approach than the chalice, the best route should have started there, even if the chosen chalice route was played well. Judge the approach path too.
- **Destination (EXTREMELY IMPORTANT):** a route realistically ends at one of three places: the chalice, the left rampart, or the right rampart. If the player saw the fortress (e.g. while navigating to the bastion), prefer the route that ends on the fortress side. Example: the double-triple exception above.
- **Fortress knowledge:** state concretely whether and when the fortress was seen (or pie-charted) before the decision, and from where.
- **When a rampart (triple) start beats going to the chalice first** (learner), any of:
  1. navigating to the chalice is hard (multiple high/low terrain changes, or having to bridge over);
  2. the fortress is closer to the chalice (a triple-to-chalice route ends at the chalice);
  3. the player needs to loot the triple's chest for an iron pickaxe.
> TODO (learner): review knowledge/drafts/bridge_variants.md (triple-to-chalice routes, end points, times).

- **State the knowledge concretely first.** E.g. "At the chalice (3:12) you had seen the right rampart's exterior (single, taller-than check at 3:05); the left rampart was unknown." The knowledge state decides the row.
- **Teach the thinking, not just the answer.** Always quote the table row and its instruction chain verbatim (e.g. "Right single known → start left dk and check the left rampart: left triple → left dk; left single → left dk → cs"), so the player learns how to decide next time. This matters most for the "right rampart only" and "no ramparts" rows.
- **Cite the reference route** (knowledge/routes.md id) for the recommended route so the player can watch it.
- Judge the choice only on the rampart knowledge the player had **at the moment of choosing**.
- Lava matters only if it can't be contained during the usual route (learner).
- Each route has its own subjective risk. Weigh it against the opponent gap (behind → risk may be justified; ahead → prefer safe).
