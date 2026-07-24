import { kv, authed } from "../lib/kv.js";

export default async function handler(req, res) {
  if (!authed(req)) return res.status(401).json({ error: "bad key" });
  const [eloRaw, statsRaw, queue, runningRaw, matches] = await Promise.all([
    kv("HGETALL", "wr:elo"),
    kv("HGETALL", "wr:stats"),
    kv("LRANGE", "wr:queue", 0, 24),
    kv("HGETALL", "wr:running"),
    kv("LRANGE", "wr:matches", 0, 39),
  ]);
  const pairs = (flat) => {
    const o = {};
    for (let i = 0; i < (flat || []).length; i += 2) o[flat[i]] = flat[i + 1];
    return o;
  };
  const elo = pairs(eloRaw);
  const stats = pairs(statsRaw);
  const bots = Object.keys(elo)
    .map((b) => ({
      bot: b,
      elo: Math.round(parseFloat(elo[b])),
      ...(stats[b] ? JSON.parse(stats[b]) : { w: 0, l: 0 }),
    }))
    .sort((a, b) => b.elo - a.elo);
  // prune running entries whose heartbeat is stale (worker died mid-match)
  const running = [];
  const now = Date.now();
  const runPairs = pairs(runningRaw);
  for (const id of Object.keys(runPairs)) {
    const j = JSON.parse(runPairs[id]);
    if (now - j.ts > 30 * 60 * 1000) {
      await kv("HDEL", "wr:running", id);
      await kv("RPUSH", "wr:queue", JSON.stringify(j.job)); // requeue
    } else running.push(j);
  }
  res.json({
    bots,
    queue: (queue || []).map(JSON.parse),
    running,
    matches: (matches || []).map(JSON.parse),
  });
}
