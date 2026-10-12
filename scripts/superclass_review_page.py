"""Render the checked superclass and synonym results as a review page (HTML).

    python scripts/superclass_review_page.py <out html>

Curator, 2026-10-01: before anything is written into the term dict, the 332
synonyms are looked at one by one (each becomes a mapping and changes the
view), and the 13,446 superclasses are accepted as a batch with spot checks
(refuse a term or a whole group). `exclude` (curator, 2026-10-02: "add a
button to exclude a term. some are not necessary or unspecific nonsense like
clinical method") marks the term itself out of scope, not just its class. Reads `data/review/placement_merged_2026-10-01.json`.
The page keeps its decisions in its own database, one document per class
group, which `scripts/apply_superclasses.py` (to come) reads.
"""
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MERGED = ROOT / "data" / "review" / "placement_merged_2026-10-01.json"


def h(s, n=12):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:n]


def source(iri):
    iri = iri or ""
    if "/WONT/" in iri:
        return "WONT"
    if "/MILD/" in iri:
        return "MILD"
    tail = iri.rsplit("/", 1)[-1]
    return tail.split("_")[0] if "_" in tail else "other"


def how(check):
    c = check or ""
    if c.startswith("verify"):
        if "agrees" in c:
            return "model + Claude"
        if "is_a, not same" in c:
            return "Claude: subclass, not synonym"
        if "alternative" in c:
            return "Claude's parent"
        return "Claude over the model"
    if "same -> is_a" in c:
        return "Claude: subclass, not synonym"
    if "alternative" in c:
        return "Claude's parent"
    return "Claude"


def main(out):
    rows = json.loads(MERGED.read_text(encoding="utf-8"))["rows"]
    groups = defaultdict(list)
    for r in rows:
        if r["outcome"] not in ("placed", "synonym"):
            continue
        kind = "syn" if r["outcome"] == "synonym" else "sub"
        groups[(kind, r["parent iri"], r["parent"])].append(r)
    data = []
    for (kind, iri, parent), items in groups.items():
        items.sort(key=lambda r: (-r["abstracts"], r["term"].lower()))
        data.append({"id": "g" + h(f"{kind}|{iri}"), "k": kind, "p": parent, "iri": iri,
                     "src": source(iri),
                     "items": [["i" + h(r["term"], 10), r["term"], r["category"], r["abstracts"],
                                how(r["check"])] for r in items]})
    data.sort(key=lambda g: (-len(g["items"]), g["p"].lower()))
    payload = json.dumps({"groups": data}, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    n_syn = sum(len(g["items"]) for g in data if g["k"] == "syn")
    n_sub = sum(len(g["items"]) for g in data if g["k"] == "sub")
    html = TEMPLATE.replace("__PAYLOAD__", payload).replace("__NSYN__", f"{n_syn:,}").replace("__NSUB__", f"{n_sub:,}")
    Path(out).write_text(html, encoding="utf-8")
    print(f"{len(data)} groups, {n_syn} synonyms, {n_sub} subclasses, {len(html)/1e6:.2f} MB -> {out}")


TEMPLATE = r'''<title>Superclasses and Synonyms</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
:root{
  --paper:#f7f8f6; --raise:#ffffff; --ink:#12181c; --ink-2:#4a565d; --ink-3:#7b878e;
  --rule:#dfe3de; --rule-2:#eceee9;
  --accent:#0f6e5c; --accent-soft:#e2efeb;
  --in:#1f7a4d; --in-soft:#e4f1e9; --out:#a8322b; --out-soft:#f7e6e4;
  --hold:#8a6d1f; --hold-soft:#f6efdc; --focus:#0f6e5c;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme:dark;
    --paper:#101619; --raise:#171f23; --ink:#e8ecea; --ink-2:#a3b0b5; --ink-3:#71807f;
    --rule:#263036; --rule-2:#1d262b;
    --accent:#5cc7ad; --accent-soft:#16302b;
    --in:#6dc894; --in-soft:#152a20; --out:#e88a80; --out-soft:#2e1c1a;
    --hold:#d6b45f; --hold-soft:#2a2418; --focus:#5cc7ad;
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --paper:#101619; --raise:#171f23; --ink:#e8ecea; --ink-2:#a3b0b5; --ink-3:#71807f;
  --rule:#263036; --rule-2:#1d262b;
  --accent:#5cc7ad; --accent-soft:#16302b;
  --in:#6dc894; --in-soft:#152a20; --out:#e88a80; --out-soft:#2e1c1a;
  --hold:#d6b45f; --hold-soft:#2a2418; --focus:#5cc7ad;
}
*{box-sizing:border-box}
body{background:var(--paper);color:var(--ink);font:400 15px/1.5 "IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;-webkit-text-size-adjust:100%}
.mono,.term,.cls{font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace}
header{position:sticky;top:env(safe-area-inset-top,0px);z-index:9;background:var(--paper);border-bottom:1px solid var(--rule)}
.hwrap{max-width:960px;margin:0 auto;padding:14px 16px 0}
h1{font-size:19px;font-weight:600;margin:0 0 2px;letter-spacing:-.01em;text-wrap:balance}
.sub{color:var(--ink-2);font-size:13px;margin:0 0 12px;max-width:72ch}
.tabs{display:flex;gap:22px}
.tab{appearance:none;background:none;border:0;border-bottom:2px solid transparent;color:var(--ink-3);font:500 14px/1 "IBM Plex Sans",sans-serif;cursor:pointer;padding:0 0 11px;display:flex;align-items:baseline;gap:7px}
.tab[aria-selected="true"]{color:var(--ink);border-bottom-color:var(--accent)}
.tab:focus-visible{outline:2px solid var(--focus);outline-offset:3px}
.count{font-family:"IBM Plex Mono",monospace;font-size:12px;color:var(--ink-3);font-variant-numeric:tabular-nums}
.bar{height:3px;background:var(--rule-2)}
.bar span{display:block;height:100%;background:var(--accent);width:0;transition:width .25s}
main{max-width:960px;margin:0 auto;padding:16px 16px 96px}
.toolbar{display:flex;flex-wrap:wrap;gap:12px 16px;align-items:center;color:var(--ink-2);font-size:13px;margin-bottom:14px}
.toolbar label{display:flex;align-items:center;gap:7px}
select,input.q{background:var(--raise);color:var(--ink);border:1px solid var(--rule);padding:5px 8px;font:inherit;font-size:13px}
input.q{min-width:0;width:220px;max-width:100%}
.explain{font-size:13px;color:var(--ink-2);background:var(--raise);border:1px solid var(--rule);padding:10px 12px;margin-bottom:14px;max-width:80ch}
.group{border-top:1px solid var(--rule-2);padding:14px 0}
.group:first-child{border-top:0}
.ghead{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 12px}
.cls{font-weight:600;font-size:15px;word-break:break-word}
.src{font-family:"IBM Plex Mono",monospace;font-size:11px;letter-spacing:.06em;color:var(--ink-2);border:1px solid var(--rule);padding:1px 6px}
.n{font-family:"IBM Plex Mono",monospace;font-size:12px;color:var(--ink-3);font-variant-numeric:tabular-nums}
.pill{font-size:12px;font-weight:500;padding:2px 8px;border-radius:999px;white-space:nowrap}
.pill.ok{background:var(--in-soft);color:var(--in)} .pill.no{background:var(--out-soft);color:var(--out)}
.pill.mix{background:var(--hold-soft);color:var(--hold)} .pill.open{background:var(--rule-2);color:var(--ink-2)}
.gacts{margin-left:auto;display:flex;gap:6px;flex-wrap:wrap}
button.v{appearance:none;cursor:pointer;font:500 13px/1 "IBM Plex Sans",sans-serif;background:var(--raise);color:var(--ink);border:1px solid var(--rule);padding:7px 11px}
button.v:hover{border-color:var(--ink-3)}
button.v:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
button.v[aria-pressed="true"][data-tone="in"]{background:var(--in-soft);color:var(--in);border-color:currentColor;font-weight:600}
button.v[aria-pressed="true"][data-tone="out"]{background:var(--out-soft);color:var(--out);border-color:currentColor;font-weight:600}
button.link{appearance:none;background:none;border:0;color:var(--accent);font:500 13px "IBM Plex Sans",sans-serif;cursor:pointer;padding:6px 0}
.items{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:4px 16px;margin-top:10px}
.item{display:flex;align-items:center;gap:8px;padding:4px 0;border-bottom:1px dashed var(--rule-2);min-width:0}
.item .term{font-size:13px;word-break:break-word;flex:1 1 auto;min-width:0}
.item[data-state="refuse"] .term{text-decoration:line-through;color:var(--out)}
.item[data-state="exclude"] .term{text-decoration:line-through;color:var(--ink-3)}
.item button[aria-pressed="true"][data-tone="ex"]{background:var(--rule-2);color:var(--ink);border-color:currentColor}
.pill.ex{background:var(--rule-2);color:var(--ink-2)}
.item .meta{font-size:11px;color:var(--ink-3);white-space:nowrap}
.item button{appearance:none;border:1px solid var(--rule);background:var(--raise);color:var(--ink-2);font:500 11px/1 "IBM Plex Sans",sans-serif;padding:4px 6px;cursor:pointer;flex:none}
.item button[aria-pressed="true"][data-tone="out"]{background:var(--out-soft);color:var(--out);border-color:currentColor}
.item button[aria-pressed="true"][data-tone="in"]{background:var(--in-soft);color:var(--in);border-color:currentColor}
.item button:focus-visible{outline:2px solid var(--focus);outline-offset:1px}
.more{font-size:12px;color:var(--ink-3);margin-top:6px}
.empty{color:var(--ink-2);padding:40px 0;text-align:center}
footer{position:fixed;left:0;right:0;bottom:0;background:var(--raise);border-top:1px solid var(--rule);font-size:12px;color:var(--ink-2);padding:9px 16px calc(9px + env(safe-area-inset-bottom,0px))}
.fwrap{max-width:960px;margin:0 auto;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
.dot{width:7px;height:7px;border-radius:50%;background:var(--in);flex:none}
.dot.warn{background:var(--hold)} .dot.bad{background:var(--out)}
.tally{margin-left:auto;font-variant-numeric:tabular-nums}
@keyframes flash{from{background:var(--accent-soft)}to{background:transparent}}
.group.flash{animation:flash 1.6s ease-out}
@media (prefers-reduced-motion:reduce){*{transition:none!important}.group.flash{animation:none}}
@media (max-width:560px){.gacts{margin-left:0}h1{font-size:17px}}
</style>
<header>
  <div class="hwrap">
    <h1>Superclasses and Synonyms</h1>
    <p class="sub">Every extracted term below was given an existing WONT, MILD or module class, either as its superclass or as a synonym, and every one was read before it reached this page. Nothing is written into the term dict until you are done here.</p>
    <div class="tabs" role="tablist">
      <button class="tab" role="tab" id="tab-syn" aria-selected="true">Synonyms <span class="count" id="c-syn">__NSYN__</span></button>
      <button class="tab" role="tab" id="tab-sub" aria-selected="false">Superclasses <span class="count" id="c-sub">__NSUB__</span></button>
    </div>
  </div>
  <div class="bar"><span id="progress"></span></div>
</header>
<main>
  <div class="explain" id="explain"></div>
  <div class="toolbar">
    <label>Find <input class="q" id="q" type="search" placeholder="class or term"></label>
    <label>From <select id="src"><option value="">all sources</option></select></label>
    <label>Show <select id="show"><option value="all">all groups</option><option value="open">undecided</option><option value="refused">with refusals</option><option value="excluded">with exclusions</option></select></label>
  </div>
  <div id="list"></div>
  <div id="pager"></div>
</main>
<footer><div class="fwrap"><span class="dot" id="dot"></span><span id="status">Loading your decisions…</span><span class="tally" id="tally"></span></div></footer>
<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
(function () {
  "use strict";
  var G = JSON.parse(document.getElementById("payload").textContent).groups;
  var byId = {}; G.forEach(function (g) { byId[g.id] = g; });
  var dec = {};                    // group id -> {all, items:{itemId:{v,term}}}
  var db = null, tab = "syn", open = {}, page = 1, PER = 60, SAMPLE = 8;
  var list = document.getElementById("list"), statusEl = document.getElementById("status"), dot = document.getElementById("dot");
  function say(t, tone) { statusEl.textContent = t; dot.className = "dot" + (tone ? " " + tone : ""); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function coll(g) { return g.k === "syn" ? "synonym" : "subclass"; }
  var EXPLAIN = {
    syn: "<b>Synonym</b>: the term names a class that already exists. Accepting it maps the term onto that class, so its mentions in the abstracts are read as the class from then on. Each one needs your yes; nothing here is accepted until you say so.",
    sub: "<b>Superclass</b>: the term becomes a subclass of the class it is listed under. This changes no mention and no count; FCA and the build read it later. Everything here counts as <b>accepted</b> unless you refuse a term or a whole group, and any refusal can be withdrawn later.",
  };
  var EXCLUDE = " <b>Exclude</b> is stronger than refuse: the term itself is not wanted (too unspecific, not needed) and goes out of scope, under no class at all.";
  function state(g, itemId) {
    var d = dec[g.id] || {}, it = (d.items || {})[itemId];
    if (it && it.v) return it.v;
    if (d.all) return d.all;
    return g.k === "sub" ? "default" : "open";
  }
  function gsum(g) {
    var s = { accept: 0, refuse: 0, exclude: 0, open: 0, "default": 0 };
    g.items.forEach(function (i) { s[state(g, i[0])]++; });
    return s;
  }
  function pill(g, s) {
    var n = g.items.length;
    var ex = s.exclude ? '<span class="pill ex">' + s.exclude + ' excluded</span>' : "";
    if (s.refuse === n) return '<span class="pill no">refused</span>';
    if (s.exclude === n) return ex;
    if (s.refuse) return '<span class="pill mix">' + s.refuse + ' refused</span>' + ex;
    if (s.exclude && g.k === "syn" && !s.open) return '<span class="pill ok">decided</span>' + ex;
    if (s.exclude && g.k === "syn") return '<span class="pill mix">' + s.open + ' undecided</span>' + ex;
    if (s.exclude) return '<span class="pill ok">rest accepted</span>' + ex;
    if (g.k === "sub") return s.accept === n ? '<span class="pill ok">accepted</span>' : '<span class="pill ok">accepted by default</span>';
    if (s.open === n) return '<span class="pill open">undecided</span>';
    if (s.open) return '<span class="pill mix">' + s.open + ' undecided</span>';
    return '<span class="pill ok">accepted</span>';
  }
  function visible() {
    var q = document.getElementById("q").value.trim().toLowerCase();
    var src = document.getElementById("src").value, show = document.getElementById("show").value;
    return G.filter(function (g) {
      if (g.k !== tab) return false;
      if (src && g.src !== src) return false;
      if (q && g.p.toLowerCase().indexOf(q) < 0 && !g.items.some(function (i) { return i[1].toLowerCase().indexOf(q) >= 0; })) return false;
      if (show === "all") return true;
      var s = gsum(g);
      return show === "open" ? (g.k === "syn" ? s.open > 0 : s.accept + s.refuse + s.exclude === 0)
        : show === "excluded" ? s.exclude > 0 : s.refuse > 0;
    }).sort(function (a, b) {          // what needed a decision when the list was drawn comes first;
      return (openAtStart[b.id] ? 1 : 0) - (openAtStart[a.id] ? 1 : 0);   // a group does not jump away when clicked
    });
  }
  function itemHTML(g, i) {
    var st = state(g, i[0]);
    var acc = g.k === "syn" ? '<button data-g="' + g.id + '" data-i="' + i[0] + '" data-v="accept" data-tone="in" aria-pressed="' + (st === "accept") + '">Accept</button>' : "";
    return '<div class="item" data-state="' + st + '"><span class="term" title="' + esc(i[2]) + '">' + esc(i[1]) + '</span>' +
      '<span class="meta">' + i[3] + ' abs · ' + esc(i[4]) + '</span>' + acc +
      '<button data-g="' + g.id + '" data-i="' + i[0] + '" data-v="refuse" data-tone="out" aria-pressed="' + (st === "refuse") + '">Refuse</button>' +
      '<button data-g="' + g.id + '" data-i="' + i[0] + '" data-v="exclude" data-tone="ex" title="not wanted at all: out of scope" aria-pressed="' + (st === "exclude") + '">Exclude</button></div>';
  }
  function groupHTML(g) {
    // a term still waiting for a decision is never hidden behind "Show all":
    // undecided terms come first, and the collapsed view always includes them
    var s = gsum(g), n = g.items.length;
    var ordered = g.items.filter(function (i) { return state(g, i[0]) === "open"; })
      .concat(g.items.filter(function (i) { return state(g, i[0]) !== "open"; }));
    var shown = open[g.id] ? ordered : ordered.slice(0, Math.max(SAMPLE, s.open));
    var d = dec[g.id] || {};
    var verb = g.k === "syn" ? "merge into" : "are subclasses of";
    return '<section class="group" id="' + g.id + '"><div class="ghead">' +
      '<span class="cls">' + esc(g.p) + '</span><span class="src">' + esc(g.src) + '</span>' +
      '<span class="n">' + n + (n === 1 ? ' term' : ' terms') + ' ' + verb + ' it</span>' + pill(g, s) +
      '<span class="gacts">' +
      (g.k === "syn" && s.open > 0 && s.accept + s.refuse + s.exclude > 0 ?
        '<button class="v" data-g="' + g.id + '" data-rest="accept" data-tone="in">Accept the other ' + s.open + '</button>' : '') +
      '<button class="v" data-g="' + g.id + '" data-all="accept" data-tone="in" aria-pressed="' + (d.all === "accept" && !Object.keys(d.items || {}).length) + '">Accept all</button>' +
      '<button class="v" data-g="' + g.id + '" data-all="refuse" data-tone="out" aria-pressed="' + (d.all === "refuse") + '">Refuse all</button></span></div>' +
      '<div class="items">' + shown.map(function (i) { return itemHTML(g, i); }).join("") + '</div>' +
      (n > SAMPLE ? '<button class="link" data-toggle="' + g.id + '">' + (open[g.id] ? 'Show fewer' : 'Show all ' + n) + '</button>' : '') +
      '</section>';
  }
  function counts() {
    var syn = 0, synDone = 0, ref = 0, sub = 0;
    G.forEach(function (g) {
      var s = gsum(g);
      if (g.k === "syn") { syn += g.items.length; synDone += s.accept + s.refuse + s.exclude; } else { sub += g.items.length; ref += s.refuse + s.exclude; }
    });
    document.getElementById("c-syn").textContent = synDone + "/" + syn;
    document.getElementById("c-sub").textContent = (sub - ref).toLocaleString() + " kept";
    document.getElementById("progress").style.width = (syn ? synDone / syn * 100 : 0) + "%";
    document.getElementById("tally").textContent = synDone + " of " + syn + " synonyms decided · " + ref + " superclass refusal" + (ref === 1 ? "" : "s") + " or exclusion" + (ref === 1 ? "" : "s");
  }
  function render() {
    var v = visible(), pages = Math.max(1, Math.ceil(v.length / PER));
    if (page > pages) page = pages;
    list.innerHTML = v.length ? v.slice((page - 1) * PER, page * PER).map(groupHTML).join("") : '<p class="empty">No group matches these filters.</p>';
    document.getElementById("pager").innerHTML = pages > 1 ?
      '<div class="toolbar"><button class="v" data-page="' + (page - 1) + '"' + (page === 1 ? ' disabled' : '') + '>Previous</button>' +
      '<span class="count">page ' + page + ' of ' + pages + ' · ' + v.length + ' groups</span>' +
      '<button class="v" data-page="' + (page + 1) + '"' + (page === pages ? ' disabled' : '') + '>Next</button></div>' : '';
    document.getElementById("explain").innerHTML = EXPLAIN[tab] + EXCLUDE;
    counts();
  }
  var queue = Promise.resolve();
  var lastMsg = "Saved.";
  function persist(g, what) {
    var d = dec[g.id] || {};
    var body = { kind: g.k, parent: g.p, iri: g.iri, all: d.all || null, items: d.items || {}, when: new Date().toISOString() };
    dec[g.id] = body; counts();
    if (!db) { say("Not saved: the shared store is unavailable here. Reload the page to try again.", "bad"); return; }
    say("Saving…", "warn");
    queue = queue.then(function () { return db.doc(coll(g) + "/" + g.id).set(body); })
      .then(function () {
        var left = 0; G.forEach(function (x) { if (x.k === "syn") left += gsum(x).open; });
        say("Saved — " + (what || "decision") + ". " + left + " synonym" + (left === 1 ? "" : "s") + " still undecided.", "");
        var el = document.getElementById(g.id); if (el) { el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash"); }
      })
      .catch(function (e) { say("Not saved: " + why(e) + ". Your other decisions are safe.", "bad"); });
  }
  list.addEventListener("click", function (e) {
    try { onClick(e); } catch (err) { say("That click failed: " + why(err) + ". Nothing was saved.", "bad"); }
  });
  function onClick(e) {
    var b = e.target.closest("button"); if (!b) return;
    if (b.dataset.toggle) { open[b.dataset.toggle] = !open[b.dataset.toggle]; render(); return; }
    var g = byId[b.dataset.g]; if (!g) return;
    var d = dec[g.id] = dec[g.id] || { items: {} };
    d.items = d.items || {};
    if (b.dataset.rest) {
      // accept every term still undecided; the refusals (and explicit accepts) stay
      g.items.forEach(function (x) { if (state(g, x[0]) === "open") d.items[x[0]] = { v: "accept", term: x[1] }; });
    } else if (b.dataset.all) {
      d.all = d.all === b.dataset.all ? null : b.dataset.all;   // a second click withdraws it
      d.items = {};
    } else {
      var it = g.items.find(function (x) { return x[0] === b.dataset.i; });
      var cur = d.items[b.dataset.i] && d.items[b.dataset.i].v;
      if (cur === b.dataset.v) delete d.items[b.dataset.i];
      else d.items[b.dataset.i] = { v: b.dataset.v, term: it ? it[1] : "" };
    }
    var what = b.dataset.rest ? "accepted the rest of " + g.p
      : b.dataset.all ? (d.all ? (d.all === "accept" ? "accepted all of " : "refused all of ") : "withdrew the group decision on ") + g.p
      : (d.items[b.dataset.i] ? ({ accept: "accepted ", refuse: "refused ", exclude: "excluded " })[d.items[b.dataset.i].v] : "withdrew ") +
        "“" + ((g.items.find(function (x) { return x[0] === b.dataset.i; }) || [0, "a term"])[1]) + "” under " + g.p;
    render(); persist(g, what);
  }
  document.getElementById("pager").addEventListener("click", function (e) {
    var b = e.target.closest("button[data-page]"); if (!b || b.disabled) return;
    page = Number(b.dataset.page); render(); window.scrollTo(0, 0);
  });
  var openAtStart = {};
  function snapshot() { openAtStart = {}; G.forEach(function (g) { if (g.k === "syn" && gsum(g).open > 0) openAtStart[g.id] = true; }); }
  function setTab(t) {
    tab = t; page = 1; snapshot();
    document.getElementById("tab-syn").setAttribute("aria-selected", t === "syn");
    document.getElementById("tab-sub").setAttribute("aria-selected", t === "sub");
    fillSources(); render();
  }
  function fillSources() {
    var sel = document.getElementById("src"), seen = {};
    G.forEach(function (g) { if (g.k === tab) seen[g.src] = (seen[g.src] || 0) + g.items.length; });
    sel.innerHTML = '<option value="">all sources</option>' + Object.keys(seen).sort(function (a, b) { return seen[b] - seen[a]; })
      .map(function (s) { return '<option value="' + esc(s) + '">' + esc(s) + ' (' + seen[s] + ')</option>'; }).join("");
  }
  document.getElementById("tab-syn").addEventListener("click", function () { setTab("syn"); });
  document.getElementById("tab-sub").addEventListener("click", function () { setTab("sub"); });
  ["q", "src", "show"].forEach(function (id) { document.getElementById(id).addEventListener(id === "q" ? "input" : "change", function () { page = 1; render(); }); });
  function why(e) { return (e && e.code ? e.code + ": " : "") + (e && e.message ? e.message : String(e)); }
  setTab("syn");
  (window.claude && window.claude.use ? window.claude.use("db") : Promise.resolve(null)).then(function (store) {
    db = store;
    if (!db) { say("No shared store here — decisions cannot be saved from this view.", "bad"); return; }
    return Promise.all([load("synonym", 1), load("subclass", 1)]).then(function (n) {
      snapshot(); render();
      var t = n[0] + n[1];
      say(t ? "Picked up decisions on " + t + " group" + (t === 1 ? "" : "s") + "." : "Ready.", "");
    });
  }).catch(function (e) { say("Could not read earlier decisions (" + why(e) + "). They are still stored — reload the page.", "bad"); });
  function load(c, attempt) {
    return db.collection(c).limit(1000).get().then(function (snap) {
      // a stored document comes back read-only: edit a copy, or the first
      // click on a group decided earlier throws and nothing happens (2026-10-02)
      snap.docs.forEach(function (d) { dec[d.id] = JSON.parse(JSON.stringify(d.data())); });
      return snap.size;
    }, function (e) {
      if (attempt < 3) return new Promise(function (r) { setTimeout(r, 600 * attempt); }).then(function () { return load(c, attempt + 1); });
      throw e;
    });
  }
})();
</script>
'''

if __name__ == "__main__":
    main(sys.argv[1])
