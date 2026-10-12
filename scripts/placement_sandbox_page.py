"""Render the placement sandbox file as an inspection page (HTML), compactly.

    python scripts/placement_sandbox_page.py <placement json> <template css html> <script js> <out html>
"""
import hashlib, json, sys

src, tpl, js, out = sys.argv[1:5]
rows = json.load(open(src, encoding="utf-8"))["rows"]
cols = ["id", "term", "category", "abstracts", "relation", "parent", "reason", "candidates"]
data = {"cols": cols, "rows": [[
    "p" + hashlib.sha1(r["term"].encode()).hexdigest()[:12], r["term"], r["category"], r["abstracts"],
    r["relation"], r["parent"], r["reason"][:160], [[c[0], c[1]] for c in r["candidates"][:5]]]
    for r in rows]}
css = "\n".join(open(tpl, encoding="utf-8").read().splitlines()[1:116])
payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
html = f'''<title>Placement Sandbox</title>
{css}
.side .spell .k{{font-family:"IBM Plex Mono",monospace;font-size:11px;color:var(--ink-3)}}
select,input.q{{background:var(--raise);color:var(--ink);border:1px solid var(--rule);padding:4px 6px;font:inherit}}
.pager{{display:flex;gap:10px;align-items:center;margin:14px 0}}
</style>
<header><div class="hwrap">
  <h1>Placement Sandbox</h1>
  <p class="sub">Where the model would put each extracted term under WONT/MILD and the import modules. Nothing here is merged. <span id="summary"></span></p>
</div><div class="bar"><span id="progress"></span></div></header>
<main>
  <div class="toolbar">
    <label>Answer <select id="f-rel"><option value="">all</option><option value="is_a">is a</option><option value="same">same</option><option value="none">none</option></select></label>
    <label>Category <select id="f-cat"><option value="">all</option></select></label>
    <label>Abstracts ≥ <select id="f-min"><option>1</option><option selected>2</option><option>3</option><option>5</option><option>10</option></select></label>
    <label><input type="checkbox" id="f-open"> Hide reviewed</label>
    <input class="q" id="f-q" placeholder="search term or parent">
  </div>
  <div id="list"></div>
  <div class="pager"><button class="v" id="prev">← Previous</button><span id="pager"></span><button class="v" id="next">Next →</button></div>
</main>
<footer><div class="fwrap"><span class="dot" id="dot"></span><span id="status">Loading…</span><span class="hint" id="tally"></span></div></footer>
<script id="payload" type="application/json">{payload}</script>
<script>
{open(js, encoding="utf-8").read()}
</script>
'''
open(out, "w", encoding="utf-8").write(html)
print(f"{out}: {len(rows):,} rows, {len(html)/1e6:.1f} MB")
