// Upstash Redis REST helper (Vercel KV integration injects these env vars).
export async function kv(...cmd) {
  const r = await fetch(process.env.KV_REST_API_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.KV_REST_API_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(cmd),
  });
  if (!r.ok) throw new Error(`kv ${cmd[0]}: ${r.status}`);
  const d = await r.json();
  return d.result;
}

export function authed(req) {
  const key = req.headers["x-warroom-key"];
  return key && process.env.WARROOM_KEY && key === process.env.WARROOM_KEY;
}
