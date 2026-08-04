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
            from .checker import run_checks

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


def _load_and_resolve(path: str, bag: Bag):
    project = load_project(path, bag)
    res = None
    if not bag.errors:
        res = resolve_project(project, bag)
        if res is not None:
            from .checker import run_checks

            run_checks(res, bag, lock=False)
    return project, res


def cmd_build(args: argparse.Namespace) -> int:
    bag = Bag()
    project, res = _load_and_resolve(args.path, bag)
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
    project, res = _load_and_resolve(args.path, bag)
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
    project, res = _load_and_resolve(args.path, bag)
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
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
