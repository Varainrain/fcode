"""IC3D WAR ROOM v2 — instant, minimal, dark.

Run:  python dashboard.py        open  http://localhost:8642

Speed: a background worker refreshes status/ladder/matches into memory every
30s — page loads serve from warm cache instantly. Completed match details
cache permanently. Rating history is appended to rating_history.csv on every
refresh and rendered as a sparkline.
"""
import concurrent.futures as cf
import csv
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8642
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
HIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rating_history.csv")
SNAP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_cache.json")

CACHE = {"status": {}, "ladder": [], "matches": [], "live": [], "ts": 0,
         "team_matches": [], "git": {}}
MATCH_CACHE = {}
MY_ELO = {}   # match_id -> signed ELO delta for IC3D (rated only)
LOCK = threading.Lock()
MY_TEAM = "Erebus"        # self-corrects from live `fcode status` anyway
NEW_TEAM = "lastpopperian_"  # the rival panel — change to whoever you're scouting
# repo panel: this file lives IN the team repo, so point at our own folder
REPO = os.path.dirname(os.path.abspath(__file__))


def fcode(*args, timeout=60):
    env = {**os.environ, "COLUMNS": "220"}
    # utf-8 + replace: the CLI emits utf-8 (team names, box tables); Windows'
    # default cp1252 decode crashes the reader thread and yields stdout=None
    out = subprocess.run(["fcode", *args], capture_output=True,
                         encoding="utf-8", errors="replace",
                         timeout=timeout, env=env)
    # normalize unicode box-table columns to ascii pipes for the row regexes
    return ((out.stdout or "") + (out.stderr or "")).replace("│", "|")


def parse_status(t):
    g = lambda p: (re.search(p, t) or [None, ""])[1]
    return {"team": g(r"Team:\s*(\S+)"), "rating": g(r"Rating:\s*(\d+)"),
            "tier": g(r"Rating:\s*\d+\s*\((\w+)\)"),
            "rank": g(r"Rank:\s*#(\d+)"), "of": g(r"Rank:\s*#\d+ of (\d+)"),
            "active_bot": g(r"Active bot:\s*(.+)"),
            "last10": g(r"Last 10:\s*(.+)"), "matches": g(r"(\d+) matches played")}


def parse_ladder(t):
    rows = []
    for line in t.splitlines():
        m = re.match(r"\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|", line)
        if m:
            rows.append({"rank": int(m[1]), "team": m[2],
                         "rating": int(m[3]), "matches": int(m[4])})
    return rows


def parse_matches(t):
    rows = []
    for line in t.splitlines():
        m = re.match(
            r"\|\s*([0-9a-f-]{36})\s*\|\s*(\S+)\s*\|\s*(.+?)\s*\|\s*(\d+)-(\d+)\s*\|"
            r"\s*(.+?)\s*\|\s*(\w+)\s*\|\s*([\d: -]+)\|", line)
        if m:
            rows.append({"id": m[1], "type": m[2], "a": m[3],
                         "sa": int(m[4]), "sb": int(m[5]), "b": m[6],
                         "status": m[7], "date": m[8].strip()})
    return rows


def enrich_elo(matches):
    """Fetch and cache the signed ELO delta for IC3D on each complete rated
    match. Cached permanently so we hit `match info` at most once each."""
    todo = [m for m in matches if m["type"] == "ladder"
            and m["status"] == "complete" and m["id"] not in MY_ELO]
    for m in todo[:8]:   # bounded per cycle so the cache stays snappy
        d = get_match(m["id"])
        if d.get("elo_a") is None:
            continue
        mine = d["elo_a"] if m["a"] == MY_TEAM else d["elo_b"]
        try:
            MY_ELO[m["id"]] = round(float(mine))   # whole numbers, like the site
        except (TypeError, ValueError):
            pass


def load_snapshot():
    """Warm the cache from the last run's snapshot so a fresh server renders
    instantly with last-known data while the first live refresh runs."""
    try:
        with open(SNAP, encoding="utf-8") as f:
            d = json.load(f)
        with LOCK:
            for k in ("status", "ladder", "matches", "live", "team_matches",
                      "git", "ts"):
                if k in d:
                    CACHE[k] = d[k]
            MY_ELO.update({k: v for k, v in d.get("elo", {}).items()})
    except Exception:
        pass


def save_snapshot():
    try:
        with LOCK:
            d = {k: CACHE[k] for k in ("status", "ladder", "matches", "live",
                                       "team_matches", "git", "ts")}
            d["elo"] = dict(MY_ELO)
        tmp = SNAP + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, SNAP)
    except Exception:
        pass


def refresher():
    while True:
        try:
            # all five CLI feeds in parallel: fresh data in one call's latency
            with cf.ThreadPoolExecutor(max_workers=5) as ex:
                fst = ex.submit(fcode, "status")
                flad = ex.submit(fcode, "ladder")
                fms = ex.submit(fcode, "match", "list", "--mine", "--limit", "60")
                flive = ex.submit(fcode, "match", "list", "--limit", "40")
                ftm = ex.submit(fcode, "match", "list", "--team", NEW_TEAM,
                                "--limit", "18")
            st = parse_status(fst.result())
            # publish the fresh feed FIRST so the live-now section never
            # waits on the (slow) per-match ELO enrichment below
            with LOCK:
                CACHE.update(status=st, ladder=parse_ladder(flad.result()),
                             matches=parse_matches(fms.result()),
                             live=parse_matches(flive.result()),
                             team_matches=parse_matches(ftm.result()),
                             ts=time.time())
            save_snapshot()
            ms = CACHE["matches"]
            enrich_elo(ms)
            gs = git_status()
            with LOCK:
                CACHE["git"] = gs
            save_snapshot()
            if st.get("rating"):
                new = not os.path.exists(HIST)
                with open(HIST, "a", newline="") as f:
                    w = csv.writer(f)
                    if new:
                        w.writerow(["ts", "rating", "rank"])
                    w.writerow([int(time.time()), st["rating"], st["rank"]])
        except Exception:
            import traceback
            with open(os.path.join(os.path.dirname(HIST), "dashboard.log"),
                      "a", encoding="utf-8") as f:
                f.write(time.strftime("%H:%M:%S ") + traceback.format_exc() + "\n")
        time.sleep(30)


def project():
    """Expected rating + rank in 24h from recent per-match ELO momentum.
    Uses the mean of the last ~25 rated ELO deltas × an estimated matches/
    day cadence, projected onto the current ladder."""
    deltas = [MY_ELO[k] for k in list(MY_ELO)][-25:]
    if len(deltas) < 4:
        return None
    avg = sum(deltas) / len(deltas)
    with LOCK:
        matches = list(CACHE["matches"])
        ladder = list(CACHE["ladder"])
        cur = CACHE["status"].get("rating")
    # cadence: rated matches in the last 6h -> per-24h rate
    rated_ts = []
    for m in matches:
        if m["type"] != "ladder":
            continue
        try:
            rated_ts.append(time.mktime(time.strptime(
                "2026-" + m["date"] if len(m["date"]) < 12 else m["date"],
                "%Y-%m-%d %H:%M:%S")))
        except Exception:
            pass
    per_day = 40  # conservative default cadence
    if len(rated_ts) >= 2:
        span_h = max(1.0, (max(rated_ts) - min(rated_ts)) / 3600.0)
        per_day = min(120, max(10, len(rated_ts) / span_h * 24))
    if not cur:
        return None
    proj = int(int(cur) + avg * per_day)
    # where proj lands on the ladder (excluding ourselves)
    rank = 1
    for r in ladder:
        if r["team"] != MY_TEAM and r["rating"] > proj:
            rank += 1
    return {"rating": proj, "rank": rank, "avg_elo": round(avg, 1),
            "per_day": int(per_day)}


def get_match(mid):
    if mid in MATCH_CACHE:
        return MATCH_CACHE[mid]
    t = fcode("match", "info", mid)
    games = []
    for line in t.splitlines():
        m = re.match(r"\|\s*(\d+)\s*\|\s*(\w+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(\d+)\s*\|", line)
        if m:
            games.append({"n": int(m[1]), "map": m[2], "winner": m[3].strip(),
                          "cond": m[4].strip(), "turns": int(m[5])})
    elo = re.search(r"ELO:\s*A:\s*([+\-\d.]+)\s*B:\s*([+\-\d.]+)", t)
    d = {"games": games, "elo_a": elo[1] if elo else None,
         "elo_b": elo[2] if elo else None}
    if "complete" in t:
        MATCH_CACHE[mid] = d
    return d


def rating_history():
    if not os.path.exists(HIST):
        return []
    with open(HIST) as f:
        return [{"ts": int(r["ts"]), "rating": int(r["rating"])}
                for r in csv.DictReader(f)][-300:]


def git_status():
    """Branch + recent commits of the merged-team bot repo. Fetches so
    teammates' pushes show up; every call is bounded and non-fatal."""
    if not os.path.isdir(os.path.join(REPO, ".git")):
        return {"error": "repo not cloned"}

    def g(*a, timeout=25):
        try:
            return subprocess.run(["git", "-C", REPO, *a], capture_output=True,
                                  text=True, timeout=timeout).stdout.strip()
        except Exception:
            return ""
    try:
        subprocess.run(["git", "-C", REPO, "fetch", "--all", "--quiet"],
                       capture_output=True, timeout=25)
    except Exception:
        pass
    branch = g("rev-parse", "--abbrev-ref", "HEAD") or "?"
    # behind = commits on origin/main we don't have yet (teammates pushed)
    behind = g("rev-list", "--count", "HEAD..origin/main") or ""
    log = g("log", "--all", "--date=relative", "--pretty=%h\x1f%an\x1f%ad\x1f%s",
            "-15")
    commits = []
    for line in log.splitlines():
        p = line.split("\x1f")
        if len(p) == 4:
            commits.append({"h": p[0], "an": p[1], "ad": p[2], "s": p[3]})
    return {"branch": branch, "behind": behind, "commits": commits}


def team_id(name):
    t = fcode("team", "search", name)
    for line in t.splitlines():
        if name.lower() in line.lower():
            m = UUID_RE.search(line)
            if m:
                return m.group(0)
    return None


def queue_unrated(name, count, maps):
    tid = team_id(name)
    if not tid:
        return {"error": f"team not found: {name}"}
    queued, errors = [], []
    for _ in range(min(count, 5)):
        args = ["match", "unrated", tid]
        for mp in maps:
            args += ["--map", mp]
        t = fcode(*args)
        m = UUID_RE.search(t)
        if m:
            queued.append(m.group(0))
        else:
            errors.append(t.strip()[-160:])
            break
    return {"queued": queued, "errors": errors}


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IC3D</title><style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800&display=swap');
*{box-sizing:border-box;margin:0}
:root{color-scheme:dark}
body{background:#000;color:#fff;font-family:Inter,-apple-system,'Segoe UI',sans-serif;
 -webkit-font-smoothing:antialiased;letter-spacing:.01em}
.wrap{max-width:1720px;margin:0 auto;padding:36px 40px}
header{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:40px}
.logo{font-weight:800;font-size:15px;letter-spacing:.35em}
.sub{color:#8a8a8a;font-size:12px;font-weight:300;letter-spacing:.15em;text-transform:uppercase}
.hero{display:grid;grid-template-columns:repeat(5,1fr);gap:24px;margin-bottom:32px;align-items:end}
.metric .v{font-size:52px;font-weight:200;line-height:1;letter-spacing:-.02em}
.metric .v b{font-weight:800}
.metric .l{color:#8a8a8a;font-size:11px;letter-spacing:.25em;text-transform:uppercase;margin-top:10px}
.up{color:#4ade80}.down{color:#f87171}
section{margin-bottom:44px}
h2{font-size:12px;font-weight:600;letter-spacing:.3em;text-transform:uppercase;color:#8a8a8a;
 margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid #1a1a1a;display:flex;justify-content:space-between;align-items:center}
table{width:100%;border-collapse:collapse;font-size:14px;font-weight:300}
td,th{padding:10px 8px;text-align:left}
th{color:#555;font-size:10px;letter-spacing:.2em;text-transform:uppercase;font-weight:600}
tr{border-bottom:1px solid #111}tbody tr{transition:background .2s}tbody tr:hover{background:#0a0a0a}
.me{background:#0d1512!important}
.pill{display:inline-block;padding:2px 12px;border-radius:100px;font-size:10px;font-weight:600;letter-spacing:.15em}
.pw{background:#0d2818;color:#4ade80}.pl{background:#2a0d0d;color:#f87171}
.plive{background:#2a230d;color:#fbbf24;animation:pulse 1.4s infinite}
@keyframes pulse{50%{opacity:.45}}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:56px}
button{background:#fff;color:#000;border:0;padding:9px 24px;font-family:inherit;font-weight:600;
 font-size:11px;letter-spacing:.25em;text-transform:uppercase;border-radius:4px;cursor:pointer;transition:all .2s}
button:hover{background:#d0d0d0}
select,input{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:8px 10px;
 font-family:inherit;font-size:12px;font-weight:300;transition:border .2s}
select:focus,input:focus{border-color:#555;outline:0}
.battlebar{display:flex;gap:10px;align-items:center;background:#0a0a0a;border:1px solid #161616;
 border-radius:8px;padding:10px 14px;margin-bottom:36px;flex-wrap:wrap}
.battlebar .lbl{color:#555;font-size:10px;letter-spacing:.25em;text-transform:uppercase;font-weight:600;margin-right:4px}
#battle-log{font-size:12px;color:#8a8a8a;font-weight:300;flex-basis:100%}
#battle-log .bq{color:#fbbf24}#battle-log .bw{color:#4ade80}#battle-log .bl{color:#f87171}
.games-row td{padding:0 8px 14px;color:#8a8a8a;font-size:13px;font-weight:300}
a{color:#fff;text-decoration:none;border-bottom:1px solid #333;transition:border .2s}
a:hover{border-color:#fff}
.expander{cursor:pointer;color:#555;border:0;background:none;padding:0;letter-spacing:0}
.expander:hover{color:#fff}
#spark{width:100%;height:64px}
.skel{animation:pulse 1.2s infinite;background:#111;border-radius:4px;height:52px;width:170px}
.win-cell{color:#4ade80;font-weight:400}.loss-cell{color:#f87171;font-weight:400}
@media(max-width:1100px){.grid2{grid-template-columns:1fr}.hero{grid-template-columns:repeat(2,1fr)}}
</style></head><body><div class="wrap">
<header><div class="logo">IC3D</div><div class="sub">Florent Code League · War Room</div></header>
<div class="hero">
 <div class="metric"><div class="v" id="m-rating"><div class="skel"></div></div><div class="l">Rating <span id="m-proj" style="color:#4ade80"></span></div></div>
 <div class="metric"><div class="v" id="m-rank"></div><div class="l">Rank <span id="m-projrank" style="color:#8a8a8a"></span></div></div>
 <div class="metric"><div class="v" id="m-last10"></div><div class="l">Last 10</div></div>
 <div class="metric"><div class="v" id="m-bot" style="font-size:22px;font-weight:300"></div><div class="l">Active Bot</div></div>
 <div class="metric"><canvas id="spark"></canvas><div class="l">Trajectory</div></div>
</div>
<div class="battlebar">
 <span class="lbl">Battle</span>
 <select id="opp"></select>
 <select id="count"><option value="1">x1</option><option value="3">x3</option><option value="5" selected>x5</option></select>
 <input id="maps" placeholder="maps (optional)" size="18">
 <button onclick="battle()">Launch</button>
 <div id="battle-log"></div>
</div>
<div class="grid2">
<section><h2><span>Rival &middot; <span id="nt-name">Besvikomat</span></span><span id="nt-rank" class="sub"></span></h2>
 <div id="nt-race" class="sub" style="margin-bottom:12px"></div>
 <table id="teamfeed"><tbody></tbody></table></section>
<section><h2><span>Repo &middot; oogway-bot</span><span id="git-branch" class="sub"></span></h2><table id="gitlog"><tbody></tbody></table></section>
</div>
<section><h2><span>Live Now &middot; Ladder-wide</span><span id="live-note" class="sub"></span></h2><table id="livefeed"><tbody></tbody></table></section>
<section><h2>My Matches</h2><table id="hist"><tbody></tbody></table></section>
<div class="grid2">
<section><h2>Ladder</h2><table id="ladder"><tbody></tbody></table></section>
<section><h2>Head to Head</h2><table id="oppo"><tbody></tbody></table></section>
</div>
</div><script>
let MY="Oogway";  // self-corrects from live status in load()
let tracked={};
const j=async(u,o)=>(await fetch(u,o)).json();
function won(m){return (m.a===MY&&m.sa>m.sb)||(m.b===MY&&m.sb>m.sa)}
function spark(h){
 const c=document.getElementById('spark'),x=c.getContext('2d');
 const W=c.width=c.offsetWidth*2,H=c.height=128;
 x.clearRect(0,0,W,H);
 if(h.length<2)return;
 const rs=h.map(p=>p.rating),mn=Math.min(...rs)-5,mx=Math.max(...rs)+5;
 x.beginPath();x.strokeStyle='#4ade80';x.lineWidth=2.5;
 h.forEach((p,i)=>{const px=i/(h.length-1)*(W-16)+8,py=H-8-(p.rating-mn)/(mx-mn)*(H-16);
   i?x.lineTo(px,py):x.moveTo(px,py)});
 x.stroke();
}
async function load(){
 const d=await j('/api/all');
 const s=d.status;
 if(!s.rating){setTimeout(load,3000);return}  // cache still warming up — keep skeletons, retry fast
 if(d.age>45)setTimeout(load,5000);  // snapshot data from a past run — re-poll fast until fresh
 if(s.team)MY=s.team;  // track whatever team the CLI is on
 document.getElementById('m-rating').innerHTML=`<b>${s.rating}</b> <span style="font-size:16px;color:#8a8a8a">${s.tier||''}</span>`;
 document.getElementById('m-rank').innerHTML=`<b>#${s.rank}</b><span style="font-size:20px;color:#8a8a8a">/${s.of}</span>`;
 const pj=d.projection;
 if(pj){const dir=pj.rating>=+s.rating?'up':'down';
  document.getElementById('m-proj').innerHTML=`<span class="${dir}">&rarr; ${pj.rating} 24h</span>`;
  document.getElementById('m-projrank').innerHTML=`&rarr; #${pj.rank}`;
  document.getElementById('m-proj').title=`avg ${pj.avg_elo} ELO/match &middot; ~${pj.per_day} rated/day`;}
 const l10=s.last10||'';const w=(l10.match(/(\\d+)W/)||[0,0])[1];
 document.getElementById('m-last10').innerHTML=`<span class="${+w>=5?'up':'down'}" style="font-size:36px">${l10.replace(/\\s+/g,' ')}</span>`;
 document.getElementById('m-bot').textContent=(s.active_bot||'').split('(')[0].trim();
 spark(d.history);
 // GLOBAL live feed (all teams): in-progress first, then most recent
 const glive=(d.live||[]).filter(m=>m.status!=='complete');
 const grecent=(d.live||[]).filter(m=>m.status==='complete').slice(0,10);
 document.getElementById('live-note').textContent=glive.length?glive.length+' in progress':'ladder idle';
 document.getElementById('livefeed').innerHTML='<tbody><tr><th>Time</th><th>Type</th><th>Match</th><th>Score</th></tr>'+
  glive.map(m=>{const mine=m.a===MY||m.b===MY;
   return `<tr ${mine?'class="me"':''}><td style="color:#555">${m.date.slice(11)}</td><td style="color:#555">${m.type}</td>`+
   `<td>${m.a} <span style="color:#555">vs</span> ${m.b} <span class="pill plive">LIVE</span></td>`+
   `<td>&mdash;</td></tr>`}).join('')+
  grecent.map(m=>{const mine=m.a===MY||m.b===MY;
   return `<tr ${mine?'class="me"':''}><td style="color:#555">${m.date.slice(11)}</td><td style="color:#555">${m.type}</td>`+
   `<td>${m.a} <span style="color:#555">vs</span> ${m.b}</td>`+
   `<td style="font-weight:600">${m.sa} &ndash; ${m.sb}</td></tr>`}).join('')+'</tbody>';
 // My matches with per-match ELO
 const elo=d.elo||{};
 const running=d.matches.filter(m=>m.status!=='complete');
 const done=d.matches.filter(m=>m.status==='complete');
 function eloCell(m){let e=elo[m.id];if(e===undefined)return '<td></td>';
  e=Math.round(e);const cls=e>=0?'up':'down';return `<td class="${cls}" style="font-weight:600">${e>=0?'+':''}${e}</td>`}
 document.getElementById('hist').innerHTML='<tbody><tr><th>Date</th><th>Type</th><th>Match</th><th>Score</th><th>ELO</th><th></th></tr>'+
  running.map(m=>`<tr><td style="color:#555">${m.date.slice(5)}</td><td style="color:#555">${m.type}</td>`+
   `<td>${m.a} <span style="color:#555">vs</span> ${m.b} <span class="pill plive">LIVE</span></td><td>&mdash;</td><td></td><td></td></tr>`).join('')+
  done.map(m=>{const w=won(m);
   return `<tr><td style="color:#555">${m.date.slice(5)}</td><td style="color:#555">${m.type}</td>`+
   `<td>${m.a} <span style="color:#555">vs</span> ${m.b} <span class="pill ${w?'pw':'pl'}">${w?'W':'L'}</span></td>`+
   `<td style="font-weight:600">${m.sa} &ndash; ${m.sb}</td>`+eloCell(m)+
   `<td><button class="expander" onclick="expand('${m.id}')">&#9662; games</button></td></tr>`+
   `<tr id="x-${m.id}" class="games-row" style="display:none"><td colspan="6"></td></tr>`}).join('')+'</tbody>';
 // TEAM (Oogway) — rank, title race, live/recent matches
 const NT=d.new_team||'Oogway';document.getElementById('nt-name').textContent=NT;
 const lad=d.ladder||[];const ntRow=lad.find(r=>r.team===NT);const meRow=lad.find(r=>r.team===MY);
 if(ntRow){document.getElementById('nt-rank').innerHTML=`#${ntRow.rank} &middot; ${ntRow.rating}`;
  if(meRow){const gap=ntRow.rating-meRow.rating;
   document.getElementById('nt-race').innerHTML=gap>0
    ?`<span class="down">${gap} ahead of you</span> &middot; close it for #1`
    :`<span class="up">${-gap} behind you</span>`;}}
 const tm=d.team_matches||[];
 const tlive=tm.filter(m=>m.status!=='complete'),tdone=tm.filter(m=>m.status==='complete').slice(0,10);
 document.getElementById('teamfeed').innerHTML='<tbody>'+
  tlive.map(m=>`<tr><td style="color:#555">${m.date.slice(11)}</td><td>${m.a} <span style="color:#555">vs</span> ${m.b} <span class="pill plive">LIVE</span></td><td>&mdash;</td></tr>`).join('')+
  tdone.map(m=>{const w=(m.a===NT&&m.sa>m.sb)||(m.b===NT&&m.sb>m.sa);
   return `<tr><td style="color:#555">${m.date.slice(5)}</td><td>${m.a} <span style="color:#555">vs</span> ${m.b} <span class="pill ${w?'pw':'pl'}">${w?'W':'L'}</span></td><td style="font-weight:600">${m.sa} &ndash; ${m.sb}</td></tr>`}).join('')+'</tbody>';
 // REPO — branch + recent commits (fetched from the clone)
 const gt=d.git||{};
 if(gt.error){document.getElementById('git-branch').textContent=gt.error;document.getElementById('gitlog').innerHTML='';}
 else{let bl=gt.branch||'?';if(+gt.behind>0)bl+=` &middot; ${gt.behind} behind`;
  document.getElementById('git-branch').innerHTML=bl;
  document.getElementById('gitlog').innerHTML='<tbody>'+(gt.commits||[]).map(c=>
   `<tr><td style="color:#555;font-family:monospace">${c.h}</td><td>${c.s.replace(/</g,'&lt;')}</td><td style="color:#777;white-space:nowrap">${c.an}</td><td style="color:#555;text-align:right;white-space:nowrap">${c.ad}</td></tr>`).join('')+'</tbody>';}
 document.getElementById('ladder').innerHTML='<tbody><tr><th>#</th><th>Team</th><th style="text-align:right">Rating</th></tr>'+
  d.ladder.slice(0,12).map(r=>
  `<tr class="${r.team===MY?'me':''}"><td style="color:#555">${String(r.rank).padStart(2,'0')}</td><td>${r.team}</td><td style="text-align:right;font-weight:600">${r.rating}</td></tr>`).join('')+'</tbody>';
 const agg={};
 for(const m of done){const o=m.a===MY?m.b:m.a;agg[o]=agg[o]||{s:0,sl:0,g:0,gl:0};
  const mg=m.a===MY?m.sa:m.sb,og=m.a===MY?m.sb:m.sa;
  mg>og?agg[o].s++:agg[o].sl++;agg[o].g+=mg;agg[o].gl+=og}
 document.getElementById('oppo').innerHTML='<tbody><tr><th>Opponent</th><th>Series</th><th>Games</th><th style="text-align:right">Game %</th></tr>'+
  Object.entries(agg).sort((a,b)=>(b[1].g+b[1].gl)-(a[1].g+a[1].gl)).map(([o,x])=>{
   const pct=Math.round(100*x.g/(x.g+x.gl));
   return `<tr><td>${o}</td><td class="${x.s>=x.sl?'win-cell':'loss-cell'}">${x.s} &ndash; ${x.sl}</td>`+
   `<td class="${x.g>=x.gl?'win-cell':'loss-cell'}">${x.g} &ndash; ${x.gl}</td>`+
   `<td style="text-align:right;color:${pct>=50?'#4ade80':'#f87171'}">${pct}%</td></tr>`}).join('')+'</tbody>';
 const sel=document.getElementById('opp');
 if(!sel.options.length)sel.innerHTML=d.ladder.filter(r=>r.team!==MY&&r.rating>0).map(r=>`<option>${r.team}</option>`).join('');
 updateLog(d.matches);
}
function updateLog(ms){
 const ids=Object.keys(tracked);if(!ids.length)return;
 const log=document.getElementById('battle-log');
 log.innerHTML=ids.map(id=>{
  const m=ms.find(x=>x.id===id);
  if(!m)return `<span class="bq">&#9676; queued ${id.slice(0,8)}</span>`;
  if(m.status!=='complete')return `<span class="bq">&#9654; LIVE ${m.a} vs ${m.b}</span>`;
  const w=won(m);
  return `<span class="${w?'bw':'bl'}">${w?'&#10003; WON':'&#10007; LOST'} ${m.sa}&ndash;${m.sb} vs ${m.a===MY?m.b:m.a}</span>`;
 }).join('&nbsp;&nbsp;&middot;&nbsp;&nbsp;');
}
async function expand(id){
 const row=document.getElementById('x-'+id);
 if(row.style.display!=='none'){row.style.display='none';return}
 row.style.display='';row.firstChild.textContent='...';
 const d=await j('/api/match/'+id);
 row.firstChild.innerHTML=d.games.map(g=>
  `<span style="color:#fff">${g.map}</span> &rarr; ${g.winner} &middot; ${g.cond} &middot; t${g.turns} `+
  `&nbsp;<a target="_blank" href="https://game.staging.code.florent.vc/visualiser?matchId=${id}&game=${g.n}">replay</a>`).join('&nbsp;&nbsp;|&nbsp;&nbsp;')+
  (d.elo_a?`&nbsp;&nbsp;&middot;&nbsp;&nbsp;ELO ${d.elo_a} / ${d.elo_b}`:'');
}
async function battle(){
 const log=document.getElementById('battle-log');log.textContent='launching...';
 const r=await j('/api/battle',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({team:opp.value,count:+count.value,
   maps:document.getElementById('maps').value.split(',').map(s=>s.trim()).filter(Boolean)})});
 tracked={};(r.queued||[]).forEach(q=>tracked[q]=1);
 log.textContent=(r.queued||[]).length+' queued'+((r.errors||[]).length?' / ERR '+r.errors.join(' '):'')+(r.error?' / '+r.error:'');
 let n=0;const t=setInterval(async()=>{await load();if(++n>20)clearInterval(t)},15000);
}
load();setInterval(load,30000);
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        p = urllib.parse.urlparse(self.path)
        try:
            if p.path == "/":
                self._send(PAGE, "text/html; charset=utf-8")
            elif p.path == "/api/all":
                proj = project()
                with LOCK:
                    self._send({"status": CACHE["status"], "ladder": CACHE["ladder"],
                                "matches": CACHE["matches"], "live": CACHE["live"],
                                "elo": dict(MY_ELO), "projection": proj,
                                "age": time.time() - CACHE["ts"],
                                "history": rating_history(),
                                "team_matches": CACHE["team_matches"],
                                "git": CACHE["git"], "new_team": NEW_TEAM})
            elif p.path.startswith("/api/match/"):
                self._send(get_match(p.path.rsplit("/", 1)[1]))
            else:
                self.send_error(404)
        except Exception as e:
            self._send({"error": str(e)})

    def do_POST(self):
        if self.path == "/api/battle":
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                self._send(queue_unrated(body.get("team", ""),
                                         int(body.get("count", 1)),
                                         body.get("maps", [])))
            except Exception as e:
                self._send({"error": str(e)})
        else:
            self.send_error(404)


if __name__ == "__main__":
    load_snapshot()
    threading.Thread(target=refresher, daemon=True).start()
    print(f"IC3D War Room v2 -> http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
