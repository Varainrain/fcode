"""AUTOLAB DASHBOARD — watch and steer the search. Read-only except the controls.

    python -m autolab.dash        then open http://localhost:8643

Everything on the page is computed from autolab/lab.db, which the runner writes.
The runner and the dashboard are separate processes on purpose: closing this
does not stop the search, and the search does not need this to run.
"""
import html
import json
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import store
from .build_template import KNOB_SPEC

PORT = 8643

CSS = """
*{box-sizing:border-box} body{margin:0;background:#0c0d10;color:#d7dae0;
font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
a{color:#7cc4ff;text-decoration:none} a:hover{text-decoration:underline}
.wrap{max-width:1180px;margin:0 auto;padding:18px}
h1{font-size:15px;margin:0 0 2px;letter-spacing:.5px}
.sub{color:#6b7280;font-size:12px;margin-bottom:16px}
.card{background:#14161b;border:1px solid #23262e;border-radius:8px;
padding:14px 16px;margin-bottom:14px}
.card h2{font-size:12px;text-transform:uppercase;letter-spacing:1px;
color:#8b93a1;margin:0 0 10px;font-weight:600}
table{width:100%;border-collapse:collapse} th,td{text-align:left;padding:5px 8px;
border-bottom:1px solid #1e212a;white-space:nowrap} th{color:#6b7280;font-weight:600;
font-size:11px;text-transform:uppercase;letter-spacing:.5px}
.bar{position:relative;height:14px;background:#1b1e25;border-radius:3px;min-width:220px}
.band{position:absolute;top:0;height:100%;background:#2b3038;border-radius:3px}
.ci{position:absolute;top:3px;height:8px;border-radius:2px}
.pt{position:absolute;top:1px;width:2px;height:12px;background:#fff}
.mid{position:absolute;top:-2px;width:1px;height:18px;background:#3a3f4a}
.good{color:#4ade80}.bad{color:#f87171}.warn{color:#fbbf24}.dim{color:#6b7280}
.btn{display:inline-block;background:#1e222b;border:1px solid #2c313c;color:#d7dae0;
padding:4px 10px;border-radius:5px;margin-right:6px;font-size:12px;cursor:pointer}
.btn:hover{background:#262b36;text-decoration:none}
input,select{background:#0f1116;border:1px solid #2c313c;color:#d7dae0;
padding:4px 8px;border-radius:5px;font:inherit}
.knob{display:inline-block;background:#1b1e25;border-radius:4px;padding:2px 7px;
margin:2px 4px 2px 0}
.knob b{color:#7cc4ff;font-weight:600}
.log{max-height:260px;overflow:auto} .log div{padding:2px 0;border-bottom:1px solid #16191f}
"""


def bar(lo, hi, pt, nlo, nhi, colour):
    """One 0-100% track: grey = the null band, coloured = this candidate's CI."""
    def pos(x):
        return max(0.0, min(100.0, x))
    return (
        f'<div class="bar">'
        f'<div class="band" style="left:{pos(nlo):.1f}%;width:{pos(nhi)-pos(nlo):.1f}%"></div>'
        f'<div class="mid" style="left:50%"></div>'
        f'<div class="ci" style="left:{pos(lo):.1f}%;width:{pos(hi)-pos(lo):.1f}%;'
        f'background:{colour}"></div>'
        f'<div class="pt" style="left:{pos(pt):.1f}%"></div></div>')


def knob_chips(knobs, base=None):
    out = []
    for k in KNOB_SPEC:
        v = knobs.get(k)
        moved = base is not None and base.get(k) != v
        style = ' style="outline:1px solid #4ade80"' if moved else ""
        out.append(f'<span class="knob"{style}>{html.escape(k)} <b>{v}</b></span>')
    return "".join(out)


def page(con):
    champ = store.champion(con)
    nulls = store.active(con, "null")
    null = nulls[0] if nulls else None
    paused = store.get_control(con, "paused", "0") == "1"
    workers = store.get_control(con, "workers", "6")
    lanes = store.get_control(con, "lanes", "attack")
    total = con.execute("SELECT COUNT(*) c FROM games").fetchone()["c"]

    if null:
        nw, nn = store.tally(con, null["name"])
        npct, nlo, nhi = store.wilson(nw, nn)
    else:
        nw = nn = 0
        npct, nlo, nhi = 0.0, 0.0, 100.0

    h = [f"<style>{CSS}</style><div class=wrap>",
         "<h1>AUTOLAB — self-iterating knob search</h1>",
         f'<div class=sub>{total} games in the book &middot; '
         f'{"<span class=warn>PAUSED</span>" if paused else "<span class=good>running</span>"} '
         f'&middot; {workers} workers &middot; lanes: {html.escape(lanes)} '
         f'&middot; <span class=dim>refreshes every 5s</span></div>']

    # ---- controls
    h.append('<div class=card><h2>controls</h2>'
             f'<a class=btn href="/set?paused={0 if paused else 1}">'
             f'{"resume" if paused else "pause"}</a>'
             f'<a class=btn href="/set?workers={max(1,int(workers)-2)}">workers -2</a>'
             f'<a class=btn href="/set?workers={int(workers)+2}">workers +2</a>')
    for lane in ("attack", "core", "econ"):
        on = lane in lanes
        new = ([l for l in lanes.split(",") if l and l != lane] if on
               else [l for l in lanes.split(",") if l] + [lane])
        h.append(f'<a class=btn href="/set?lanes={",".join(new)}" '
                 f'style="{"outline:1px solid #4ade80" if on else ""}">'
                 f'{"✓" if on else "+"} {lane}</a>')
    h.append('<form action="/req" style="margin-top:10px">'
             '<input name="q" size="52" placeholder=\'try {"SEAT_TI": 60}\'> '
             '<button class=btn>queue</button>'
             '<span class=dim> &nbsp;also: <code>kill lab_cNNN</code>, '
             '<code>rebase OogwayAttack</code></span></form></div>')

    # ---- champion + null
    if champ:
        ck = json.loads(champ["knobs"])
        h.append('<div class=card><h2>champion</h2>'
                 f'<div><b>{html.escape(champ["name"])}</b> '
                 f'<span class=dim>{html.escape(champ["note"] or "")}</span></div>'
                 f'<div style="margin-top:8px">{knob_chips(ck)}</div>')
        if null:
            h.append(f'<div style="margin-top:10px" class=dim>null '
                     f'<b>{html.escape(null["name"])}</b> — byte-identical control — '
                     f'{nw}/{nn} = {npct:.1f}%, 95% CI {nlo:.1f}-{nhi:.1f}. '
                     f'A candidate must clear <b>{nhi:.1f}%</b> to promote, and '
                     f'drops below <b>{nlo:.1f}%</b> to be culled.</div>')
        h.append("</div>")
        base = ck
    else:
        base = {}

    # ---- live candidates
    h.append('<div class=card><h2>candidates in the arena</h2><table>'
             '<tr><th>variant</th><th>change</th><th>games</th><th>win%</th>'
             '<th>95% CI vs null band</th><th></th></tr>')
    rows = store.active(con, "candidate")
    if not rows:
        h.append('<tr><td colspan=6 class=dim>none live — the runner will '
                 'propose more on its next cycle</td></tr>')
    for c in rows:
        w, n = store.tally(con, c["name"])
        pct, lo, hi = store.wilson(w, n)
        colour = "#4ade80" if lo > nhi else ("#f87171" if hi < nlo else "#7cc4ff")
        h.append(f'<tr><td>{html.escape(c["name"])}</td>'
                 f'<td>{html.escape(c["note"] or "")}</td><td>{n}</td>'
                 f'<td>{pct:.1f}</td><td>{bar(lo, hi, pct, nlo, nhi, colour)}</td>'
                 f'<td><a href="/req?q=kill+{html.escape(c["name"])}" '
                 f'class=dim>kill</a></td></tr>')
    h.append("</table></div>")

    # ---- history
    h.append('<div class=card><h2>closed</h2><table>'
             '<tr><th>variant</th><th>change</th><th>outcome</th><th>games</th>'
             '<th>win%</th></tr>')
    closed = con.execute(
        "SELECT * FROM variants WHERE status!='active' ORDER BY closed DESC LIMIT 14"
    ).fetchall()
    if not closed:
        h.append('<tr><td colspan=5 class=dim>nothing closed yet</td></tr>')
    for c in closed:
        w, n = store.tally(con, c["name"])
        pct, _, _ = store.wilson(w, n)
        klass = {"promoted": "good", "rejected": "bad"}.get(c["status"], "dim")
        h.append(f'<tr><td>{html.escape(c["name"])}</td>'
                 f'<td>{html.escape(c["note"] or "")}</td>'
                 f'<td class={klass}>{c["status"]}</td><td>{n}</td>'
                 f'<td>{pct:.1f}</td></tr>')
    h.append("</table></div>")

    # ---- log
    h.append('<div class=card><h2>log</h2><div class=log>')
    for e in con.execute("SELECT * FROM events ORDER BY id DESC LIMIT 60").fetchall():
        when = time.strftime("%H:%M:%S", time.localtime(e["ts"]))
        klass = {"PROMOTE": "good", "reject": "bad", "error": "bad",
                 "retire": "warn"}.get(e["kind"], "dim")
        h.append(f'<div><span class=dim>{when}</span> '
                 f'<span class={klass}>{html.escape(e["kind"])}</span> '
                 f'{html.escape(e["text"])}</div>')
    h.append("</div></div></div>")
    return "".join(h)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, code=200, ctype="text/html; charset=utf-8"):
        raw = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _redirect(self):
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(parsed.query)
        con = store.init()
        try:
            if parsed.path == "/set":
                for key in ("paused", "workers", "lanes", "min_prune",
                            "min_promote", "max_games", "candidates"):
                    if key in q:
                        store.set_control(con, key, q[key][0])
                return self._redirect()
            if parsed.path == "/req":
                if q.get("q"):
                    store.set_control(con, "request", q["q"][0])
                return self._redirect()
            if parsed.path == "/api":
                champ = store.champion(con)
                return self._send(json.dumps({
                    "champion": dict(champ) if champ else None,
                    "games": con.execute("SELECT COUNT(*) c FROM games")
                    .fetchone()["c"],
                }), ctype="application/json")
            body = ('<meta http-equiv="refresh" content="5">'
                    '<title>autolab</title>' + page(con))
            return self._send(body)
        finally:
            con.close()


def main():
    store.init().close()
    print(f"autolab dashboard on http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
