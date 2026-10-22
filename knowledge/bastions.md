# Bastions — types, identification, routes (1.16.1)

status: draft (researched, awaiting learner review)

<!-- Researched reference. Every claim cites [n] (Sources at bottom). Learner edits win. -->

## Why bastion first
- Goal: trade gold for pearls + obsidian (+ string for beds, fire res); go bastion before fortress for the chance of Fire Resistance [3][7].
- Minimum loot: 10 obsidian (blind travel), 12 pearls (16+ preferred); 20 obsidian enables double/"calculated" travel [3]. Wikibooks target: ≥10 obby, 1 fire res, 16 pearls [7].
- Bastion vs fortress per 432×432 region: bastion 3/5, fortress 2/5; one structure per region [2][13]. 1.16.1: bastions never in basalt deltas [2][3].
- Finding it: "microlensing"/E-ray — a quick jump in the F3 `E:` count, or M+C ≈ E+30, suggests a bastion in render distance; at FOV 30 turn slowly and watch the left `E:` number [3].

## Piglin mechanics (what the coach should check)
- 1.16.1 has **no piglin brutes** (added 1.16.2) [10]. Ignore brute advice from newer guides.
- Breaking a **gold block** or a container angers piglins within 16 blocks, no line of sight needed; *opening* a chest angers only piglins with line of sight [7][8]. Breaking out of sight angering was added in 1.16 pre3, so it applies to 1.16.1 [8].
- Hitting a piglin angers nearby piglins; the hit piglin ignores thrown gold [7][8]. Manhunt routes deliberately punch one piglin after breaking the chest to "upgrade" aggro so more piglins follow [6].
- Wearing ≥1 gold armor piece keeps piglins neutral (no auto-aggro) [3][8]. Manhunt Housing: if you enter with gold armor, the punch step is pointless [6].
- Angered piglins (not hit-angered) can be distracted by gold; anger lasts 30 s [8].
- Bartering: 6 s admire per ingot (Java) [12]. Trading setup = lead angered piglins into a **hole** (1×1 pit) and throw gold [3][6][7].
- 1.16.1 barter table (total weight 423): pearls 4–8 (20/423 ≈ 4.7%), string 8–24 (20/423), obsidian 1 (40/423), crying obsidian 1–3 (40/423), fire res potion and splash each 10/423. 1.16.2 cut quantities (pearls 2–4) [9].
MCSR Ranked "standardizes" piglin trades so that both players receive the same rolls for every random factor  (example: both players will receive x rods from y blaze deaths) [11];
- Ranked rules (seeded by the match seed, same trades in the same order for both): obsidian barter odds +~35%; ≥6 obsidian and exactly 3 pearl trades guaranteed per 72 barters (8 gold blocks); no non-structure mob spawns inside bastions; zombified piglins avoid pathing in [15].
- Ranked filter: intended bastion's ramparts hold ≥3 iron + ≥5 obsidian; stables always has 2 good gaps, or 1 good gap + ≥1 triple-chest rampart [16].

## Identify the type (from outside / on arrival)
Ramparts are the main tell; every type has them [1].
| Type | Ramparts | Rampart chests | Other tells |
|---|---|---|---|
| Bridge | 2, **separated** | 1 or 3 | piglin-face rampart; bridge from the "mouth"; gold "chalice" (16 gold in bridge piece) [1][2] |
| Housing | 2, adjacent | 0, 1 or 3 | central courtyard, nether wart on soul sand, a center chest [2] |
| Stables | **3** | 1, 2 or 3 | hoglin stables both sides; hoglins [1][2] |
| Treasure | 2, adjacent | always 2 | big lava basin, magma-cube spawner, gold center (12–19 blocks) [1][2] |
- Triple-chest rampart: player y=73 on Bridge/Housing, y=72 on Stables [1]. Between the double and single chest: 2 blocks → Stables; 3 blocks → Housing or Bridge [3]. Treasure never has a triple-chest top [3].
- Rampart backs differ per type (image-only in [1]).
- Pie-ray false positive: a treasure bastion's spawner shows up as a "spawner" like a blaze spawner [3].

## Rampart height and iron pickaxe (learner, ranked player)
- **Rampart height is the main exterior cue for triple vs single (vs ruins).** Taller = triple. Applies to:
  - **Bridge:** left and right ramparts are triple or single.
  - **Housing:** the RIGHT rampart is GUARANTEED triple; the left can be triple, single, or ruins. (Learner: always triple — treat any "ruined right rampart" source as wrong for this purpose.)
  - **Stables:** ramparts can be single, triple, or ruins.
- **Iron pickaxe is not guaranteed from the overworld.** If the player has none, they must get one before starting the route, usually by looting a bastion chest that has iron. Judge route choice and timing with this in mind (e.g. a detour to a rampart chest for iron, then starting the usual route from there, is correct, not a mistake).

- **Punching a piglin** (learner): typically not needed, but a punched piglin will never be distracted (by gold) afterwards — the player/coach should know this when judging aggro/trading setups.

## Routes by type
Times below = top-runner model on Llama's practice map (no TAS), measured from the listed start point: **trade start** (piglins aggro'd / can reach the hole) and **hole return** (all tasks done, back at hole) [4][5]. No source gives times for real ranked matches.

### Bridge — most beginner-friendly
- Gold exposed and away from piglins [7]. If the chalice is buried, craft a gold pickaxe from it [3].
- Main risk: dying to the hoglins in the middle [7].
- Decision = which rampart has the triple chest [3][4]:
| Route | Needs | Start | Trade start / hole return | Gold / chests |
|---|---|---|---|---|
| Right shoulder (Original/Pizza/High Hole) | right triple | chalice | 0:09–0:14 / 0:48–0:54 | 16 / 5 |
| Gus (Reignex) | left triple | chalice | 0:23 / 0:43 | 16 / 3 |
| Speed Record (buried/exposed) | any | chalice | 0:21–0:23 / 0:52–1:05 | 16 / 1–2 |
| Manhunt Lode | left triple | lodestone area | 0:13 / 0:40 | 16 / 0 |
| Manhunt left / right | left / right triple | that rampart | 0:25–0:44 / 0:56–1:12 | 16 / 3 |
- Double-single (no triple): Metacor points to "Ela's Hole"/Speed Record routes [3][4].

### Housing — start depends on where you arrive (bottom vs top) [3]
| Route | Start | Trade start / hole return | Gold / chests |
|---|---|---|---|
| Manhunt | centre chest | 0:20 / 0:39 | 9 / 3 |
| Lava Manhunt | centre chest | 0:23 / 0:49 | 9 / 3 |
| Top-Down (Sichi / Double-Triple / Dig-Thru) | top middle | 0:24–0:40 / 0:48–1:08 | 9–12 / 5–8 |
- [1] rates Top-Down 5/10 difficulty, Lava variants 7/10, all 9–12 gold, 5–8 chests (counts differ from [4] for Manhunt).
- Manhunt steps [6]: find centre chest and the direction to the ramparts → break centre chest (aggro) → punch one piglin that is closer to the ramparts than the chest (not too close, or rampart piglins aggro too) → bridge over lava (center bridge blocks; 8-block bridge) → block two piglin paths at the staircase (blocks > lava > fire) → optional double chest → dig the trading hole (needs ≥1 gold block in the 2nd column) → leave.
- Hole options trade digging time for safety, e.g. Standard 19 blocks mined, Fast1 18, "Twice Elevated" 15 (recommended for top-down) [6].
- Lava bridging: build 1 block *above* lava, 3 wide, no corners — piglins won't step up/down at lava edges or cut corners [3].

### Stables — weakest; depends on triple/gap luck
| Route | Needs | Trade start / hole return | Gold / chests |
|---|---|---|---|
| Single triple | any 1 triple rampart | 0:17 / 0:42 | 4 / 4 |
| Double triple | 2 adjacent triples | 0:20 / 1:04 | 8 / 6 |
| Manhunt gap (right/left) | "good gap" | 0:15–0:16 / 1:04–1:05 | 10 / 2 |
(start: ramparts; gap routes start at middle stairs) [4]. Triple rampart pieces hold 4 gold each [2].
- Metacor flow: triple → triple-chest route; no triple + good gap → gap route; no triple + double bad gap → "better luck next time" [3].
- Each stables has AT LEAST one good gap
- A good gap can be determined through multiple ways. 
- Left gap is determined by either 1. Breaking the polished blackstone brick to the left of the chest at the bottom of the middle staircase (blackstone behind - good gap | air or netherrack - bad gap) 2. At the top of the middle staircase, breaking the eyesight level block leading to the left rampart (air behind - good gap | else bad gap). 
- There is another method in determining gaps by looking at the bottom generation of each gap.
- If a bad gap is discovered, the other rampart is guaranteed to be good
- It is possible for both ramparts be good gaps.

#### Stables layout & loot (zolstice guide [14]; diagrams described)
- Seen from outside: 3 ramparts (left, middle, right) next to the hoglin pens; only the ramparts matter. Each has a top half and a bottom half.
- Bottom middle is always the same: the "middle staircase", a zig-zag stair (up, turn, up) with a chest at its foot. Bottom left/right = the two gaps.
- Right gap check mirrors the left: break the marked wall block in the middle staircase on the right side; blackstone behind = good, air/netherrack = bad.
- Bad gap: a single chest only; its piglin-snout blocks are a decoy (no gold).
- Good gap: up to 4 gold blocks in one wall spot plus up to 6 gold blocks under the piglin-snout blocks on the floor.
- Tops come in 3 variants: triple-chest (always 4 gold blocks in a room under the chests), diagonal-chest (1 chest, no gold), lantern-chest (2 chests in an upper and a lower room, no gold).
- Ranked's filter rules out the double-bad-gap stables Metacor calls "better luck next time" [16].

### Treasure — high gold, high risk
| Route | Start | Trade start / hole return | Gold / chests |
|---|---|---|---|
| Ninjabrain (Lavabrain / Middle-Dip) | bridge | 0:11–0:13 / 0:49–0:55 | ~12.4 / 4 |
| Right Boomer | bridge | 0:12 / 0:48 | n/a |
| Top Treasure | ramparts | 0:15 / 0:53 | n/a |
[4]. Craft a gold pickaxe from the gold blocks on the bridge [3].
- Risks: piglins hard to gather at the bottom; magma cubes swarm; [7] calls rampart gold the safer choice.

## Common bastion mistakes (sourced)
- Skipping the centre bridge blocks in Manhunt Housing → lose 2–3 piglins [6].
- Placing bridge blocks *after* aggro; using fire at the staircase (burns piglins); punching a piglin too close to the ramparts; breaking the centre chest with a wood axe [6].
- Hitting the piglins you want to trade with (they then ignore gold) [7][8].
- Dying to bridge hoglins [7]; entering treasure bottom without a plan for magma cubes [7].
- Bad lava bridges (in lava, 1-wide, corners) → piglins don't follow [3].

## What the player can see at each decision point
- Nether entry: F3 `E:` jump / M+C vs E → bastion nearby and direction [3].
- Approach: rampart count/spacing, chest gap, y-level, stables/lava basin/courtyard → type [1][3].
- Bridge: which shoulder has the triple; chalice buried or exposed [3][4].
- Housing: arriving top or bottom; centre-chest location [3][6].
- Stables: which ramparts are triples; gap shape [3].
- During trading: pearl/obby/string counts vs targets (10 obby, 12–16 pearls) decide when to leave [3].

## Sources
1. MCSR Wiki, Bastion routing — https://mcsr.miraheze.org/wiki/Bastion_routing
2. Minecraft Wiki, Bastion Remnant — https://minecraft.wiki/w/Bastion_Remnant
3. Metacor, Minecraft Speedrun Guide (1.16.1; last commit Nov 2022) — https://github.com/Metacor/Minecraft-Speedrun-Guide
4. pncakespoon et al., Bastion Route Sheet (Bridge/Housing/Stables/Treasure tabs) — https://docs.google.com/spreadsheets/d/1qLgp5uhMOKuerNZaec1dpoECpJI0-6YhztMqa_wZ8W0
5. Route Sheet preface (timing method) — https://docs.google.com/document/d/1rhFI3UJQKnqMeudHdkMDAo4CUrieWNuu_o0ODf5k2vc
6. MCSR Wiki, Manhunt Housing — https://mcsr.miraheze.org/wiki/Manhunt_Housing
7. Wikibooks, Minecraft Speedrunning/Bastion Strats (edited Sep 2025) — https://en.wikibooks.org/wiki/Minecraft_Speedrunning/Bastion_Strats
8. Minecraft Wiki, Piglin — https://minecraft.wiki/w/Piglin
9. Minecraft Wiki, Bartering/Outdated loot tables (20w20a–20w27a = 1.16/1.16.1) — https://minecraft.wiki/w/Bartering/Outdated_loot_tables
10. Minecraft Wiki, Piglin Brute (added 1.16.2) — https://minecraft.wiki/w/Piglin_Brute
11. MCSR Ranked mod page — https://modrinth.com/mod/mcsr-ranked
12. Minecraft Wiki, Bartering — https://minecraft.wiki/w/Bartering
13. Minecraft Wiki, Nether Fortress — https://minecraft.wiki/w/Nether_Fortress
14. zolstice, Beginner's Guide to Hoglin Stables (r/MinecraftSpeedrun, Feb 2021; image gallery) — https://www.reddit.com/r/MinecraftSpeedrun/comments/lprexu/beginners_guide_to_hoglin_stables/
15. MCSR Ranked Wiki, RNG Standardization — https://wiki.mcsrranked.com/gameplay/rng
16. MCSR Ranked Wiki, Filtered Seeds — https://wiki.mcsrranked.com/gameplay/seed

Not read: Couriway's Metafy guide (https://metafy.gg/guides/view/ultimate-minecraft-speedrun-guide-cIzfjeTmwOm) — chapters are paywalled; only the table of contents was visible.
