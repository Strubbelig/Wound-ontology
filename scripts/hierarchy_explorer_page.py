"""Render the class hierarchy as a browsable tree page (HTML). Read-only view.

    python scripts/hierarchy_explorer_page.py <out html> [provenance csv]

Curator, 2026-10-02: "is there a way to show me the subtree after planned
process for example". Reads the latest `class_hierarchy_provenance_*.csv`
(one row per edge: child, parent, source) written by `run_build_hierarchies`,
so the page shows exactly what the hierarchy holds, every edge with the source
that put it there: `curated` (WONT/MILD), `placed` (checked placement, rule
59), `text` (one abstract said so), `fca` (accepted lattice slice).
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main(out, prov=None):
    prov = Path(prov) if prov else max((ROOT / "data" / "cache").glob("class_hierarchy_provenance_*.csv"),
                                       key=lambda f: f.stat().st_mtime)
    df = pd.read_csv(prov)
    names = sorted(set(df["child"]) | set(df["parent"]))
    idx = {n: i for i, n in enumerate(names)}
    kids = defaultdict(list)
    for c, p, s in df[["child", "parent", "source"]].itertuples(index=False):
        kids[idx[p]].append([idx[c], s])
    data = {"names": names, "kids": {str(k): v for k, v in kids.items()},
            "source": prov.name}
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    counts = df["source"].value_counts().to_dict()
    html = TEMPLATE.replace("__PAYLOAD__", payload).replace(
        "__SUMMARY__", " · ".join(f"{n:,} {s}" for s, n in counts.items()))
    Path(out).write_text(html, encoding="utf-8")
    print(f"{len(df):,} edges, {len(names):,} classes, {len(html)/1e6:.1f} MB -> {out}  ({counts})")


TEMPLATE = r'''<title>Class Hierarchy Explorer</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{
  --paper:#f6f7f4; --raise:#ffffff; --ink:#151b1e; --ink-2:#4b575d; --ink-3:#7d888d;
  --rule:#dde2dc; --accent:#0f6e5c; --accent-soft:#e2efeb;
  --cur:#1f5f9e; --cur-soft:#e3edf8; --pla:#1f7a4d; --pla-soft:#e4f1e9;
  --txt:#8a6d1f; --txt-soft:#f6efdc; --fca:#7a3fa0; --fca-soft:#f1e7f7;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme:dark;
    --paper:#101619; --raise:#171f23; --ink:#e8ecea; --ink-2:#a3b0b5; --ink-3:#71807f;
    --rule:#263036; --accent:#5cc7ad; --accent-soft:#16302b;
    --cur:#8db9ea; --cur-soft:#18283a; --pla:#6dc894; --pla-soft:#152a20;
    --txt:#d6b45f; --txt-soft:#2a2418; --fca:#c79be6; --fca-soft:#2a1d33;
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --paper:#101619; --raise:#171f23; --ink:#e8ecea; --ink-2:#a3b0b5; --ink-3:#71807f;
  --rule:#263036; --accent:#5cc7ad; --accent-soft:#16302b;
  --cur:#8db9ea; --cur-soft:#18283a; --pla:#6dc894; --pla-soft:#152a20;
  --txt:#d6b45f; --txt-soft:#2a2418; --fca:#c79be6; --fca-soft:#2a1d33;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:400 15px/1.5 "IBM Plex Sans",system-ui,-apple-system,sans-serif}
header{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--paper);border-bottom:1px solid var(--rule)}
.wrap{max-width:980px;margin:0 auto;padding:12px 16px}
h1{font-size:19px;font-weight:600;margin:0 0 2px}
.sub{color:var(--ink-2);font-size:13px;margin:0 0 10px}
.bar{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center;font-size:13px;color:var(--ink-2)}
input.q{font:inherit;font-size:14px;padding:6px 9px;border:1px solid var(--rule);background:var(--raise);color:var(--ink);width:280px;max-width:100%}
label.chk{display:flex;align-items:center;gap:5px}
.crumbs{font-size:13px;color:var(--ink-2);margin-top:8px;word-break:break-word}
.crumbs button{appearance:none;background:none;border:0;color:var(--accent);font:inherit;cursor:pointer;padding:0}
main{max-width:980px;margin:0 auto;padding:12px 16px 80px}
.sug{background:var(--raise);border:1px solid var(--rule);max-height:260px;overflow:auto;margin-top:6px;display:none}
.sug button{display:block;width:100%;text-align:left;appearance:none;border:0;background:none;color:var(--ink);font:inherit;font-size:13px;padding:5px 9px;cursor:pointer}
.sug button:hover,.sug button:focus{background:var(--accent-soft)}
ul.tree{list-style:none;margin:0;padding-left:18px;border-left:1px solid var(--rule)}
ul.tree.top{padding-left:0;border-left:0}
li{margin:1px 0}
.row{display:flex;align-items:baseline;gap:7px;min-width:0}
.tog{appearance:none;border:0;background:none;color:var(--ink-3);cursor:pointer;font:12px "IBM Plex Mono",monospace;width:16px;padding:0;flex:none}
.name{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:13.5px;word-break:break-word;cursor:pointer}
.name:hover{text-decoration:underline}
.n{font:12px "IBM Plex Mono",monospace;color:var(--ink-3);font-variant-numeric:tabular-nums}
.src{font:11px "IBM Plex Mono",monospace;padding:0 5px;border-radius:3px;flex:none}
.src.curated{background:var(--cur-soft);color:var(--cur)} .src.placed{background:var(--pla-soft);color:var(--pla)}
.src.text{background:var(--txt-soft);color:var(--txt)} .src.fca{background:var(--fca-soft);color:var(--fca)}
.more{appearance:none;border:0;background:none;color:var(--accent);font:13px "IBM Plex Sans",sans-serif;cursor:pointer;padding:2px 0}
.root{font-size:16px;font-weight:600;margin:4px 0 8px;font-family:"IBM Plex Mono",monospace;word-break:break-word}
footer{color:var(--ink-3);font-size:12px;margin-top:24px}
</style>
<header><div class="wrap">
  <h1>Class Hierarchy Explorer</h1>
  <p class="sub">Every edge of the class hierarchy, coloured by where it came from: <span class="src curated">curated</span> WONT/MILD, <span class="src placed">placed</span> checked placement, <span class="src text">text</span> one abstract, <span class="src fca">fca</span> accepted lattice slice. __SUMMARY__</p>
  <div class="bar">
    <label>Root <input class="q" id="q" type="search" placeholder="type a class, e.g. planned process" autocomplete="off"></label>
    <label class="chk"><input type="checkbox" data-s="curated" checked> curated</label>
    <label class="chk"><input type="checkbox" data-s="placed" checked> placed</label>
    <label class="chk"><input type="checkbox" data-s="text" checked> text</label>
    <label class="chk"><input type="checkbox" data-s="fca" checked> fca</label>
  </div>
  <div class="sug" id="sug"></div>
  <div class="crumbs" id="crumbs"></div>
</div></header>
<main>
  <div class="root" id="root"></div>
  <ul class="tree top" id="tree"></ul>
  <footer id="foot"></footer>
</main>
<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
(function () {
  "use strict";
  var D = JSON.parse(document.getElementById("payload").textContent);
  var N = D.names, K = D.kids, PAR = {}, lower = N.map(function (n) { return n.toLowerCase(); });
  Object.keys(K).forEach(function (p) { K[p].forEach(function (e) { (PAR[e[0]] = PAR[e[0]] || []).push(+p); }); });
  var on = { curated: true, placed: true, text: true, fca: true };
  var PAGE = 200, sizeCache = {};
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function kids(i) {
    return (K[i] || []).filter(function (e) { return on[e[1]]; })
      .sort(function (a, b) { return size(b[0]) - size(a[0]) || (N[a[0]] < N[b[0]] ? -1 : 1); });
  }
  function size(i) {                          // descendants under the active sources
    if (sizeCache[i] != null) return sizeCache[i];
    var seen = {}, stack = [i], n = 0;
    while (stack.length) { var x = stack.pop(); (K[x] || []).forEach(function (e) { if (on[e[1]] && !seen[e[0]]) { seen[e[0]] = 1; n++; stack.push(e[0]); } }); }
    return (sizeCache[i] = n);
  }
  function li(e, depth) {
    var i = e[0], k = kids(i).length;
    return '<li data-i="' + i + '"><div class="row">' +
      (k ? '<button class="tog" data-open="0" aria-label="expand">▸</button>' : '<span class="tog">·</span>') +
      '<span class="name" data-root="' + i + '">' + esc(N[i]) + '</span>' +
      (e[1] ? '<span class="src ' + e[1] + '">' + e[1] + '</span>' : '') +
      (k ? '<span class="n">' + k + ' child' + (k === 1 ? '' : 'ren') + ' · ' + size(i).toLocaleString() + ' below</span>' : '') +
      '</div></li>';
  }
  function fill(ul, list, from) {
    var html = list.slice(from, from + PAGE).map(function (e) { return li(e); }).join("");
    if (list.length > from + PAGE) html += '<li><button class="more" data-from="' + (from + PAGE) + '">show ' + Math.min(PAGE, list.length - from - PAGE) + ' more of ' + (list.length - from - PAGE) + '</button></li>';
    ul.insertAdjacentHTML("beforeend", html);
    ul._list = list;
  }
  var cur = null;
  function setRoot(i) {
    cur = i; sizeCache = {};
    document.getElementById("q").value = N[i];
    var r = document.getElementById("root"), t = document.getElementById("tree");
    r.textContent = N[i] + " — " + size(i).toLocaleString() + " classes below";
    t.innerHTML = ""; fill(t, kids(i), 0);
    var path = [], x = i, guard = 0;
    while (PAR[x] && guard++ < 30) { x = PAR[x][0]; path.unshift(x); }
    document.getElementById("crumbs").innerHTML = path.length ? "Above: " + path.map(function (p) {
      return '<button data-root="' + p + '">' + esc(N[p]) + '</button>'; }).join(" › ") +
      (PAR[i] && PAR[i].length > 1 ? " (also under " + (PAR[i].length - 1) + " other parent" + (PAR[i].length > 2 ? "s" : "") + ")" : "") : "Top level";
    try { history.replaceState(null, "", "#" + encodeURIComponent(N[i]).replace(/%/g, "~")); } catch (e) {}
  }
  document.addEventListener("click", function (ev) {
    var b = ev.target.closest("button,.name"); if (!b) return;
    if (b.dataset.root != null) { setRoot(+b.dataset.root); window.scrollTo(0, 0); hideSug(); return; }
    if (b.classList.contains("tog")) {
      var liEl = b.closest("li"), open = b.dataset.open === "1";
      if (open) { var sub = liEl.querySelector("ul"); if (sub) sub.remove(); b.dataset.open = "0"; b.textContent = "▸"; }
      else { var ul = document.createElement("ul"); ul.className = "tree"; liEl.appendChild(ul); fill(ul, kids(+liEl.dataset.i), 0); b.dataset.open = "1"; b.textContent = "▾"; }
      return;
    }
    if (b.classList.contains("more")) { var u = b.closest("ul"), f = +b.dataset.from; b.closest("li").remove(); fill(u, u._list, f); }
  });
  document.querySelectorAll("input[data-s]").forEach(function (c) {
    c.addEventListener("change", function () { on[c.dataset.s] = c.checked; if (cur != null) setRoot(cur); });
  });
  var q = document.getElementById("q"), sug = document.getElementById("sug");
  function hideSug() { sug.style.display = "none"; }
  q.addEventListener("input", function () {
    var s = q.value.trim().toLowerCase(); if (s.length < 2) { hideSug(); return; }
    var hits = [];
    for (var i = 0; i < N.length && hits.length < 40; i++) if (lower[i].indexOf(s) >= 0) hits.push(i);
    hits.sort(function (a, b) { return (lower[a] === s ? -1 : 0) - (lower[b] === s ? -1 : 0) || size(b) - size(a); });
    sug.innerHTML = hits.map(function (i) { return '<button data-root="' + i + '">' + esc(N[i]) + ' <span class="n">' + size(i).toLocaleString() + ' below</span></button>'; }).join("") || '<div class="n" style="padding:6px 9px">no class matches</div>';
    sug.style.display = "block";
  });
  q.addEventListener("keydown", function (e) { if (e.key === "Enter") { var f = sug.querySelector("button"); if (f) f.click(); } });
  document.getElementById("foot").textContent = "Read from " + D.source + " · " + N.length.toLocaleString() + " classes.";
  var start = null, h = decodeURIComponent((location.hash || "").slice(1).replace(/~/g, "%"));
  [h, "Planned Process", "planned process"].some(function (n) { var i = N.indexOf(n); if (i >= 0) { start = i; return true; } return false; });
  if (start == null) start = 0;
  setRoot(start);
})();
</script>
'''

if __name__ == "__main__":
    main(*sys.argv[1:])
