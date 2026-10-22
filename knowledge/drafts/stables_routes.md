status: draft (researched, awaiting learner review)

# Stables bastion: route decision table

Every claim cites [n]. Learner edits win. See bastions.md for gap identification and layout.

## Decision variables (visible to the player)
1. **Which top ramparts are triple** (left / middle / right; 0, 1 or 2+) [1][2][3].
2. **Middle top rampart type** when a side is triple: lantern (= "double") or single [3][4]. "Lantern and Double ramparts are different names for the same thing" [4].
3. **Gap quality**: left/right lower rampart good or bad [3][4][5].
4. **Exposed vs buried** (several triple-to-gap variants are exposed-only) [4].
5. Ranked filter: every ranked stables has 2 good gaps, or 1 good gap + at least one triple-chest rampart (bastions.md [16], https://wiki.mcsrranked.com/gameplay/seed).

## Names
- **TTG = Triple To Gap**: loot a triple, then play a good gap [3][4][6].
- **Classic TTG**: triple and good gap on the same side [4].
- **Hourglass**: left triple → (left bad gap) → right good gap; Chloe + pavkin [4][7]. kindred's version "works on buried" [8].

## Decision table
| Triples | Middle / gaps | Route | Source |
|---|---|---|---|
| none | good gap | **Good Gap** (Classic, safe) or Auto Funnel / BeefSalad gap blocks (faster, riskier) | [2][3][4] |
| middle only | any good gap | **Middle Triple to Gap** | [3][4] |
| left only | middle lantern | **Left Triple to Middle Lantern** | [3][4] |
| right only | middle lantern | **Right Triple to Middle Lantern** | [3][4] |
| left only | middle single | **Left Triple to Middle Single** (exposed only) | [3][4] |
| right only | middle single | **Right Triple to Middle Single** (exposed; separate buried version) | [3][4] |
| left / right | same-side good gap | **Classic TTG** (L→L good, R→R good) | [4] |
| left | left gap bad | **Hourglass** (→ right good gap) | [3][4][7][8] |
| right | right gap bad | Right Triple to Right Bad Gap | [4] |
| two adjacent | — | **Double Triple** (L-M or M-R) | [1][2][3] |
| two split (L+R) | middle lantern / single | Split Double Triple (Lantern / Single) | [9] |
| any | any | **Suigi TTG** — "force this route on every stables"; safe, slower than the specific variants | [10] |
Metacor (2022) simpler flow: triple → triple-chest route; no triple + good gap → good-gap route [2].
> UNVERIFIED: when a single triple should skip the gap entirely (old "Single-Triple" route [1]) vs TTG. Learner to fill.

## Named routes and times
| Route | Start | Trade start / hole return | Gold / chests | Source |
|---|---|---|---|---|
| Single-Triple (L/M/R) | ramparts | 0:17 / 0:42 | 4 / 4 | [1] |
| Double-Triple (L-M / M-R) | ramparts | 0:20 / 1:04 | 8 / 6 | [1] |
| UnaTriple (Unassumed) | ramparts | 0:18 / 0:53 | 8 / 6 | [1] |
| Manhunt Right / Left Gap (Fyroah) | middle stairs | 0:15–0:16 / 1:04–1:05 | 10 / 2 | [1] |
Modern TTG routes: > UNVERIFIED times (none in any description read). migrained: "1:25ish 20-25 piglins triple to gap route" [11].
Others found: Triple Triple to Double Gap [12], Left to Right Triple Triple [13], Item Elevator L/R 8:30 and Middle 9:57 [9].

## Reference videos (chapters = route start)
- meebie TTG guide: Middle TTG 6:14, L→Mid Lantern 8:30, R→Mid Lantern 9:49, L→Mid Single 10:36, R→Mid Single exposed 11:49 / buried 12:42, R→R good 14:50, L→L good 15:24, Hourglass 15:55, R→R bad 17:13, Classic gap blocks 17:46, BeefSalad gap blocks 18:54 [4].
- HiTrippy: Double Triple 4:44, Middle TTG 6:16, L/R triple + middle lantern 6:39 / 7:33, + middle single 8:14 / 8:51, Good Gap Classic 9:21, Auto Funnel (Beef Salad hole) 10:17, Hourglass 11:40 [3].
- Kanes: Right Gap 7:44, Left Gap 8:35, TTG all-left 9:38, all-right 11:06, middle 13:46, "guessed wrong" 15:10, Disconnected TTG 16:16, Double Triple 18:59 [6].
- MCSR Wiki (2024): Right Good Gap 0:14, Left Good Gap 2:30, Double Triple 4:05, Split Double Triple 5:22 / 6:54 [9].
- Mikeyboie: Good Gap 55:48, Double-Triple 1:00:16, fast 1:05:21 [14].

## End points / exceptions
> UNVERIFIED: where each route's hole is (gap side vs middle) — matters for fortress direction.
- Buried stables: several TTG variants are exposed-only; buried needs the buried version or a gold pick [4].
- 7rowl stables info dump (chest ID, gap signs, buried bastions 10:31; auto chapters) [15].

## Sources
1. pncakespoon et al., Bastion Route Sheet, Stables tab — https://docs.google.com/spreadsheets/d/1qLgp5uhMOKuerNZaec1dpoECpJI0-6YhztMqa_wZ8W0/htmlview (gid 2107907080)
2. Metacor, Minecraft Speedrun Guide (Bastions) — https://github.com/Metacor/Minecraft-Speedrun-Guide
3. HiTrippy, "Stables Bastion Guide (All Useful Routes)" — https://www.youtube.com/watch?v=D8Mt1bNNWtg
4. meebie, "Stables Triple to Gap Updated Guide (all variants)" — https://www.youtube.com/watch?v=D4Ulw7VepJc
5. Fyroah, "In-Depth Bastions - Hoglin Stables" (2020) — https://www.youtube.com/watch?v=npYwNsa1KuA
6. Kanes, "Master the STABLES BASTION in 20 minutes || MCSR Tutorial Part 7" — https://www.youtube.com/watch?v=_N8Ax6tQ4MI
7. chloe, "Hourglass Gap Route (Left Triple to Right Gap)" — https://www.youtube.com/watch?v=9U8uJh9DGL0
8. kindred, "Hourglass Gap Route" — https://www.youtube.com/watch?v=CV3B9tLK8z0
9. MCSR Wiki (YouTube), "How to SPEEDRUN Bastions - STABLES" (2024) — https://www.youtube.com/watch?v=fjkkLdWYRmY
10. maexxez, "Suigi Triple To Gap" — https://www.youtube.com/watch?v=tORxck-C_Ng
11. migrained, "1:25ish 20-25 piglins triple to gap route" — https://www.youtube.com/watch?v=LuRXEx0gO80
12. GarryLarry890, "Triple Triple to Double Gap stables route" — https://www.youtube.com/watch?v=Xe6y6WQw5xE
13. Daniel_H212, "Left to Right Triple Triple Stables Route" — https://www.youtube.com/watch?v=Rjx0QLBTWJY
14. Mikeyboie, "Minecraft 2025 Speedrunning Guide For RANKED/RSG - Part 2: Bastions" — https://www.youtube.com/watch?v=CRwiJcWWUlY
15. 7rowl archive, "stables info dump" — https://www.youtube.com/watch?v=o8gCJJkCBno
