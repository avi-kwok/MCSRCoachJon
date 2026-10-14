// Procedural 16x16 "dirt block" texture, drawn to a canvas and used as the
// tiled page background (like Minecraft's options-screen background).
// Nothing is copied from Mojang's textures: it's seeded noise over a dirt palette.

const PALETTE = ["#866043", "#6c4a30", "#593d29", "#9b7653", "#b9855c"];
// How often each palette entry is picked (mid-browns dominate, light flecks are rare).
const WEIGHTS = [0.38, 0.27, 0.17, 0.12, 0.06];

function rng(seed: number) {
  // mulberry32 - tiny deterministic PRNG so the texture is the same on every load
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function pick(r: number) {
  let acc = 0;
  for (let i = 0; i < WEIGHTS.length; i++) {
    acc += WEIGHTS[i];
    if (r < acc) return PALETTE[i];
  }
  return PALETTE[0];
}

/** Returns a PNG data URI of a 16x16 dirt tile, darkened by `shade` (0 = black, 1 = full). */
export function dirtTile(shade = 0.3, seed = 1337): string {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 16;
  const ctx = canvas.getContext("2d");
  if (!ctx) return "";
  const rand = rng(seed);
  for (let y = 0; y < 16; y++) {
    for (let x = 0; x < 16; x++) {
      ctx.fillStyle = pick(rand());
      ctx.fillRect(x, y, 1, 1);
    }
  }
  // A few 2-pixel dark "pebbles" to break up the noise like the real block.
  for (let i = 0; i < 7; i++) {
    const x = Math.floor(rand() * 15);
    const y = Math.floor(rand() * 16);
    ctx.fillStyle = "#4a3222";
    ctx.fillRect(x, y, 2, 1);
  }
  // Menu backgrounds are the texture drawn dark.
  ctx.fillStyle = `rgba(0,0,0,${1 - shade})`;
  ctx.fillRect(0, 0, 16, 16);
  return canvas.toDataURL("image/png");
}

/** Put the dirt tiles on :root as CSS variables. */
export function installDirtBackground() {
  const root = document.documentElement.style;
  root.setProperty("--dirt-dark", `url(${dirtTile(0.3)})`);
  root.setProperty("--dirt", `url(${dirtTile(0.62, 4242)})`);
}
