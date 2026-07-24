# EREBUS Private Arena

Our own battle site: queue fights between any of our bots, private ELO
ladder, match history. The site never sees bot code — games run on OUR
machines via `warroom_worker.py` (that's what keeps the gatekept bots
private: every match on the official server, rated or unrated, is publicly
listed with downloadable replays — it's how we scouted lastpopperian_).

## One-time setup (one person, ~5 minutes)

1. Vercel → New Project → import this repo → set **Root Directory** to
   `warroom-web`. (Repo must stay private, obviously.)
2. In the project: Storage → create a **KV / Upstash Redis** store and
   connect it (this injects `KV_REST_API_URL` / `KV_REST_API_TOKEN`).
3. Settings → Environment Variables → add `WARROOM_KEY` = a long random
   string. This is the shared team password — DM it to the other two.
4. Deploy. Open the URL, enter the key, done.

## Everyone

- Open the site, enter the war room key once (it's remembered).
- To make battles actually run, at least one of us keeps a worker going:

```bash
python warroom_worker.py https://YOUR-ARENA.vercel.app YOUR_WARROOM_KEY
```

- Bot names on the site = folder names in `bots/`. `git pull` before
  starting your worker so you're running everyone's latest.
- Multiple workers at once is fine (job claiming is atomic).

## Notes

- ELO starts at 1500, K=16 per game. It's OUR ladder — decoupled from the
  public one by design.
- A worker that dies mid-match: the job re-queues automatically after 30
  minutes.
- Measurement standard baked into the worker: `--tle 10`, both sides,
  full map pool (or the 6-map fast screen).
