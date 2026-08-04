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

    args = ap.parse_args(argv)
    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "fmt":
        return cmd_fmt(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
