"""The curator's judgement page for the WONT addition.

    python scripts/judgement_queue_page.py DATA.json OUT.html

DATA.json comes from scripts/judgement_queue_data.py. Decisions are kept in the
artifact's shared store, collection `judgement`, one document per item:
`{v, parent, note, section, subject, when}`. The document id is `item_id()` of
the item, stable across rebuilds of the data, so a decision survives a new
version of the page. Read them back with ArtifactData before applying anything.
"""
from __future__ import annotations

import hashlib
import json
import sys


def item_id(it: dict) -> str:
    key = it.get("key") or f"{it['section']}|{it['subject'].lower()}"
    return it["section"][0] + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def main(data_path: str, out_path: str) -> None:
    data = json.load(open(data_path, encoding="utf-8"))
    items = data["items"]
    for it in items:
        it["id"] = item_id(it)
    if len({it["id"] for it in items}) != len(items):
        raise RuntimeError("two items share an id")
    payload = json.dumps(items, ensure_ascii=False).replace("</", "<\\/")
    page = TEMPLATE.replace("__ITEMS__", payload)
    open(out_path, "w", encoding="utf-8").write(page)
    print(f"wrote {out_path} ({len(items)} items)")


TEMPLATE = r'''<title>WONT Judgement Queue</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
:root{
  --ground:#F3F5F4; --panel:#FFFFFF; --ink:#16211E; --muted:#5A6863; --rule:#D6DDDA; --soft:#EAEFED;
  --accent:#0F6B60; --accent-ink:#FFFFFF;
  --bad:#B3261E; --bad-bg:#FBE6E4; --warn:#9A6200; --warn-bg:#FBF0DA; --ok:#1D7A46; --ok-bg:#E3F2E8;
  --yes:#0F6B60; --no:#6B4E3D;
  --sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme:dark;
    --ground:#0F1514; --panel:#161E1C; --ink:#E2E9E6; --muted:#93A29C; --rule:#2A3532; --soft:#1C2624;
    --accent:#3CB3A0; --accent-ink:#0F1514;
    --bad:#F08A80; --bad-bg:#3A1714; --warn:#E8B04F; --warn-bg:#33260D; --ok:#6FD39A; --ok-bg:#16301F;
    --yes:#3CB3A0; --no:#C9A48C;
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --ground:#0F1514; --panel:#161E1C; --ink:#E2E9E6; --muted:#93A29C; --rule:#2A3532; --soft:#1C2624;
  --accent:#3CB3A0; --accent-ink:#0F1514;
  --bad:#F08A80; --bad-bg:#3A1714; --warn:#E8B04F; --warn-bg:#33260D; --ok:#6FD39A; --ok-bg:#16301F;
  --yes:#3CB3A0; --no:#C9A48C;
}
body{background:var(--ground);color:var(--ink);font:15px/1.55 var(--sans)}
.wrap{max-width:1080px;margin:0 auto;padding-inline:20px;padding-block:28px 64px;display:flex;flex-direction:column;gap:18px}
h1{font-size:25px;line-height:1.2;margin:0;font-weight:600;text-wrap:balance}
.lede{color:var(--muted);margin:6px 0 0;max-width:72ch}
.bar{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--ground);padding-block:10px;border-bottom:1px solid var(--rule);display:flex;flex-direction:column;gap:10px}
.tabs{display:flex;flex-wrap:wrap;gap:6px}
.tab{font:inherit;font-size:13px;border:1px solid var(--rule);border-radius:16px;padding:4px 12px;background:var(--panel);color:var(--ink);cursor:pointer}
.tab[aria-pressed="true"]{background:var(--ink);color:var(--ground);border-color:var(--ink)}
.tab .c{font-family:var(--mono);font-size:12px;margin-left:6px;opacity:.75}
.controls{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center}
.seg{display:flex;border:1px solid var(--rule);border-radius:6px;overflow:hidden;background:var(--panel)}
.seg button{font:inherit;font-size:13px;border:0;background:transparent;color:var(--ink);padding:5px 11px;cursor:pointer;border-right:1px solid var(--rule)}
.seg button:last-child{border-right:0}
.seg button[aria-pressed="true"]{background:var(--ink);color:var(--ground)}
input[type=search],input[type=text]{font:inherit;font-size:13px;padding:6px 9px;border:1px solid var(--rule);border-radius:6px;background:var(--panel);color:var(--ink);max-width:100%}
input[type=search]{width:220px}
.status{font-size:13px;min-height:20px}
.status.bad{color:var(--bad)} .status.warn{color:var(--warn)}
.progress{height:6px;background:var(--soft);border-radius:3px;overflow:hidden}
.progress span{display:block;height:100%;background:var(--accent);width:0}
.secintro{font-size:14px;color:var(--muted);max-width:78ch;margin:0}
.secintro b{color:var(--ink);font-weight:600}
#list{display:flex;flex-direction:column;gap:10px}
.card{background:var(--panel);border:1px solid var(--rule);border-radius:8px;padding:12px 14px;display:grid;grid-template-columns:1fr minmax(170px,280px);gap:10px 16px;align-items:start}
.card.dec-yes{border-left:4px solid var(--yes)} .card.dec-no{border-left:4px solid var(--no)}
.stmt{font-size:15.5px}
.stmt .pred{font-family:var(--mono);font-size:13px;color:var(--accent);padding-inline:5px}
.stmt b{font-weight:600}
.meta{display:flex;flex-wrap:wrap;gap:4px 12px;margin-top:5px;font-size:12.5px;color:var(--muted)}
.meta .lab{color:var(--ink)}
.chip{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:500}
.chip.bad{background:var(--bad-bg);color:var(--bad)} .chip.warn{background:var(--warn-bg);color:var(--warn)} .chip.ok{background:var(--ok-bg);color:var(--ok)}
.pmids a{color:var(--accent);font-family:var(--mono);font-size:12px;margin-right:6px}
.kids{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}
.kids span{font-size:12px;background:var(--soft);border-radius:10px;padding:1px 8px}
.acts{display:flex;flex-direction:column;gap:6px}
.acts .row{display:flex;flex-wrap:wrap;gap:6px}
.btn{font:inherit;font-size:13px;padding:6px 11px;border-radius:6px;border:1px solid var(--rule);background:var(--panel);color:var(--ink);cursor:pointer;white-space:normal;text-align:left}
.btn:focus-visible,.tab:focus-visible,.seg button:focus-visible,input:focus-visible,textarea:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.btn.yes[aria-pressed="true"]{background:var(--yes);border-color:var(--yes);color:var(--accent-ink)}
.btn.no[aria-pressed="true"]{background:var(--no);border-color:var(--no);color:var(--ground)}
textarea{box-sizing:border-box;font:inherit;font-size:12.5px;padding:5px 7px;border:1px solid var(--rule);border-radius:6px;background:var(--panel);color:var(--ink);resize:vertical;min-height:30px;width:100%}
.acts input[type=text]{width:100%;box-sizing:border-box}
.flash{animation:fl .9s ease}
@keyframes fl{from{box-shadow:0 0 0 3px var(--accent)}to{box-shadow:none}}
.empty{color:var(--muted)}
@media (max-width:640px){.card{grid-template-columns:1fr}}
@media (prefers-reduced-motion:reduce){.flash{animation:none}}
</style>

<div class="wrap">
  <header>
    <h1>What waits for your judgement</h1>
    <p class="lede">Everything in the new part of WONT that nobody but the pipeline and Claude has looked at, and that a person should decide. Nothing on this page goes into WONT until you decide it. WONT’s own file is never changed; the last tab only collects notes for its next revision.</p>
  </header>
  <div class="bar">
    <div class="tabs" id="tabs" role="group" aria-label="Section"></div>
    <div class="progress" aria-hidden="true"><span id="prog"></span></div>
    <div class="controls">
      <div class="seg" id="show" role="group" aria-label="Show"></div>
      <label style="font-size:13px;color:var(--muted)">Filter <input type="search" id="q" placeholder="any word"></label>
    </div>
    <div class="status" id="status" aria-live="polite">Loading decisions…</div>
  </div>
  <p class="secintro" id="intro"></p>
  <main id="list"></main>
</div>

<script>
(function () {
  var ITEMS = __ITEMS__;
  var SECTIONS = [
    {k: "clashes", t: "Statements that contradict each other", intro: "<b>Statements from the abstracts that cannot all be true together.</b> Either a term is said to be two kinds of thing at once (a property of something <i>and</i> a piece of information, say), or a statement needs its target to be a kind the target’s own statements say it is not. All of them are left out of WONT for now. Say which side is wrong and the other side comes back in at the next rebuild.",
     opts: []},
    {k: "relations", t: "Relations on new classes", intro: "<b>Relations the abstracts state about new classes.</b> Each is found in 2 or more abstracts, fits the kinds of its two terms, and Claude read it as true in every case — but you have not seen them. They are out of WONT until you add them.",
     opts: [["yes", "Add"], ["no", "Leave out"]]},
    {k: "duplicates", t: "Possible duplicates", intro: "<b>New classes whose name another ontology already uses</b>, as a name or an exact synonym. If they mean the same thing, the new class should go and the existing one be used.",
     opts: [["yes", "Same thing — use the existing one"], ["no", "Different"]]},
    {k: "parents", t: "Waiting for a parent", intro: "<b>Classes that are not added because their parent has no parent.</b> Give the parent one (any WONT, MILD or imported class, by name) and all its children come in with it.",
     opts: [["yes", "Use this parent"], ["no", "Leave them out"]], text: "Parent class for it"},
    {k: "conflicts", t: "Contradicted by the reasoner", intro: "<b>Terms whose every suggested parent the reasoner found contradictory.</b> Usually the parent is fine and something else about the term is wrong — say which parent is right, or leave the term out.",
     opts: [["yes", "Parent is right — find the conflict"], ["no", "Leave it out"]], text: "Which parent is right"},
    {k: "fillers", t: "In only because of your axioms", intro: "<b>Classes added only because one of your axioms points at them.</b> They have a BFO type, but no checked parent.",
     opts: [["yes", "Use this parent"], ["no", "Fine as it is"]], text: "Parent class for it"},
    {k: "wont", t: "Notes for WONT", intro: "<b>Parents the abstracts suggest for classes already in WONT or MILD, which they do not have yet.</b> WONT is not changed here; a yes is a note for its next revision.",
     opts: [["yes", "Note for the next revision"], ["no", "No"]]}
  ];
  SECTIONS = SECTIONS.filter(function (s) { return ITEMS.some(function (i) { return i.section === s.k; }); });
  var dec = {}, db = null, sec = SECTIONS.length ? SECTIONS[0].k : "", show = "open", openAtStart = {};
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]; }); }
  function say(m, c) { var el = document.getElementById("status"); el.textContent = m; el.className = "status " + (c || ""); }
  function why(e) { return (e && e.code ? e.code + ": " : "") + (e && e.message ? e.message : String(e)); }
  function S(k) { return SECTIONS.find(function (s) { return s.k === k; }); }
  function snapshot() { openAtStart = {}; ITEMS.forEach(function (it) { if (!dec[it.id] || !dec[it.id].v) openAtStart[it.id] = true; }); }
  function pm(list) { return '<span class="pmids">' + (list || []).slice(0, 8).map(function (p) { return '<a href="https://pubmed.ncbi.nlm.nih.gov/' + esc(p) + '/" target="_blank" rel="noopener">' + esc(p) + '</a>'; }).join("") + ((list || []).length > 8 ? "…" : "") + '</span>'; }
  function body(it) {
    var h = "";
    if (it.section === "relations") {
      h = '<div class="stmt"><b>' + esc(it.subject) + '</b><span class="pred">' + esc(it.predicate) + '</span><b>' + esc(it.value) + '</b></div><div class="meta">' +
        (it.flags || []).map(function (f) { return '<span class="chip bad">' + esc(f) + '</span>'; }).join("") +
        '<span>' + it.abstracts + ' abstracts</span>' + pm(it.pmids) + '</div><div class="meta">' +
        (it.subject_parents.length ? '<span>' + esc(it.subject) + ' is a kind of <span class="lab">' + esc(it.subject_parents.join(", ")) + '</span></span>' : '') +
        '<span>written as: ' + esc(it.as_written.join(" · ")) + '</span>' + (it.reading ? '<span>Claude: ' + esc(it.reading) + '</span>' : '') +
        (it.elk !== "no contradiction" ? '<span>' + esc(it.elk) + '</span>' : '') + '</div>';
    } else if (it.section === "duplicates") {
      h = '<div class="stmt">New class <b>' + esc(it.subject) + '</b> <span class="meta" style="display:inline">' + esc(it.iri) + (it.bfo ? " · " + esc(it.bfo) : "") + '</span></div><div class="meta">' +
        (it.parents.length ? '<span>a kind of <span class="lab">' + esc(it.parents.join(", ")) + '</span></span>' : '') + '</div><div class="meta">' +
        it.matches.map(function (m) { return '<span>already in <b>' + esc(m.source) + '</b>: <span class="lab">' + esc(m.label) + '</span>' + (m.said.toLowerCase() !== m.label.toLowerCase() ? ' (as “' + esc(m.said) + '”)' : '') + ' <code>' + esc(m.iri) + '</code></span>'; }).join("") + '</div>';
    } else if (it.section === "parents") {
      h = '<div class="stmt"><b>' + esc(it.subject) + '</b> <span class="meta" style="display:inline">' + (it.bfo ? esc(it.bfo) : "") + '</span></div><div class="meta"><span>' + it.children.length + ' class' + (it.children.length === 1 ? '' : 'es') + ' wait for it</span>' +
        (it.now_under.length ? '<span>the abstracts put it under: ' + esc(it.now_under.join(", ")) + ' (not checked)</span>' : '') + '</div><div class="kids">' +
        it.children.slice(0, 40).map(function (c) { return '<span>' + esc(c) + '</span>'; }).join("") + (it.children.length > 40 ? '<span>…</span>' : '') + '</div>';
    } else if (it.section === "conflicts") {
      h = '<div class="stmt"><b>' + esc(it.subject) + '</b></div><div class="meta"><span>' + it.abstracts + ' abstracts</span><span>suggested parents: <span class="lab">' + esc(it.parents.join(" · ")) + '</span></span></div>';
    } else if (it.section === "fillers") {
      h = '<div class="stmt"><b>' + esc(it.subject) + '</b> <span class="meta" style="display:inline">' + esc(it.iri) + (it.bfo ? " · " + esc(it.bfo) : "") + '</span></div><div class="meta">' +
        (it.uses.length ? '<span>your axiom: ' + esc(it.uses.join(" · ")) + '</span>' : '<span>no axiom names it by this name</span>') + '</div>';
    } else if (it.section === "clashes" && it.kind === "two kinds") {
      h = '<div class="stmt"><b>' + esc(it.subject) + '</b> is said to be two kinds of thing at once, and nothing can be both:</div>' +
        it.sides.map(function (side) {
          return side.map(function (x) {
            return '<div class="meta"><span><span class="pred">' + esc(x.predicate) + '</span> makes it <span class="lab">' + esc(x.kind) + '</span>:</span>' + saidList(x.said) + '</div>';
          }).join("");
        }).join('<div class="meta"><span>— against —</span></div>');
    } else if (it.section === "clashes") {
      h = '<div class="stmt"><b>' + esc(it.subject) + '</b><span class="pred">' + esc(it.predicate) + '</span><b>' + esc(it.value) + '</b></div>' +
        '<div class="meta"><span>' + it.pmids.length + ' abstract' + (it.pmids.length === 1 ? '' : 's') + '</span>' + pm(it.pmids) + '</div>' +
        '<div class="meta"><span>This needs <span class="lab">' + esc(it.value) + '</span> to be <span class="lab">' + esc(it.needs) + '</span>. But the abstracts also say:</span></div>' +
        it.blamed.map(function (b) {
          return '<div class="meta"><span><b>' + esc(it.value) + '</b><span class="pred">' + esc(b.predicate) + '</span></span>' + saidList(b.said) + '<span>— that makes it <span class="lab">' + esc(b.kind) + '</span>.</span></div>';
        }).join("");
    } else if (it.section === "wont") {
      h = '<div class="stmt"><b>' + esc(it.subject) + '</b> <span class="meta" style="display:inline">' + esc(it.source) + ' · ' + esc(it.iri) + '</span></div><div class="meta"><span>the abstracts put it under: <span class="lab">' + esc(it.suggested.join(" · ")) + '</span></span>' +
        '<span>' + esc(it.source) + ' has it under: ' + esc(it.has.join(", ") || "nothing") + '</span><span>' + it.abstracts + ' abstracts</span></div>';
    }
    return h;
  }
  function q(p) { return "‘" + p + "’"; }
  function kinds(side) { return side.map(function (x) { return x.kind; }).filter(function (k, i, a) { return a.indexOf(k) === i; }).join(" / "); }
  function optsOf(it) {
    if (it.section !== "clashes") return S(it.section).opts;
    if (it.kind === "target") return [["out", "Leave this statement out"],
      ["keep", "Keep it — the statements on " + q(it.value) + " below are wrong"]];
    var o = it.sides.map(function (side, i) {
      return ["side" + i, "Keep " + side.map(function (x) { return q(x.predicate); }).join(", ") + " — it is " + kinds(side)];
    });
    o.push(["none", "Neither — leave all out"]);
    return o;
  }
  function saidList(list) {
    return list.map(function (x) { return '<span>' + esc(x.value) + ' <span class="meta" style="display:inline">(' + x.pmids.length + ')</span> ' + pm(x.pmids.slice(0, 3)) + '</span>'; }).join("");
  }
  function card(it) {
    var s = S(it.section), d = dec[it.id] || {};
    var cls = d.v ? (d.v === "no" || d.v === "none" || d.v === "out" ? "dec-no" : "dec-yes") : "";
    return '<article class="card ' + cls + '" id="' + it.id + '"><div>' + body(it) + '</div><div class="acts">' +
      (s.text ? '<input type="text" data-id="' + it.id + '" data-f="parent" placeholder="' + esc(s.text) + '" aria-label="' + esc(s.text) + '" value="' + esc(d.parent || "") + '">' : '') +
      '<div class="row">' + optsOf(it).map(function (o) { return '<button type="button" class="btn ' + (o[0] === "no" || o[0] === "none" || o[0] === "out" ? "no" : "yes") + '" data-id="' + it.id + '" data-v="' + o[0] + '" aria-pressed="' + (d.v === o[0]) + '">' + esc(o[1]) + '</button>'; }).join("") + '</div>' +
      '<textarea data-id="' + it.id + '" data-f="note" placeholder="Note (optional)" aria-label="Note">' + esc(d.note || "") + '</textarea></div></article>';
  }
  function tabs() {
    document.getElementById("tabs").innerHTML = SECTIONS.map(function (s) {
      var all = ITEMS.filter(function (i) { return i.section === s.k; });
      var open = all.filter(function (i) { return !(dec[i.id] && dec[i.id].v); }).length;
      return '<button type="button" class="tab" data-k="' + s.k + '" aria-pressed="' + (s.k === sec) + '">' + esc(s.t) + '<span class="c">' + open + '/' + all.length + '</span></button>';
    }).join("");
    var done = ITEMS.filter(function (i) { return dec[i.id] && dec[i.id].v; }).length;
    document.getElementById("prog").style.width = (done / Math.max(1, ITEMS.length) * 100) + "%";
  }
  function segs() {
    var opts = [["open", "Undecided"], ["done", "Decided"], ["all", "All"]];
    document.getElementById("show").innerHTML = opts.map(function (o) { return '<button type="button" data-k="' + o[0] + '" aria-pressed="' + (o[0] === show) + '">' + o[1] + '</button>'; }).join("");
  }
  function render() {
    var q = document.getElementById("q").value.trim().toLowerCase();
    var v = ITEMS.filter(function (it) {
      if (it.section !== sec) return false;
      var d = dec[it.id] && dec[it.id].v;
      if (show === "open" && !openAtStart[it.id]) return false;
      if (show === "done" && !d) return false;
      if (q && JSON.stringify(it).toLowerCase().indexOf(q) < 0) return false;
      return true;
    });
    document.getElementById("intro").innerHTML = S(sec).intro;
    document.getElementById("list").innerHTML = v.length ? v.map(card).join("") : '<p class="empty">Nothing here with these filters.</p>';
    tabs();
  }
  document.getElementById("tabs").addEventListener("click", function (e) { var b = e.target.closest("button[data-k]"); if (!b) return; sec = b.dataset.k; snapshot(); render(); });
  document.getElementById("show").addEventListener("click", function (e) { var b = e.target.closest("button[data-k]"); if (!b) return; show = b.dataset.k; snapshot(); segs(); render(); });
  document.getElementById("q").addEventListener("input", render);
  var byId = {}; ITEMS.forEach(function (it) { byId[it.id] = it; });
  var queue = Promise.resolve();
  function persist(it, what) {
    var d = dec[it.id] || {};
    var b = { v: d.v || null, parent: d.parent || "", note: d.note || "", section: it.section, subject: it.subject,
              value: it.value || "", predicate: it.predicate || "", key: it.key || "", when: new Date().toISOString() };
    dec[it.id] = b; tabs();
    if (!db) { say("Not saved: earlier decisions have not been read yet (or could not be), so saving is off to keep them from being overwritten. Reload the page.", "bad"); return; }
    say("Saving…", "warn");
    queue = queue.then(function () { return db.doc("judgement/" + it.id).set(b); })
      .then(function () { say("Saved — " + what + ".", ""); var el = document.getElementById(it.id); if (el) { el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash"); } })
      .catch(function (e) { say("Not saved: " + why(e) + ". Your other decisions are safe.", "bad"); });
  }
  document.getElementById("list").addEventListener("click", function (e) {
    try {
      var b = e.target.closest("button[data-v]"); if (!b) return;
      var it = byId[b.dataset.id]; if (!it) return;
      var d = dec[it.id] = JSON.parse(JSON.stringify(dec[it.id] || {}));
      if (S(it.section).text && b.dataset.v === "yes" && !(d.parent || "").trim()) {
        say("Type the parent class first, then press “" + b.textContent + "”.", "warn");
        var inp = document.querySelector('input[data-id="' + it.id + '"]'); if (inp) inp.focus();
        return;
      }
      d.v = d.v === b.dataset.v ? null : b.dataset.v;
      render();
      var label = optsOf(it).find(function (o) { return o[0] === d.v; });
      persist(it, (label ? label[1] : "decision withdrawn") + " — " + it.subject);
    } catch (err) { say("That click failed: " + why(err) + ". Nothing was saved.", "bad"); }
  });
  var timers = {};
  document.getElementById("list").addEventListener("input", function (e) {
    var t = e.target; if (!t.dataset || !t.dataset.f) return;
    var it = byId[t.dataset.id]; if (!it) return;
    var d = dec[it.id] = JSON.parse(JSON.stringify(dec[it.id] || {}));
    d[t.dataset.f] = t.value;
    clearTimeout(timers[it.id + t.dataset.f]);
    timers[it.id + t.dataset.f] = setTimeout(function () { persist(it, (t.dataset.f === "parent" ? "parent" : "note") + " for " + it.subject); }, 900);
  });
  snapshot(); segs(); render();
  // The store returns at most 1000 documents per read (2026-10-07: limit(2000) was refused, and every
  // reload lost sight of the saved decisions); a full page is reported, never cut silently.
  var PAGE = 1000;
  function load(store, attempt) {
    return store.collection("judgement").limit(PAGE).get().then(function (snap) {
      snap.docs.forEach(function (d) { dec[d.id] = JSON.parse(JSON.stringify(d.data())); });
      return snap.size;
    }, function (e) {
      if (e && (e.code === "invalid_argument" || e.code === "transform_error")) throw e;
      if (attempt < 3) return new Promise(function (r) { setTimeout(r, 600 * attempt); }).then(function () { return load(store, attempt + 1); });
      throw e;
    });
  }
  say("Reading earlier decisions…", "warn");
  // Saving switches on only once the earlier decisions are read: every save writes the whole
  // decision, so a save from a page that never read them would blank a stored one.
  (window.claude && window.claude.use ? window.claude.use("db") : Promise.resolve(null)).then(function (store) {
    if (!store) { say("No shared store here — decisions cannot be saved from this view.", "bad"); return; }
    return load(store, 1).then(function (n) {
      db = store; snapshot(); render();
      if (n >= PAGE) { say("Picked up " + n + " earlier decisions — that is the most one read returns, so some may be missing from view. Tell Claude.", "bad"); return; }
      say(n ? "Picked up " + n + " earlier decision" + (n === 1 ? "" : "s") + "." : "Ready.", "");
    });
  }).catch(function (e) { say("Could not read earlier decisions (" + why(e) + "). They are still stored, and saving is paused so nothing stored is overwritten — reload the page.", "bad"); });
})();
</script>
'''

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
