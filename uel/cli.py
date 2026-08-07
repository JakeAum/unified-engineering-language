"""The UEL CLI. One engine, several doors (spec §4.4):

    uel check [path] [--json]    compile-time pipeline: parse, resolve, check, staleness
    uel fmt [path] [--check]     the zero-config formatter
    uel doctor [path] [--strict] the checkup: drift, epistemic debt, trust ledger
    uel --version

Later phases add: build, stale, hash, graph, project, calibrate, query.
Exit codes: 0 clean, 1 diagnostics with errors, 2 usage/internal.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .diagnostics import Bag
from .formatter import format_ast
from .parser import parse_text
from .project import load_project
from .resolver import resolve_project
from .uast import fingerprint

def cmd_check(args: argparse.Namespace) -> int:
    bag = Bag()
    project = load_project(args.path, bag)
    res = None
    if not bag.errors:
        res = resolve_project(project, bag)
        if res is not None:
            from .calibration import apply_overlays
            from .checker import run_checks

            apply_overlays(res, getattr(args, "serial", "") or "")
            run_checks(res, bag, lock=not args.no_lock)
    if args.json:
        print(bag.to_json())
    else:
        out = bag.render(project.sources_map())
        if out:
            print(out)
        if bag.ok():
            n = len(res.doc.nodes) if res else 0
            print(f"check: ok ({n} nodes, {len(bag.items)} advisories)" if bag.items
                  else f"check: ok ({n} nodes)")
    return 0 if bag.ok() else 1

def _load_and_resolve(path: str, bag: Bag, serial: str = "", checks: bool = True):
    project = load_project(path, bag)
    res = None
    rollups: dict = {}
    if not bag.errors:
        res = resolve_project(project, bag)
        if res is not None:
            from .calibration import apply_overlays

            apply_overlays(res, serial)
            if checks:
                from .checker import run_checks

                rollups = run_checks(res, bag, lock=False) or {}
    return project, res, rollups

def cmd_build(args: argparse.Namespace) -> int:
    bag = Bag()
    project, res, _ = _load_and_resolve(args.path, bag, serial=getattr(args, "serial", "") or "")
    if res is None or bag.gates_runtime():
        print(bag.render(project.sources_map()))
        print("build: refused — fix compile-time errors first (compile time gates runtime)")
        return 1
    from .scheduler import build as run_build

    result = run_build(res, bag, only=args.node or None, dry_run=args.dry_run)
    if not args.dry_run:
        # the pre-build check judged the *old* lock; re-verdict targets and
        # seams against the values this build just produced
        from . import contracts, envelopes
        from .lockfile import Lock

        bag.items = [d for d in bag.items
                     if d.code not in ("UEL0804", "UEL0805", "UEL0806", "UEL0808", "UEL0809")]
        lk = Lock.load(project.lock_path, bag)
        envelopes.check_locked(res, bag, lk)
        contracts.check(res, bag, lk)
    out = bag.render(project.sources_map())
    if out:
        print(out)
    verb = "would run" if args.dry_run else "ran"
    print(f"build: {verb} {len(result.ran)}, skipped {len(result.skipped)} fresh, "
          f"{len(result.failed)} failed")
    return 0 if result.ok() and bag.ok() else 1

def cmd_stale(args: argparse.Namespace) -> int:
    bag = Bag()
    project, res, _ = _load_and_resolve(args.path, bag)
    if res is None:
        print(bag.render(project.sources_map()))
        return 1
    from .lockfile import Lock
    from .staleness import compute

    rep = compute(res, Lock.load(project.lock_path, bag))
    if args.json:
        import json as _json

        print(_json.dumps(
            {n: {"status": s.status, "reasons": s.reasons, "upstream": s.upstream}
             for n, s in rep.states.items()}, indent=2))
        return 0
    if not rep.order:
        print("stale: no executable nodes in this graph")
        return 0
    width = max(len(n) for n in rep.order)
    for n in rep.order:
        s = rep.states[n]
        mark = {"fresh": "·", "stale": "STALE", "missing": "MISSING"}.get(s.status, s.status)
        line = f"  {n:<{width}}  {mark}"
        if s.reasons:
            line += "  — " + "; ".join(s.reasons)
        print(line)
    stale = rep.stale()
    print(f"stale: {len(stale)} of {len(rep.order)} executable nodes need work"
          if stale else f"stale: all {len(rep.order)} executable nodes fresh")
    return 0

def cmd_hash(args: argparse.Namespace) -> int:
    bag = Bag()
    project, res, _ = _load_and_resolve(args.path, bag)
    if res is None:
        print(bag.render(project.sources_map()))
        return 1
    from .hashing import graph_hash, node_hash
    from .lockfile import Lock
    from .staleness import compute

    pol = project.tolerances
    if args.node:
        node = res.doc.nodes.get(args.node)
        if node is None:
            print(f"hash: no node named '{args.node}'")
            return 1
        print(f"{args.node}")
        print(f"  node:   {node_hash(node, pol)}")
        rep = compute(res, Lock.load(project.lock_path, bag))
        st = rep.states.get(args.node)
        if st:
            print(f"  recipe: {st.recipe}")
            for part, h in st.parts.items():
                if part == "inputs":
                    for k, v in h.items():
                        print(f"    input {k}: {v}")
                else:
                    print(f"    {part}: {h}")
        return 0
    print(f"graph {graph_hash(res.doc, pol)}")
    print(f"  ({len(res.doc.nodes)} nodes, edition {res.doc.edition})")
    return 0

def cmd_fmt(args: argparse.Namespace) -> int:
    bag = Bag()
    project = load_project(args.path, bag)
    if bag.errors:
        print(bag.render(project.sources_map()), file=sys.stderr)
        return 1
    changed: list[str] = []
    failed = False
    for sf in project.files:
        if sf.namespace.startswith("stdlib:"): continue
        fbag = Bag()
        ast = parse_text(sf.text, sf.rel, fbag)
        if fbag.errors:
            print(fbag.render({sf.rel: sf.text}), file=sys.stderr)
            failed = True
            continue
        formatted = format_ast(ast)
        if formatted != sf.text:
            # safety: formatting must preserve meaning
            fbag2 = Bag()
            ast2 = parse_text(formatted, sf.rel, fbag2)
            if fbag2.errors or fingerprint(ast2) != fingerprint(ast):
                print(f"fmt: INTERNAL: reformat of {sf.rel} would change meaning; left untouched",
                      file=sys.stderr)
                failed = True
                continue
            changed.append(sf.rel)
            if not args.check:
                sf.path.write_text(formatted, encoding="utf-8")
    if args.check:
        for rel in changed:
            print(f"would reformat {rel}")
        return 1 if (changed or failed) else 0
    for rel in changed:
        print(f"reformatted {rel}")
    return 1 if failed else 0

def cmd_project(args: argparse.Namespace) -> int:
    bag = Bag()
    project, res, rollups = _load_and_resolve(args.path, bag, serial=args.serial)
    if res is None or not bag.ok():
        print(bag.render(project.sources_map()))
        print("project: refused — projections compile only from a graph that checks clean")
        return 1
    from .lockfile import Lock
    from . import projections as P

    lock = Lock.load(project.lock_path, bag)
    outdir = Path(args.path) / args.out if not Path(args.out).is_absolute() else Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    kinds = ["bom", "icd", "work", "status"] if args.kind == "all" else [args.kind]
    for kind in kinds:
        if kind == "bom":
            text = P.bom(res, lock, rollups)
        elif kind == "icd":
            text = P.icd(res, lock)
        elif kind == "work":
            text = P.work_instructions(res, lock)
        else:
            text = P.status(res, lock)
        suffix = f"-{args.serial}" if args.serial else ""
        p = outdir / f"{kind}{suffix}.md"
        p.write_text(text, encoding="utf-8")
        print(f"project: wrote {p}")
    return 0

def cmd_agent(args: argparse.Namespace) -> int:
    from .agentdoc import briefing

    sys.stdout.write(briefing(commands=getattr(args, "_commands", None)))
    return 0

def cmd_init(args: argparse.Namespace) -> int:
    from .agentdoc import init_project

    root = Path(args.path)
    root.mkdir(parents=True, exist_ok=True)
    written = init_project(root, args.name or root.resolve().name)
    for p in written:
        print(f"init: wrote {p}")
    print(f"init: skill installed at {root / '.claude' / 'skills' / 'uel-engineer'}")
    print(f"init: next -> uel check {args.path} && uel build {args.path}; orient with `uel agent`")
    return 0

def cmd_skill(args: argparse.Namespace) -> int:
    from .agentdoc import SKILL_DIR, skill_install

    if args.action == "show":
        sys.stdout.write((SKILL_DIR / "SKILL.md").read_text(encoding="utf-8"))
        return 0
    dest = skill_install(Path(args.path))
    print(f"skill: installed uel-engineer at {dest}")
    print("skill: harnesses that read .claude/skills/ load it automatically; others can read SKILL.md directly")
    return 0

def cmd_pack(args: argparse.Namespace) -> int:
    bag = Bag()
    project, res, _ = _load_and_resolve(args.path, bag, checks=False)
    if res is None:
        print(bag.render(project.sources_map()))
        return 1
    from .lockfile import Lock
    from .projections import pack

    sys.stdout.write(pack(res, Lock.load(project.lock_path, bag), args.node))
    return 0

def cmd_graph(args: argparse.Namespace) -> int:
    bag = Bag()
    project, res, _ = _load_and_resolve(args.path, bag, checks=False)
    if res is None:
        print(bag.render(project.sources_map()))
        return 1
    from . import projections as P

    sys.stdout.write(P.dot(res))
    return 0

def cmd_calibrate(args: argparse.Namespace) -> int:
    import json as _json

    bag = Bag()
    project, res, _ = _load_and_resolve(args.path, bag, checks=False)
    if res is None:
        print(bag.render(project.sources_map()))
        return 1
    try:
        payload = _json.loads(Path(args.measurements).read_text(encoding="utf-8"))
    except (OSError, _json.JSONDecodeError) as e:
        print(f"calibrate: cannot read measurements: {e}")
        return 1
    from .calibration import ingest

    summary = ingest(res, bag, payload, write_stubs=not args.no_stubs)
    out = bag.render(project.sources_map())
    if out:
        print(out)
    print(f"calibrate: {summary['applied']} applied, {summary['tightened']} tightened, "
          f"{summary['validated']} validated, {summary['discrepancies']} discrepancies")
    return 0 if bag.ok() else 1

def cmd_doctor(args: argparse.Namespace) -> int:
    """The checkup (uel/doctor.py). Reads; never builds, repairs, or files —
    reporting upstream is an explicit decision, not a side effect of an audit
    (the never-files rule, `0007-doctor-and-upstream-issues.md` §Framing).
    `--strict` is the CI gate: nonzero on error-severity findings only."""
    from . import doctor as D

    checkup, bag = D.run(args.path)
    if bag.errors:
        print(bag.render())
        print("doctor: cannot audit a project that does not resolve — run `uel check` first")
        return 1
    if args.json:
        print(D.to_json(checkup))
    else:
        print(D.render(checkup))
    return 1 if (args.strict and checkup.errors()) else 0

def cmd_query(args: argparse.Namespace) -> int:
    bag = Bag()
    path = args.path
    if args.what == "instances" and args.target and path == ".":
        path = args.target  # `uel query instances <dir>` — no target for this query
    project, res, _ = _load_and_resolve(path, bag, serial=args.serial, checks=False)
    if res is None:
        print(bag.render(project.sources_map()))
        return 1
    from .lockfile import Lock
    from .projections import instances, provenance

    if args.what == "instances":
        sys.stdout.write(instances(res))
        return 0
    if args.what == "sensitivity":
        from .scheduler import sensitivity

        sys.stdout.write(sensitivity(res, args.target, Lock.load(project.lock_path), bag))
        return 0
    print(provenance(res, args.target, Lock.load(project.lock_path)))
    return 0

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="uel", description="UEL — Unified Engineering Language")
    ap.add_argument("--version", action="version", version=f"uel {__version__}")
    sub = ap.add_subparsers(dest="cmd")

    p_check = sub.add_parser("check", help="run the compile-time pipeline (no cores executed)")
    p_check.add_argument("path", nargs="?", default=".")
    p_check.add_argument("--json", action="store_true", help="emit structured diagnostics")
    p_check.add_argument("--no-lock", action="store_true", help="skip staleness (lock) comparison")

    p_fmt = sub.add_parser("fmt", help="format .uel sources in place")
    p_fmt.add_argument("path", nargs="?", default=".")
    p_fmt.add_argument("--check", action="store_true", help="fail if anything would change")

    p_build = sub.add_parser("build", help="execute stale cores in dependency order (model runtime)")
    p_build.add_argument("path", nargs="?", default=".")
    p_build.add_argument("--node", action="append", help="build only this node (repeatable)")
    p_build.add_argument("--dry-run", action="store_true", help="show what would run")

    p_stale = sub.add_parser("stale", help="what does the current state invalidate?")
    p_stale.add_argument("path", nargs="?", default=".")
    p_stale.add_argument("--json", action="store_true")

    p_hash = sub.add_parser("hash", help="show content hashes (graph, or one node with --node)")
    p_hash.add_argument("path", nargs="?", default=".")
    p_hash.add_argument("--node", help="show one node's identity + recipe breakdown")

    p_proj = sub.add_parser("project", help="compile hash-stamped projections (spec §9.1)")
    p_proj.add_argument("kind", choices=["bom", "icd", "work", "status", "all"])
    p_proj.add_argument("path", nargs="?", default=".")
    p_proj.add_argument("-o", "--out", default="out", help="output directory (default: out/)")
    p_proj.add_argument("--serial", default="", help="apply an as-built overlay (calibration/<serial>.json)")

    p_agent = sub.add_parser("agent", help="the tool briefs the agent using it (generated from live kernel tables)")
    _ = p_agent

    p_init = sub.add_parser("init", help="scaffold a green-by-construction UEL project (incl. agent skill)")
    p_init.add_argument("path", nargs="?", default=".")
    p_init.add_argument("--name", default="", help="project name (default: directory name)")

    p_skill = sub.add_parser("skill", help="the packaged agent skill: show it, or install into a project")
    p_skill.add_argument("action", choices=["show", "install"])
    p_skill.add_argument("path", nargs="?", default=".")

    p_pack = sub.add_parser("pack", help="review dossier: one node's full epistemic chain, context-sized (ADR-0008)")
    p_pack.add_argument("node", help="analysis node to pack (e.g. LinkMargin)")
    p_pack.add_argument("path", nargs="?", default=".")

    p_graph = sub.add_parser("graph", help="export the dependency graph")
    p_graph.add_argument("path", nargs="?", default=".")
    p_graph.add_argument("--dot", action="store_true", help="Graphviz DOT to stdout (default)")

    p_cal = sub.add_parser("calibrate", help="ingest measurements; reality writes back (spec §8)")
    p_cal.add_argument("measurements", help="JSON measurements file")
    p_cal.add_argument("path", nargs="?", default=".")
    p_cal.add_argument("--no-stubs", action="store_true", help="do not generate investigation stubs")

    p_doc = sub.add_parser("doctor", help="audit a model: drift, epistemic debt, and the trust ledger")
    p_doc.add_argument("path", nargs="?", default=".")
    p_doc.add_argument("--strict", action="store_true",
                       help="exit nonzero on error-severity findings (the CI gate)")
    p_doc.add_argument("--json", action="store_true", help="emit the structured checkup")

    p_query = sub.add_parser("query", help="ask the graph")
    p_query.add_argument("what", choices=["provenance", "instances", "sensitivity"])
    p_query.add_argument("target", nargs="?", default="",
                         help="provenance: a value ref; sensitivity: an analysis node "
                              "(elasticities by perturbation, v0.6)")
    p_query.add_argument("path", nargs="?", default=".")
    p_query.add_argument("--serial", default="")

    args = ap.parse_args(argv)
    if args.cmd == "agent":
        args._commands = sorted(sub.choices)
        return cmd_agent(args)
    if args.cmd == "init":
        return cmd_init(args)
    if args.cmd == "skill":
        return cmd_skill(args)
    if args.cmd == "check": return cmd_check(args)
    if args.cmd == "fmt": return cmd_fmt(args)
    if args.cmd == "build": return cmd_build(args)
    if args.cmd == "stale": return cmd_stale(args)
    if args.cmd == "hash": return cmd_hash(args)
    if args.cmd == "project": return cmd_project(args)
    if args.cmd == "pack": return cmd_pack(args)
    if args.cmd == "graph": return cmd_graph(args)
    if args.cmd == "calibrate": return cmd_calibrate(args)
    if args.cmd == "doctor": return cmd_doctor(args)
    if args.cmd == "query": return cmd_query(args)
    ap.print_help()
    return 2

if __name__ == "__main__": raise SystemExit(main())
