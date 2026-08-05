"""The UEL CLI. One engine, several doors (spec §4.4):

    uel check [path] [--json]    compile-time pipeline: parse, resolve, check, staleness
    uel fmt [path] [--check]     the zero-config formatter
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
    if res is None or not bag.ok():
        print(bag.render(project.sources_map()))
        print("build: refused — fix compile-time errors first (compile time gates runtime)")
        return 1
    from .scheduler import build as run_build

    result = run_build(res, bag, only=args.node or None, dry_run=args.dry_run)
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

    lock = Lock.load(project.lock_path, bag)
    rep = compute(res, lock)
    if args.rank:
        from .attention import rank

        ranked = rank(res, rep, lock)
        if args.json:
            import json as _json

            print(_json.dumps([r.to_obj() for r in ranked], indent=2))
            return 0
        if not ranked:
            print(f"stale: all {len(rep.order)} executable nodes fresh — nothing to rank")
            return 0
        width = max(len(r.name) for r in ranked)
        for r in ranked:
            mark = "»" if r.frontier else "…"
            line = f"  {r.score:6.2f}  {mark} {r.name:<{width}}"
            if r.reasons:
                line += "  — " + "; ".join(r.reasons)
            print(line)
        print(f"stale: {len(ranked)} node{'s' if len(ranked) != 1 else ''} ranked by attention value "
              f"(» = frontier, buildable now); execution order is still `uel build`'s topological walk")
        return 0
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
        if sf.namespace.startswith("stdlib:"):
            continue
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
          f"{summary['validated']} validated, {summary['discrepancies']} discrepancies"
          + (f", {summary['candidate_rules']} entailment candidates emitted"
             if summary.get("candidate_rules") else ""))
    return 0 if bag.ok() else 1


def cmd_query(args: argparse.Namespace) -> int:
    # `uel query info-value <project-dir>`: the lone positional is the path,
    # not a target (targets are dotted refs and never name directories)
    if args.target and args.path == "." and Path(args.target).is_dir():
        args.path, args.target = args.target, ""
    bag = Bag()
    project, res, _ = _load_and_resolve(args.path, bag, serial=args.serial, checks=False)
    if res is None:
        print(bag.render(project.sources_map()))
        return 1
    from .lockfile import Lock

    lock = Lock.load(project.lock_path)
    if args.what == "info-value":
        from .attention import info_value
        from .staleness import compute

        ranked = info_value(res, compute(res, lock), lock)
        if args.target:
            ranked = [m for m in ranked if m.target == args.target]
            if not ranked:
                print(f"info-value: '{args.target}' carries no declared ignorance a measurement "
                      f"would remove (or is not a measurable quantity)")
                return 1
        if args.json:
            import json as _json

            print(_json.dumps([m.to_obj() for m in ranked], indent=2))
            return 0
        if not ranked:
            print("info-value: no declared ignorance anywhere — every quantity is exact or unconsumed")
            return 0
        width = max(len(m.target) for m in ranked)
        for m in ranked:
            line = (f"  {m.value:7.2f}  {m.target:<{width}}  "
                    f"[{m.ignorance:g} ignorance ({m.ignorance_note}) × {1 + m.consumers} consumers"
                    f" × {1 + m.fence_pressure:g} fence")
            line += f" @ {m.pressure_consumer}]" if m.pressure_consumer else "]"
            if m.kind == "validation":
                line += "  (validates a prediction)"
            print(line)
        print(f"info-value: {len(ranked)} candidate measurement{'s' if len(ranked) != 1 else ''}, "
              f"highest expected envelope-tightening first (ADR-0005)")
        return 0
    if not args.target:
        print("query provenance: a target is required (e.g. spar_v7.mass)")
        return 2
    from .projections import provenance

    print(provenance(res, args.target, lock))
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    from .scaffold import init, render_result

    target = Path(args.path)
    if target.exists() and not target.is_dir():
        print(f"init: '{target}' exists and is not a directory")
        return 2
    result = init(target, name=args.name, harness=args.harness, force=args.force)
    print(render_result(result, args.harness))
    return 0 if result.ok() else 1


def cmd_agenda(args: argparse.Namespace) -> int:
    bag = Bag()
    project, res, rollups = _load_and_resolve(args.path, bag, serial=getattr(args, "serial", "") or "")
    if res is None:
        print(bag.render(project.sources_map()))
        return 1
    from .attention import build_agenda, render_agenda
    from .lockfile import Lock
    from .staleness import compute

    lock = Lock.load(project.lock_path, bag)
    rep = compute(res, lock)
    errors = sum(1 for d in bag.items if d.severity == "error")
    warnings = sum(1 for d in bag.items if d.severity == "warning")
    agenda = build_agenda(res, rep, lock, rollups, errors, warnings)
    if args.json:
        import json as _json

        print(_json.dumps(agenda.to_obj(), indent=2))
        return 0
    if errors:
        print(bag.render(project.sources_map()))
    print(render_agenda(agenda, top=args.top))
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
    p_stale.add_argument("--rank", action="store_true",
                         help="value-order the stale set: where should attention go first? (ADR-0005)")

    p_hash = sub.add_parser("hash", help="show content hashes (graph, or one node with --node)")
    p_hash.add_argument("path", nargs="?", default=".")
    p_hash.add_argument("--node", help="show one node's identity + recipe breakdown")

    p_proj = sub.add_parser("project", help="compile hash-stamped projections (spec §9.1)")
    p_proj.add_argument("kind", choices=["bom", "icd", "work", "status", "all"])
    p_proj.add_argument("path", nargs="?", default=".")
    p_proj.add_argument("-o", "--out", default="out", help="output directory (default: out/)")
    p_proj.add_argument("--serial", default="", help="apply an as-built overlay (calibration/<serial>.json)")

    p_graph = sub.add_parser("graph", help="export the dependency graph")
    p_graph.add_argument("path", nargs="?", default=".")
    p_graph.add_argument("--dot", action="store_true", help="Graphviz DOT to stdout (default)")

    p_cal = sub.add_parser("calibrate", help="ingest measurements; reality writes back (spec §8)")
    p_cal.add_argument("measurements", help="JSON measurements file")
    p_cal.add_argument("path", nargs="?", default=".")
    p_cal.add_argument("--no-stubs", action="store_true", help="do not generate investigation stubs")

    p_query = sub.add_parser("query", help="ask the graph")
    p_query.add_argument("what", choices=["provenance", "info-value"])
    p_query.add_argument("target", nargs="?", default="",
                         help="e.g. spar_v7.mass or SparStaticLimit.outputs.FoS "
                              "(info-value: omit to rank every candidate measurement)")
    p_query.add_argument("path", nargs="?", default=".")
    p_query.add_argument("--serial", default="")
    p_query.add_argument("--json", action="store_true")

    p_init = sub.add_parser(
        "init", help="scaffold a UEL project and its agent harness in this repository")
    p_init.add_argument("path", nargs="?", default=".",
                        help="where the model lives (default: here)")
    p_init.add_argument("--name", default="", help="project name (default: directory name)")
    p_init.add_argument("--harness", choices=["claude", "none"], default="claude",
                        help="also write agent boot context, skill, hooks, and CI gate (default: claude)")
    p_init.add_argument("--force", action="store_true", help="overwrite existing files")

    p_agenda = sub.add_parser(
        "agenda",
        help="the standing work queue: errors, ranked stale work, epistemic debt, "
             "next measurement, tightest margins (ADR-0005)")
    p_agenda.add_argument("path", nargs="?", default=".")
    p_agenda.add_argument("--json", action="store_true")
    p_agenda.add_argument("--top", type=int, default=5, help="rows per section (default 5)")
    p_agenda.add_argument("--serial", default="", help="apply an as-built overlay")

    args = ap.parse_args(argv)
    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "fmt":
        return cmd_fmt(args)
    if args.cmd == "build":
        return cmd_build(args)
    if args.cmd == "stale":
        return cmd_stale(args)
    if args.cmd == "hash":
        return cmd_hash(args)
    if args.cmd == "project":
        return cmd_project(args)
    if args.cmd == "graph":
        return cmd_graph(args)
    if args.cmd == "calibrate":
        return cmd_calibrate(args)
    if args.cmd == "query":
        return cmd_query(args)
    if args.cmd == "agenda":
        return cmd_agenda(args)
    if args.cmd == "init":
        return cmd_init(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
