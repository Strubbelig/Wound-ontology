"""UML class diagram of the pipeline's own classes, read from the code.

    python scripts/uml_class_diagram.py [--overview]

Writes docs/uml/uml_classes_wound_ontology.plantuml (or
uml_overview_wound_ontology.plantuml with --overview: class names and
relations only). Render it as the README of ../Thesis says:

    java -jar ~/.vscode/extensions/jebbs.plantuml-2.18.1/plantuml.jar -tsvg \
        -o "<abs path>/Thesis/figures" docs/uml/uml_classes_wound_ontology.plantuml

Replaces the pyreverse output (classes_wound_ontology.plantuml), which guesses
associations from attribute names. Here every element comes from the syntax
tree of src/wound_ontology, nothing from a guess:

* class: every top-level `class` in the package; `abstract` when it derives
  from ABC, `enum` when from Enum (literals listed); «dataclass» / «pydantic»
  stereotypes; a base from outside the package is named as a stereotype, not
  drawn.
* attributes: annotated class fields, and `self.x = ...` in `__init__`, with
  the type taken from the annotation, else from the `__init__` parameter it was
  assigned from, else from the class it was constructed from. `@property` is a
  derived attribute (`/name`). `_x` is private (`-`), otherwise public (`+`).
* operations: public methods with their parameters and annotated types
  (defaults left out); `@staticmethod`/`@classmethod` {static}; an
  `@abstractmethod` {abstract}.
* relations:
  - generalization: a base class inside the package;
  - composition: `__init__` constructs the object it keeps (`self.x = C(...)`);
  - association: an attribute whose type names a class of the package, with
    multiplicity (`0..1` optional, `*` in a list/dict/set);
  - dependency «create»: a method other than `__init__` constructs it.
"""
from __future__ import annotations

import ast
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "wound_ontology"
OUT = ROOT / "docs" / "uml"

EXTERNAL_STEREO = {"ABC": None, "BaseModel": "pydantic", "Enum": None, "str": None,
                   "MutableMapping": "MutableMapping"}


def _dec_names(node) -> list[str]:
    out = []
    for d in node.decorator_list:
        d = d.func if isinstance(d, ast.Call) else d
        out.append(d.attr if isinstance(d, ast.Attribute) else getattr(d, "id", ""))
    return out


def _ann(a) -> str:
    return "" if a is None else re.sub(r"\s+", " ", ast.unparse(a)).replace('"', "").replace("'", "")


#: Package rows, top to bottom, in the order the pipeline runs (layout only).
ROWS = [["(top level)"],
        ["connectors", "llm", "embedding"],
        ["store", "mappers", "data_manager"],
        ["hierarchies", "fca", "reasoning", "evaluation"],
        ["owl", "knowledge_graph", "alignment", "utils"]]


def _pid(pkg: str) -> str:
    return "P_" + re.sub(r"\W", "_", pkg)


#: Longest member line before it is wrapped onto continuation lines.
WIDTH = 80
#: Java's trim() keeps an em space, so a continuation line stays indented.
INDENT = "\u2003\u2003\u2003"


def _wrap(line: str) -> list[str]:
    """Break a long operation after a comma; nothing is cut, only wrapped."""
    if len(line) <= WIDTH:
        return [line]
    out, cur = [], ""
    for part in line.split(", "):
        piece = part if not cur else cur + ", " + part
        if len(piece) > WIDTH and cur:
            out.append(cur + ","); cur = part
        else:
            cur = piece
    out.append(cur)
    return [out[0]] + [INDENT + x for x in out[1:]]


def _short(t: str) -> str:
    """`pd.DataFrame` -> `DataFrame`, `np.ndarray` -> `ndarray`; keeps the shape."""
    return re.sub(r"\b[a-z_]+\.(?=[A-Za-z_])", "", t)


class Model:
    def __init__(self) -> None:
        self.classes: dict[str, dict] = {}

    def read(self) -> None:
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            rel = path.relative_to(SRC)
            pkg = rel.parts[0] if len(rel.parts) > 1 else "(top level)"
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    if node.name in self.classes:
                        raise RuntimeError(f"two classes named {node.name}: {self.classes[node.name]['file']} and {rel}")
                    self.classes[node.name] = {"node": node, "pkg": pkg, "file": str(rel)}
        names = set(self.classes)
        for name, c in self.classes.items():
            self._describe(name, c, names)
        # An unannotated __init__ parameter takes its type from the call sites:
        # `MappingCleaner(self.term_mapper)` in Orchestrator.__init__, where
        # `term_mapper` is a TermMapper, makes MappingCleaner.term_mapper one.
        # Only when every call site agrees; then the class is described again.
        seen: dict[tuple[str, str], set[str]] = defaultdict(set)
        for owner, c in self.classes.items():
            for m in c["node"].body:
                if not isinstance(m, ast.FunctionDef):
                    continue
                for call in ast.walk(m):
                    if not (isinstance(call, ast.Call) and _ann(call.func) in names):
                        continue
                    callee = self.classes[_ann(call.func)]["node"]
                    init = next((x for x in callee.body if isinstance(x, ast.FunctionDef) and x.name == "__init__"), None)
                    if init is None:
                        continue
                    params = [a.arg for a in init.args.args if a.arg != "self"]
                    pairs = list(zip(params, call.args)) + [(k.arg, k.value) for k in call.keywords if k.arg]
                    for p, v in pairs:
                        if isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) and v.value.id == "self":
                            t = c["attrs"].get(v.attr) or c["attrs"].get("_" + v.attr) or ""
                            hit = [n for n in re.findall(r"[A-Za-z_]+", t) if n in names]
                            if len(hit) == 1:
                                seen[(_ann(call.func), p)].add(hit[0])
        self.call_types = {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}
        for name, c in self.classes.items():
            self._describe(name, c, names)

    def _describe(self, name: str, c: dict, names: set[str]) -> None:
        node = c["node"]
        bases = [_ann(b) for b in node.bases]
        decs = _dec_names(node)
        c["bases_in"] = [b for b in bases if b in names]
        c["bases_out"] = [b for b in bases if b not in names]
        c["kind"] = "enum" if "Enum" in bases else ("abstract" if "ABC" in bases else "class")
        stereo = []
        if "dataclass" in decs:
            stereo.append("dataclass")
        stereo += [EXTERNAL_STEREO.get(b, b) for b in c["bases_out"] if EXTERNAL_STEREO.get(b, b)]
        c["stereo"] = stereo
        attrs: dict[str, str] = {}
        literals: list[str] = []
        comp: dict[str, str] = {}          # attr -> class constructed in __init__
        for st in node.body:               # class-level fields
            if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                attrs[st.target.id] = _ann(st.annotation)
            elif isinstance(st, ast.Assign) and c["kind"] == "enum":
                literals += [t.id for t in st.targets if isinstance(t, ast.Name)]
        init = next((m for m in node.body if isinstance(m, ast.FunctionDef) and m.name == "__init__"), None)
        if init is not None:
            params = {a.arg: _ann(a.annotation) or getattr(self, "call_types", {}).get((name, a.arg), "")
                      for a in init.args.args + init.args.kwonlyargs}
            for st in ast.walk(init):
                if not isinstance(st, (ast.Assign, ast.AnnAssign)):
                    continue
                tg = st.targets[0] if isinstance(st, ast.Assign) else st.target
                if not (isinstance(tg, ast.Attribute) and isinstance(tg.value, ast.Name) and tg.value.id == "self"):
                    continue
                typ = _ann(st.annotation) if isinstance(st, ast.AnnAssign) else ""
                v = st.value
                if isinstance(v, ast.Call):
                    f = _ann(v.func)
                    if f in names:
                        comp[tg.attr] = f
                        typ = typ or f
                if not typ and isinstance(v, ast.Name) and params.get(v.id):
                    typ = params[v.id]
                if not typ and isinstance(v, ast.BoolOp):          # `x or C()` -> C
                    for e in v.values:
                        if isinstance(e, ast.Call) and _ann(e.func) in names:
                            comp[tg.attr] = _ann(e.func); typ = typ or _ann(e.func)
                        elif isinstance(e, ast.Name) and params.get(e.id):
                            typ = typ or params[e.id]
                if tg.attr not in attrs or (typ and not attrs[tg.attr]):
                    attrs[tg.attr] = typ
        ops, props, creates = [], {}, set()
        for m in node.body:
            if not isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            d = _dec_names(m)
            if m.name != "__init__":
                for sub in ast.walk(m):
                    if isinstance(sub, ast.Call) and _ann(sub.func) in names and _ann(sub.func) != name:
                        creates.add(_ann(sub.func))
            if "property" in d:
                props[m.name] = _ann(m.returns)
                continue
            if "setter" in d or (m.name.startswith("_") and m.name != "__init__"):
                continue
            if m.name == "__init__":
                continue
            args = [a for a in m.args.args + m.args.kwonlyargs if a.arg not in ("self", "cls")]
            sig = ", ".join(f"{a.arg}: {_short(_ann(a.annotation))}" if a.annotation else a.arg for a in args)
            if len(sig) > WIDTH:                 # long: parameter names only (the types stay in the code)
                sig = ", ".join(a.arg for a in args)
            if m.args.vararg:
                sig += (", " if sig else "") + "*" + m.args.vararg.arg
            if m.args.kwarg:
                sig += (", " if sig else "") + "**" + m.args.kwarg.arg
            ret = _short(_ann(m.returns))
            mods = ("{static} " if {"staticmethod", "classmethod"} & set(d) else "") + \
                   ("{abstract} " if "abstractmethod" in d else "")
            ops.append(f"{mods}+{'async ' if isinstance(m, ast.AsyncFunctionDef) else ''}{m.name}({sig})"
                       + (f" : {ret}" if ret else ""))
        c.update(attrs=attrs, literals=literals, comp=comp, props=props, ops=ops,
                 creates=creates - set(comp.values()))

    # ── relations ─────────────────────────────────────────────────────────────
    def relations(self) -> list[tuple]:
        names = set(self.classes)
        rel = []
        for name, c in self.classes.items():
            for b in c["bases_in"]:
                rel.append(("gen", b, name, "", ""))
            linked = set()
            for attr, typ in list(c["attrs"].items()) + list(c["props"].items()):
                hits = [n for n in re.findall(r"[A-Za-z_]+", typ) if n in names and n != name]
                for h in dict.fromkeys(hits):
                    many = bool(re.search(r"\b(list|dict|set|tuple|Iterable|Sequence)\[", typ))
                    mult = "*" if many else ("0..1" if ("None" in typ or "Optional" in typ) else "1")
                    kind = "comp" if c["comp"].get(attr) == h else "assoc"
                    rel.append((kind, name, h, attr.lstrip("_"), mult))
                    linked.add(h)
            for attr, h in c["comp"].items():
                if h not in linked and h != name:
                    rel.append(("comp", name, h, attr.lstrip("_"), "1")); linked.add(h)
            for h in sorted(c["creates"] - linked):
                rel.append(("create", name, h, "", ""))
        return rel

    # ── PlantUML ──────────────────────────────────────────────────────────────
    def plantuml(self, overview: bool) -> str:
        L = ["' Generated by scripts/uml_class_diagram.py from src/wound_ontology -- do not edit by hand.",
             f"@startuml {'uml_overview' if overview else 'uml_classes'}",
             "skinparam shadowing false", "skinparam defaultFontName Helvetica",
             "skinparam classAttributeIconSize 0", "skinparam packageStyle frame",
             "skinparam linetype polyline",
             "skinparam nodesep 18", "skinparam ranksep 40",
             "skinparam class {", "  BackgroundColor #FFFFFF", "  BorderColor #333333", "  ArrowColor #333333", "}",
             "skinparam package {", "  BorderColor #888888", "  FontColor #444444", "}",
             "hide empty members" if not overview else "hide members",
             "hide circle",
             f"title Wound ontology pipeline: {len(self.classes)} classes of src/wound_ontology"
             + (" (names and relations)" if overview else ""), ""]
        by_pkg = defaultdict(list)
        for n, c in self.classes.items():
            by_pkg[c["pkg"]].append(n)
        for pkg in sorted(by_pkg, key=lambda p: (p == "(top level)", p)):
            L.append(f'package "{pkg}" as {_pid(pkg)} {{')
            for n in sorted(by_pkg[pkg]):
                L += ["  " + x for x in self._class_block(n, overview)]
            L.append("}")
        L.append("")
        L += self._stacking(by_pkg)
        L += self._rows(by_pkg)
        arrows = {"gen": "<|--", "comp": "*--", "assoc": "-->", "create": "..>"}
        for kind, a, b, role, mult in self.relations():
            if kind == "gen":
                L.append(f"{a} {arrows[kind]} {b}")
            elif kind == "create":
                L.append(f"{a} ..> {b} : «create»")
            else:
                L.append(f'{a} {arrows[kind]} "{mult}" {b}' + (f" : {role}" if role and not overview else ""))
        L += ["", "legend right",
              "  Hollow triangle: generalization (subclass). Filled diamond: composition",
              "  (created and kept in __init__). Arrow: association, with multiplicity.",
              "  Dashed arrow «create»: a method constructs the class.",
              "  /name: property (derived). +public  -internal. {static} underlined.",
              "endlegend", "@enduml", ""]
        return "\n".join(x for x in L if x is not None)

    def _rows(self, by_pkg: dict) -> list[str]:
        """Layout only: packages in rows, in the order the pipeline runs.

        Without this every package sits on the rank below the Orchestrator and
        the drawing is three times as wide as high. A package the code gains
        later and ROWS does not name goes in the last row, and is said.
        """
        rows = [[p for p in row if p in by_pkg] for row in ROWS]
        rest = sorted(set(by_pkg) - {p for row in ROWS for p in row})
        if rest:
            print(f"[uml] packages not placed in a row, put last: {rest}")
            rows.append(rest)
        rows = [r for r in rows if r]
        out = ["' layout only: package rows"]
        for upper, lower in zip(rows, rows[1:]):
            for q in lower:
                out.append(f"{_pid(upper[0])} -[hidden]down- {_pid(q)}")
        return out

    def _stacking(self, by_pkg: dict) -> list[str]:
        """Layout only: hidden links that stack a package's groups in columns.

        Graphviz puts every unconnected group of a package side by side, so
        `llm`'s 21 response schemas made one row a third of the drawing wide.
        A hidden link asserts nothing (it is not drawn); it puts the next group
        below the previous one, in about sqrt(n) columns per package.
        """
        import math
        within = defaultdict(set)
        for kind, a, b, *_ in self.relations():
            if self.classes[a]["pkg"] == self.classes[b]["pkg"]:
                within[a].add(b); within[b].add(a)
        out = ["' layout only: hidden links stack each package's groups in columns"]
        for pkg, members in by_pkg.items():
            left, groups = set(members), []
            for n in sorted(members, key=lambda x: (-len(within[x]), x)):
                if n not in left:
                    continue
                stack, g = [n], []
                left.discard(n)
                while stack:
                    x = stack.pop(); g.append(x)
                    for y in sorted(within[x]):
                        if y in left:
                            left.discard(y); stack.append(y)
                groups.append(g)
            if len(groups) < 4:
                continue
            cols = max(2, math.ceil(math.sqrt(len(groups))))
            columns = [groups[i::cols] for i in range(cols)]
            for col in columns:
                for upper, lower in zip(col, col[1:]):
                    out.append(f"{upper[-1]} -[hidden]down- {lower[0]}")
        return out

    def _class_block(self, n: str, overview: bool) -> list[str]:
        c = self.classes[n]
        st = "".join(f" <<{s}>>" for s in c["stereo"])
        head = {"enum": "enum", "abstract": "abstract class", "class": "class"}[c["kind"]]
        if overview:
            return [f"{head} {n}{st}"]
        out = [f"{head} {n}{st} {{"]
        if c["kind"] == "enum":
            out += [f"  {x}" for x in c["literals"]]
        else:
            for a, t in c["attrs"].items():
                vis = "-" if a.startswith("_") else "+"
                out.append(f"  {vis}{a}" + (f" : {_short(t)}" if t else ""))
            for p, t in c["props"].items():
                out.append(f"  +/{p}" + (f" : {_short(t)}" if t else ""))
            if c["ops"]:
                out.append("  --")
                for o in c["ops"]:
                    out += [f"  {line}" for line in _wrap(o)]
        out.append("}")
        return out


def main(argv: list[str]) -> int:
    overview = "--overview" in argv
    m = Model(); m.read()
    text = m.plantuml(overview)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / ("uml_overview_wound_ontology.plantuml" if overview else "uml_classes_wound_ontology.plantuml")
    out.write_text(text, encoding="utf-8")
    if out.read_text(encoding="utf-8") != text:
        raise RuntimeError(f"{out} did not read back as written")
    rel = m.relations()
    from collections import Counter
    print(f"[uml] {len(m.classes)} classes in {len({c['pkg'] for c in m.classes.values()})} packages; "
          f"relations {dict(Counter(r[0] for r in rel))} -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
