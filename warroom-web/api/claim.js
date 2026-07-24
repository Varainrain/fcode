import { kv, authed } from "../lib/kv.js";

// Workers poll this. LPOP is atomic, so two workers never get the same job.
export default async function handler(req, res) {
  if (!authed(req)) return res.status(401).json({ error: "bad key" });
  if (req.method !== "POST") return res.status(405).end();
  const raw = await kv("LPOP", "wr:queue");
  if (!raw) return res.json({ job: null });
  const job = JSON.parse(raw);
  const worker = String((req.body || {}).worker || "?").slice(0, 24);
  await kv("HSET", "wr:running", job.id,
           JSON.stringify({ job, worker, ts: Date.now() }));
  res.json({ job });
}
