# General knowledge — MCSR Ranked 1.16.1

status: draft (researched, awaiting learner review)

<!-- Researched reference; learner edits win. Every claim cites [n] (Sources at bottom). Bastion detail lives in bastions.md. -->

## Mechanics (1.16.1)

### Overworld
- Route shape: enter Nether with basic resources (village, shipwreck, buried treasure) → bastion trades → fortress rods → stronghold → End [1].
- Shipwreck chests: treasure (iron, gold, diamonds), supply (food, sometimes TNT), map. Full wreck = 3 chests + enough wood; front half = supply only; back half = treasure chest, no food, ~4 logs [2].
- Buried treasure: more iron/gold, better food, TNT for quick logs/dirt than shipwrecks [2]. Chest sits at chunk-relative 9,9; found "mapless" via chunk position + surrounding-block tells [5][6].
- Ruined portal: damaged obsidian frame (sometimes crying obsidian, which can't be lit) + chest with gold, obsidian, flint and steel [7]. Only a *completable* one is an entry [4].
- Desert temple: 4 chests under the centre, guarded by a pressure plate + 9 TNT [8].
- Ranked filter: temple ≤5 chunks from spawn, ≥7 iron (or 4 iron + 3 diamonds), 3 lava pools nearby, river ≤6 chunks [26].
- Ranked desert-temple route — `status: draft (from learner's run, awaiting review)`; from runs/desert-temple (VOD times, RTA ≈ VOD − 2.9 s; details read from frames at 2–3 s spacing, unverified):
  - 0:03–0:12 spawn in sight of the temple; run to it and dig straight down through the centre of the orange/blue floor pattern (skips the stairs, lands beside the pressure plate, not on it).
  - 0:12–0:46 loot the 4 chests in the treasure room (Diamonds! ~0:30, Acquire Hardware ~0:38: iron/gold/diamonds/food); the trap TNT is taken, not set off. Climb out ~0:48.
  - 0:50–2:00 run to the savanna edge; use the TNT (+ pressure plate) to blow up trees for logs instead of punching them (explosions ~1:12, ~1:50).
  - 2:20–3:10 craft in the inventory: crafting table, tools, bucket, flint and steel.
  - 3:10–3:58 lava pool next to the river: bucket + water-cast portal (Hot Stuff ~3:42), light it ~3:57 → Nether 4:00 (RTA 3:57).
- Village: loot blacksmith(s), kill iron golem (3–5 iron), hay bales → food (Ranked golem always drops 4 iron [25]); a 10-obsidian blacksmith = instant portal [3].
- ≥7 iron covers pickaxe + bucket + flint and steel [2].

### Nether travel & portals
- 1 Nether block = 8 Overworld blocks; portal teleport takes 4 s in the portal [9][15].
- Any fire inside the frame lights it [9]. Lava ignites air next to flammable/wood blocks → "wood light" without flint [10][11]. Flint and steel is not required but is a big timesave [3].
- Ocean entry: boat-scout for underwater magma ravines (floating kelp with F3+B hints at one); mine flint from gravel while standing in a door air pocket [2].
- Village entry: lava pool, ruined portal, dig to underground lava (y ≤ 11), or blacksmith lava with ≥8 obsidian [3].
- Turn on F3 before entering the portal to microlens immediately [4].

### Bastions / Piglins & bartering
See `bastions.md`.

### Fortresses & blazes
- One structure per 432×432 region; fortress 2/5 vs bastion 3/5 [12]. Leave the bastion's region to find another structure [4].
- "Go east/west" is obsolete pre-1.16 advice: since 20w16a fortresses "generate evenly" via the region grid, so no axis bias in 1.16.1 [12]. Ranked: fortress origin ≤16 chunks from the intended bastion [26].
- Pie-ray: F3 pie chart (Tick→Level→Entities→Block Entities) shows a mob spawner; step across chunk borders to get its direction [4]. A treasure bastion's spawner gives false positives [4].
- Two sections: roofed nether-brick hallways (bad) vs open bridges / netherrack roof (good, where blaze spawners are) [4][13].
- Inside: stairs with nether wart at the bottom → go down; without → go up; lava-pool room links the sections [4][13].
- Spawnerless: lower render distance (e.g. 5 RD) so the 70 monster cap fills near you; preferred by top runners but more wither skeletons [4][13].
- Blazes: target within 48 blocks with line of sight; 3 s windup, then 3 fireballs, then 5 s cooldown [4]. Fire res blocks fireballs, not melee [4].
- Blaze bed: a bed exploded in the Nether clears blocks around a spawner [4][14].
- Rods: 6–7 rods; craft ~10 eyes first [4]. Build the first portal near the spawner so the 4 s animation overlaps spawns [15].

### Eyes of ender & strongholds
- Rings: ring 1 = 3 strongholds at 1,280–2,816 blocks from 0,0; ring 2 = 6 at 4,352–5,888; ring 3 = 10 at 7,424–8,960 [16].
- Eye flies ~12 blocks toward the nearest stronghold's staircase chunk; 20% chance to break per throw [17]. It points to chunk 0,0; staircase is centred at 4,~,4 [17].
- Some portals spawn with eyes already in frames; 12 eyes fill an empty one [17].

### The End & dragon
- Beds explode in the End/Nether (power 5, stronger than TNT's 4) [14]. Charged respawn anchors also explode outside the Nether [4][18].
- You spawn east of the island [4].
- Perch roll after each holding path: starts 1/13, denominator −1 per destroyed crystal down to 1/3; strafe chance drops with distance from the fountain [18][19].
- Resolved: per-roll perch chance is 1/(crystals+3), distance-independent; distance only lowers strafe chance (k=⌊d²/512⌋) [19]. [4]'s "farther = more perches" is the indirect effect: fewer strafes → more perch rolls per minute. Ranked standardises perch/strafe rolls (same for both players) [25].

## Strategy

### Overworld routing by seed type
- Ocean (shipwreck/buried treasure + ravine portal) is the 1.16 RSG meta: entries often < 2 min [2].
- Villages: slower/less consistent entry, still occasionally used in top runs [3].
- Ranked seeds are filtered ("good overworld and nether") and both players get the same seed [20].
- Seed type by lowest Elo in match: <600 village 55/shipwreck 15/DT 30; 600–1199 30/25/25 + RP 20; 1200+ 20% each incl. BT [26]. Overworld and Nether filtered from independent seeds (no Nether inference from overworld) [26].
- Intended bastion ≤14 chunks from 0,0 and ≥10 chunks closer than any other; its ramparts hold ≥3 iron + ≥5 obsidian [26].
- Pool ≈ 200,000 seeds, ~50,000 per bastion type; repeats have been recorded (learner, ranked player).

### Post-bastion → fortress
- Leave toward a different region; pie-ray for a spawner [4]. Fortress mobs only spawn near you, so E-ray is weaker for fortresses than bastions [4].
- Approach at low RD to boost spawnerless rates; risky in soul sand valleys (more mobs) [4][12].

### Blind travel
- 10–20 obsidian → blind: one portal mid-ring, then triangulate [15]. Ring-1 Nether blind coords ≈ (0,220) … (155,155) and their mirror points (~220 Nether-block radius) [4][21].
- ≥20 obsidian → double travel (fastest): portal anywhere, triangulate, go back, portal at the stronghold's Nether coords [15]. Top runs may use 1 eye ("perfect travel") and risk a wrong portal [15].
- Home portal: return through entry portal; more consistent, blind can be faster [15].
- Triangulation: throw, record angle (FOV 30 helps), move ~17.5 blocks perpendicular, throw again; distance ≈ 1000 / angle-difference° blocks [4]. Usually 2 eyes unless close [15].
- Ninjabrain Bot does Bayesian triangulation from F3+C angles, incl. blind-coord evaluation [22].
- Ninjabrain Bot is allowed and encouraged in Ranked (learner, ranked player) [27]. Ranked: 2nd eye throw never breaks [25].

### Stronghold navigation
- Dig down at staircase chunk 4,4 (4 blocks diagonal from NW corner) [4][17].
- All staircases lead up to the starter staircase; libraries are dead ends; portal room usually 5–7 rooms away [4].
- Hidden rooms only in 5-way rooms and only when facing −x/−z (north/west) from the entrance [4][16].
- Listen for lava popping / silverfish (subtitles) [4].

### Dragon fight
- One cycle: kill during one perch with beds/anchors so the dragon never sits; ≥4 explosives needed (3+1 or 4 bed) [18].
- Setup: obsidian/crying obsidian diagonal on N or S side of the fountain pillar; anchors need a blast-proof block under them [18].
- Wait N/S of the fountain (SW for a diagonal instaperch); far for fewer strafes, close if you need an instaperch [18].
- Perch tell: landing-approach pathing, then the head "snap" to face the fountain → pearl/run in [18]. F3+B hitboxes help time explosions [4][18].
- Trigger when the head passes over the bed; "+1" = a second explosion 0.5 s later on a low-HP dragon [18].
- If it lands: it leaves after >50 damage taken; deal ~50 with melee and finish with an explosive or charged axe hit (no crit bonus vs dragon) [18].
- Zero cycle (setup on a pillar, no perch wait) is more consistent on average than one cycle [23].
- Hunger reset (die after setting spawn, items in a 2-deep hole) refills HP/food [24].

## Ranked-specific (opponent, match clock, forfeits)
- 1.16.1 + Fabric; same seed, separate worlds; first to finish wins; standardized piglin trades and blaze rates; live opponent splits [20].
- Standardised RNG (seeded, same order for both): obsidian barter odds +~35%, ≥6 obsidian and exactly 3 pearl trades per 72 barters (8 gold blocks); blaze spawn timing/positions and rod drops; flint, food drops, eye breaks [25].
- Timer runs through deaths and pauses; stops only on forfeit or match win. Forfeit doesn't affect PB. On death: respawn or forfeit. The world can be fully reset at any point (learner, ranked player).

## Sources
1. MCSR Wiki, 1.16 RSG — https://mcsr.miraheze.org/wiki/116rsg
2. MCSR Wiki, Ocean — https://mcsr.miraheze.org/wiki/Ocean
3. MCSR Wiki, Village — https://mcsr.miraheze.org/wiki/Village
4. Metacor, Minecraft Speedrun Guide (last commit Nov 2022) — https://github.com/Metacor/Minecraft-Speedrun-Guide
5. MCSR Wiki, Mapless buried treasure — https://mcsr.miraheze.org/wiki/Mapless_buried_treasure
6. Minecraft Wiki, Buried Treasure — https://minecraft.wiki/w/Buried_Treasure
7. Minecraft Wiki, Ruined Portal — https://minecraft.wiki/w/Ruined_Portal
8. Minecraft Wiki, Desert Pyramid — https://minecraft.wiki/w/Desert_Pyramid
9. Minecraft Wiki, Nether Portal (block) — https://minecraft.wiki/w/Nether_Portal_(block)
10. Minecraft Wiki, Lava — https://minecraft.wiki/w/Lava
11. MCSR Wiki, Portals (woodlight videos) — https://mcsr.miraheze.org/wiki/Portals
12. Minecraft Wiki, Nether Fortress — https://minecraft.wiki/w/Nether_Fortress
13. MCSR Wiki, Nether fortress — https://mcsr.miraheze.org/wiki/Nether_fortress
14. Minecraft Wiki, Bed — https://minecraft.wiki/w/Bed
15. MCSR Wiki, Stronghold travel — https://mcsr.miraheze.org/wiki/Stronghold_travel
16. Minecraft Wiki, Stronghold — https://minecraft.wiki/w/Stronghold
17. Minecraft Wiki, Eye of Ender — https://minecraft.wiki/w/Eye_of_Ender
18. MCSR Wiki, One cycle — https://mcsr.miraheze.org/wiki/One_cycle
19. MCSR Wiki, Dragon fight mechanics — https://mcsr.miraheze.org/wiki/Dragon_fight_mechanics
20. MCSR Ranked mod page — https://modrinth.com/mod/mcsr-ranked
21. MCSR documents (Stronghold Ring Blind Coords) — https://www.minecraftspeedrunning.com/public-resources/documents
22. Ninjabrain Bot — https://github.com/Ninjabrain1/Ninjabrain-Bot
23. MCSR Wiki, Zero cycle — https://mcsr.miraheze.org/wiki/Zero_cycle
24. MCSR Wiki, Hunger resetting — https://mcsr.miraheze.org/wiki/Hunger_resetting
25. MCSR Ranked Wiki, RNG Standardization — https://wiki.mcsrranked.com/gameplay/rng
26. MCSR Ranked Wiki, Filtered Seeds — https://wiki.mcsrranked.com/gameplay/seed
27. MCSR Ranked Wiki, Rules (Legal Tools) — https://wiki.mcsrranked.com/gameplay/rules
