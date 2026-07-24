import { kv, authed } from "../lib/kv.js";

export default async function handler(req, res) {
  if (!authed(req)) return res.status(401).json({ error: "bad key" });
  if (req.method !== "POST") return res.status(405).end();
  const { a, b, maps, seeds, by } = req.body || {};
  if (!a || !b || a === b) return res.status(400).json({ error: "need two different bots" });
  const job = {
    id: Math.random().toString(36).slice(2, 10),
    a: String(a).trim(),
    b: String(b).trim(),
    maps: maps === "fast" ? "fast" : "full",
    seeds: Math.min(4, Math.max(1, parseInt(seeds) || 1)),
    by: String(by || "?").slice(0, 24),
    ts: Date.now(),
  };
  await kv("RPUSH", "wr:queue", JSON.stringify(job));
  res.json({ ok: true, id: job.id });
}
