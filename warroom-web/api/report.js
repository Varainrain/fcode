import { kv, authed } from "../lib/kv.js";

const K = 16;
const DEFAULT_ELO = 1500;

async function getElo(bot) {
  const v = await kv("HGET", "wr:elo", bot);
  return v === null ? DEFAULT_ELO : parseFloat(v);
}

export default async function handler(req, res) {
  if (!authed(req)) return res.status(401).json({ error: "bad key" });
  if (req.method !== "POST") return res.status(405).end();
  const { id, a, b, games, worker } = req.body || {};
  if (!id || !a || !b || !Array.isArray(games))
    return res.status(400).json({ error: "bad report" });

  let eloA = await getElo(a);
  let eloB = await getElo(b);
  let winsA = 0, winsB = 0;
  for (const g of games) {
    const scoreA = g.winner === a ? 1 : g.winner === b ? 0 : 0.5;
    const expA = 1 / (1 + 10 ** ((eloB - eloA) / 400));
    eloA += K * (scoreA - expA);
    eloB += K * ((1 - scoreA) - (1 - expA));
    if (g.winner === a) winsA++;
    else if (g.winner === b) winsB++;
  }
  const bump = async (bot, w, l) => {
    const cur = await kv("HGET", "wr:stats", bot);
    const s = cur ? JSON.parse(cur) : { w: 0, l: 0 };
    s.w += w; s.l += l;
    await kv("HSET", "wr:stats", bot, JSON.stringify(s));
  };
  await Promise.all([
    kv("HSET", "wr:elo", a, eloA.toFixed(2)),
    kv("HSET", "wr:elo", b, eloB.toFixed(2)),
    bump(a, winsA, winsB),
    bump(b, winsB, winsA),
    kv("HDEL", "wr:running", id),
    kv("LPUSH", "wr:matches", JSON.stringify({
      id, a, b, winsA, winsB, games, worker, ts: Date.now(),
    })),
    kv("LTRIM", "wr:matches", 0, 199),
  ]);
  res.json({ ok: true });
}
