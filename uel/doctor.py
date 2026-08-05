"""`uel doctor` — the checkup, and the upstream issue it writes for you (ADR-0007).

Two audiences, one pass:

**Your project** (`user` findings) — the drift and debt the graph can see about
itself: compiled reports that were *doctored* (hand-edited after compilation,
still claiming their graph hash) or merely *stale*; a lock that disagrees with
the model; results nobody judged; discrepancies nobody investigated.

**The kernel** (`kernel` findings) — evidence that UEL itself is wrong, gathered
on real data the maintainers do not have: the checker raising instead of
diagnosing, the formatter failing idempotence, a graph that will not survive its
own canonical round-trip, errors shipped without the reason the spec promises,
staleness dishonesty. These are the findings worth a GitHub issue, and this
module writes that issue as a typed claim with provenance and a repro — the
org-to-org channel (program §7.1), made mechanical.

The split is the point. A user-class finding is *your* work; a kernel-class
finding is *ours*, and a user who has to write the bug report by hand mostly
doesn't. What the issue may contain is deliberately narrow: codes, structure,
counts, versions — never quantity values, doc strings, or requirement text,
unless `--full-evidence` is given. The upstream repository is public; a
proprietary hardware model must not leak into it because a tool was helpful.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .diagnostics import CODES, Bag
from .lockfile import Lock
from .project import load_project
from .projections import verify_seal
from .resolver import resolve_project

UPSTREAM_DEFAULT = "JakeAum/unified-engineering-language"

SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


@dataclass
class Finding:
    code: str  # DOCTOR-xxx
    audience: str  # "user" | "kernel"
    severity: str  # error | warning | info
    title: str
    detail: str
    advice: str = ""
    repro: str = ""
    evidence: dict = field(default_factory=dict)  # structural only; see redaction note
    sensitive: dict = field(default_factory=dict)  # withheld unless --full-evidence

    def fingerprint(self) -> str:
        """Stable across runs and machines, so re-filing the same defect is
        detectable. Deliberately excludes paths, timestamps, and versions —
        the same bug from two users should collide, not multiply."""
        basis = json.dumps({"code": self.code, "evidence": self.evidence},
                           sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]

    def to_obj(self, full: bool = False) -> dict:
        o = {
            "code": self.code, "audience": self.audience, "severity": self.severity,
            "title": self.title, "detail": self.detail, "fingerprint": self.fingerprint(),
        }
        if self.advice:
            o["advice"] = self.advice
        if self.repro:
            o["repro"] = self.repro
        if self.evidence:
            o["evidence"] = self.evidence
        if self.sensitive:
            o["withheld"] = sorted(self.sensitive) if not full else self.sensitive
        return o


@dataclass
class Checkup:
    findings: list[Finding] = field(default_factory=list)
    project_rel: str = "."
    checked: list[str] = field(default_factory=list)

    def add(self, f: Finding) -> None:
        self.findings.append(f)

    def kernel(self) -> list[Finding]:
        return [f for f in self.findings if f.audience == "kernel"]

    def user(self) -> list[Finding]:
        return [f for f in self.findings if f.audience == "user"]

    def sorted(self) -> list[Finding]:
        return sorted(self.findings,
                      key=lambda f: (SEVERITY_RANK.get(f.severity, 3), f.audience != "kernel", f.code))

    def to_obj(self, full: bool = False) -> dict:
        return {
            "uel": __version__,
            "project": self.project_rel,
            "checks_run": self.checked,
            "summary": {
                "kernel": len(self.kernel()), "user": len(self.user()),
                "errors": sum(1 for f in self.findings if f.severity == "error"),
            },
            "findings": [f.to_obj(full) for f in self.sorted()],
        }


def environment() -> dict:
    return {
        "uel": __version__,
        "python": platform.python_version(),
        "platform": platform.system(),
    }


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


def _check_projections(root: Path, res, lock: Lock, c: Checkup) -> None:
    """Doctored vs stale, told apart exactly (spec §1.4, §9.1)."""
    from .hashing import graph_hash

    outdir = root / "out"
    if not outdir.is_dir():
        return
    current = graph_hash(res.doc, res.project.tolerances)[7:19]
    for p in sorted(outdir.glob("*.md")):
        rel = f"out/{p.name}"
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        intact, recorded, recomputed = verify_seal(text)
        stamped = ""
        for line in text.splitlines()[:8]:
            if "graph " in line and "edition" in line:
                stamped = line.split("graph ", 1)[1].split(" ", 1)[0].strip(" .·")
                break
        if not recorded:
            c.add(Finding(
                "DOCTOR-101", "user", "info",
                f"{rel} predates integrity sealing",
                "This projection carries no body digest, so hand-edits cannot be proven "
                "either way. It was compiled by an older kernel.",
                advice="regenerate it: `uel project all` — after that its integrity is checkable",
                evidence={"artifact": p.name},
            ))
            continue
        if not intact:
            c.add(Finding(
                "DOCTOR-102", "user", "error",
                f"{rel} was edited after it was compiled",
                "The body no longer matches the digest compiled into it. A compiled "
                "projection that has been hand-edited is the drift failure mode: the "
                "document now disagrees with the graph it claims to come from, and "
                "nothing downstream knows.",
                advice="put the change in the model, not the report, then `uel project all`. "
                       "If the report was right and the model was wrong, that is a model bug — "
                       "fix it at the source and let the projection follow.",
                repro="uel doctor",
                evidence={"artifact": p.name, "recorded": recorded, "recomputed": recomputed},
            ))
            continue
        if stamped and stamped != current:
            c.add(Finding(
                "DOCTOR-103", "user", "warning",
                f"{rel} is stale",
                f"Compiled from graph {stamped}; the graph is now {current}. The report is "
                "intact and honest — it is simply out of date.",
                advice="`uel project all` to recompile",
                evidence={"artifact": p.name},
            ))


def _check_lock_integrity(res, lock: Lock, c: Checkup) -> None:
    """Every recorded output carries the hash that gives it identity. If that
    hash does not recompute from the recorded value, content addressing is
    lying about what it addresses — and every consumer inherits the lie."""
    from .hashing import output_value_hash

    pol = res.project.tolerances
    bad: list[str] = []
    for name, entry in sorted(lock.nodes.items()):
        for oname, out in sorted(entry.outputs.items()):
            if out.artifact or not out.hash or out.value is None:
                continue
            try:
                recomputed = output_value_hash(out.value, out.unit, out.unc, pol)
            except Exception:
                bad.append(f"{name}.{oname}")
                continue
            if recomputed != out.hash:
                bad.append(f"{name}.{oname}")
    if bad:
        c.add(Finding(
            "DOCTOR-201", "kernel", "error",
            "recorded output hashes do not recompute from their recorded values",
            "A lock entry's output hash is the identity downstream nodes consume. Where it "
            "disagrees with the value it is supposed to address, staleness is computed "
            "against a fiction: consumers can be called fresh against a value that never "
            "produced that hash.",
            repro="uel build <project> && uel doctor <project>",
            evidence={"check": "output_hash_mismatch", "count": len(bad)},
            sensitive={"outputs": sorted(bad)[:20]},
        ))


def _check_staleness_honesty(res, lock: Lock, c: Checkup) -> None:
    """Grade the oracle on the user's own graph (program §5.2).

    Perturb a consumed value far above tolerance *in memory*, recompute the
    stale set, and compare it against the reachability cone computed
    independently from the edge structure. Under-invalidation — a consumer of a
    changed value still called fresh — is the failure that silently ships wrong
    numbers, and it is a kernel defect. Over-invalidation is the declared
    conservative direction and is merely noted. Nothing is written to disk.
    """
    from .staleness import compute

    if not lock.nodes:
        return  # nothing built yet; the oracle has nothing to be honest about

    quantities: list[tuple[str, object]] = []
    for (consumer, local), rr in sorted(res.known_refs.items()):
        if rr.kind == "quantity" and rr.quantity is not None and rr.quantity.value is not None:
            quantities.append((rr.target, rr.quantity))
    seen: set[str] = set()
    sampled = []
    for target, q in quantities:
        if target not in seen:
            seen.add(target)
            sampled.append((target, q))
    sampled = sampled[:8]  # the doctor must stay a checkup, not a test campaign

    # consumer edges: producing node -> consumers, over knowns
    downstream: dict[str, set[str]] = {}
    by_target: dict[str, set[str]] = {}
    for (consumer, _), rr in res.known_refs.items():
        by_target.setdefault(rr.target, set()).add(consumer)
        downstream.setdefault(rr.node, set()).add(consumer)

    def cone(seed_nodes: set[str]) -> set[str]:
        out, work = set(), list(seed_nodes)
        while work:
            n = work.pop()
            for d in downstream.get(n, ()):
                if d not in out:
                    out.add(d)
                    work.append(d)
        return out

    baseline = {n: s.status for n, s in compute(res, lock).states.items()}
    under: list[str] = []
    for target, q in sampled:
        original = q.value
        try:
            if isinstance(original, tuple):
                q.value = (original[0] + 1000.0, original[1] + 1000.0)
            else:
                q.value = float(original) + 1000.0
            after = compute(res, lock).states
            direct = by_target.get(target, set())
            expected = direct | cone(direct)
            missed = sorted(
                n for n in expected
                if n in after and after[n].status == "fresh" and baseline.get(n) == "fresh"
            )
            under.extend(f"{target}->{n}" for n in missed)
        except Exception:
            c.add(Finding(
                "DOCTOR-203", "kernel", "error",
                "the staleness oracle raised while recomputing a perturbed graph",
                "Perturbing a consumed quantity made staleness computation raise.",
                repro="uel stale <project>",
                evidence={"check": "staleness_raised",
                          "traceback_tail": traceback.format_exc(limit=4).splitlines()[-1][:200]},
            ))
        finally:
            q.value = original

    if under:
        c.add(Finding(
            "DOCTOR-204", "kernel", "error",
            "staleness under-invalidates: a consumer of a changed value stayed fresh",
            "A quantity was moved far beyond its declared tolerance and nodes that consume "
            "it (directly or transitively) were still reported fresh. Under-invalidation is "
            "the one direction staleness may never fail in — it ships numbers computed from "
            "inputs that no longer exist.",
            repro="uel stale <project>  # after changing the named input",
            evidence={"check": "staleness_under_invalidation", "count": len(under)},
            sensitive={"edges": sorted(under)[:20]},
        ))


def _check_diagnostic_quality(bag: Bag, c: Checkup) -> None:
    """The spec makes diagnostic quality a feature, so a bare error is a defect."""
    unregistered = sorted({d.code for d in bag.items if d.code not in CODES})
    if unregistered:
        c.add(Finding(
            "DOCTOR-301", "kernel", "error",
            "diagnostics emitted with unregistered codes",
            "Every code must be in the registry so it can be documented and matched.",
            repro="uel check --json <project>",
            evidence={"codes": unregistered},
        ))
    bare = sorted({d.code for d in bag.items if d.severity == "error" and not d.reason})
    if bare:
        c.add(Finding(
            "DOCTOR-302", "kernel", "warning",
            "error diagnostics shipped without a stated reason",
            "Agents iterate against errors, so an error that says what failed but not why "
            "costs a round trip. These codes fired on a real model with no `reason`.",
            repro="uel check --json <project>",
            evidence={"codes": bare},
        ))


def _check_formatter_idempotence(project, c: Checkup) -> None:
    from .formatter import format_ast
    from .parser import parse_text
    from .uast import fingerprint

    for sf in project.files:
        if sf.namespace.startswith("stdlib:"):
            continue
        bag = Bag()
        ast = parse_text(sf.text, sf.rel, bag)
        if bag.errors:
            continue
        once = format_ast(ast)
        bag2 = Bag()
        ast2 = parse_text(once, sf.rel, bag2)
        if bag2.errors:
            c.add(Finding(
                "DOCTOR-303", "kernel", "error",
                "formatter output does not parse",
                "Reformatting a valid source produced text the parser rejects.",
                repro="uel fmt <project>",
                evidence={"check": "format_output_unparseable"},
                sensitive={"file": sf.rel},
            ))
            continue
        if fingerprint(ast2) != fingerprint(ast):
            c.add(Finding(
                "DOCTOR-304", "kernel", "error",
                "formatter changed the meaning of a source file",
                "The AST fingerprint moved across a reformat. The formatter must be "
                "meaning-preserving.",
                repro="uel fmt <project>",
                evidence={"check": "format_not_meaning_preserving"},
                sensitive={"file": sf.rel},
            ))
        elif format_ast(ast2) != once:
            c.add(Finding(
                "DOCTOR-305", "kernel", "error",
                "formatter is not idempotent",
                "fmt(fmt(x)) != fmt(x) on a real source file, so formatting churns diffs "
                "forever and `--check` can never settle.",
                repro="uel fmt --check <project>",
                evidence={"check": "format_not_idempotent"},
                sensitive={"file": sf.rel},
            ))


def _check_roundtrip(res, c: Checkup) -> None:
    from .graph import GraphDoc

    try:
        once = res.doc.to_canonical()
        doc2, errors = GraphDoc.from_obj(json.loads(once.decode("utf-8")))
    except Exception:
        c.add(Finding(
            "DOCTOR-306", "kernel", "error",
            "the resolved graph cannot be canonically encoded",
            "Canonical encoding raised on a graph the checker accepted.",
            repro="uel hash <project>",
            evidence={"check": "canonical_encode_raised",
                      "traceback_tail": traceback.format_exc(limit=3).splitlines()[-1][:200]},
        ))
        return
    if errors or doc2 is None:
        c.add(Finding(
            "DOCTOR-307", "kernel", "error",
            "a resolved graph fails its own schema on re-read",
            "The kernel produced a document its own reader rejects — the round-trip "
            "conformance property, violated on real data.",
            repro="uel hash <project>",
            evidence={"check": "roundtrip_schema_errors", "count": len(errors or [])},
        ))
    elif doc2.to_canonical() != once:
        c.add(Finding(
            "DOCTOR-308", "kernel", "error",
            "canonical encoding is not a fixpoint",
            "decode∘encode changed the bytes, so content hashes are not stable identities.",
            repro="uel hash <project>",
            evidence={"check": "canonical_not_fixpoint"},
        ))


def _check_epistemic_debt(res, lock: Lock, bag: Bag, c: Checkup) -> None:
    from .attention import build_agenda
    from .staleness import compute

    rep = compute(res, lock)
    agenda = build_agenda(res, rep, lock, {}, 0, 0)
    if agenda.pending_judgments:
        c.add(Finding(
            "DOCTOR-104", "user", "warning",
            f"{len(agenda.pending_judgments)} computed result(s) nobody judged",
            "An analysis that ran but was never judged is debt: the number exists, the "
            "argument does not. Judgment is what makes an analysis a claim.",
            advice="read the outputs and record `judgment accepted \"…\" doubts \"…\"`",
            evidence={"count": len(agenda.pending_judgments)},
            sensitive={"nodes": agenda.pending_judgments},
        ))
    if agenda.discrepancies:
        c.add(Finding(
            "DOCTOR-105", "user", "warning",
            f"{len(agenda.discrepancies)} open discrepancy(ies) between model and reality",
            "Reality disagreed with a model and the investigation is still open.",
            advice="resolve each as an analysis of its own — 'why was the prediction wrong'",
            evidence={"count": len(agenda.discrepancies)},
        ))
    if agenda.candidate_rules:
        c.add(Finding(
            "DOCTOR-106", "user", "info",
            f"{len(agenda.candidate_rules)} unreviewed entailment candidate(s)",
            "Discrepancies proposed structural-claim rules that nobody has reviewed. "
            "Reviewed candidates are how the shipped taxonomy gets less wrong.",
            advice="review them; a confirmed one is worth an upstream issue against lib.claims",
            evidence={"count": len(agenda.candidate_rules)},
        ))
    silent = sorted({d.code for d in bag.items if d.code == "UEL0503"})
    if silent:
        n = sum(1 for d in bag.items if d.code == "UEL0503")
        c.add(Finding(
            "DOCTOR-401", "kernel", "info",
            f"{n} structural claim(s) required but provided by nobody",
            "UEL0503 fires when a consumer requires a claim no upstream provides. A "
            "cluster of these on a real model usually means the shipped claim taxonomy "
            "is missing an entailment, which is a kernel-side gap, not a user error.",
            repro="uel check --json <project>",
            evidence={"count": n},
        ))


def _check_kernel_skew(lock: Lock, c: Checkup) -> None:
    pinned = {
        (e.run or {}).get("tools", {}).get("uel")
        for e in lock.nodes.values() if (e.run or {}).get("tools")
    }
    pinned.discard(None)
    if pinned and __version__ not in pinned:
        c.add(Finding(
            "DOCTOR-107", "user", "info",
            "results were computed by a different kernel version",
            f"Recorded runs used {sorted(pinned)}; this kernel is {__version__}. A different "
            "kernel is a different artifact, so everything is legitimately stale.",
            advice="`uel build` to recompute under this kernel",
            evidence={"pinned": sorted(pinned), "current": __version__},
        ))


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------


def run(path: str | Path) -> Checkup:
    """Never raises: a doctor that crashes on the patient is useless, and the
    crash itself is the most valuable kernel finding there is."""
    c = Checkup()
    root = Path(path).resolve()
    c.project_rel = root.name
    bag = Bag()

    try:
        project = load_project(root, bag)
        res = resolve_project(project, bag)
        # measured values are part of the current graph; resolving without them
        # would compute a different graph hash than every other command and
        # report honest projections as stale
        from .calibration import apply_overlays

        apply_overlays(res, "")
    except Exception:
        c.add(Finding(
            "DOCTOR-001", "kernel", "error",
            "the kernel raised while loading the project",
            "Loading or resolving a project raised an exception instead of producing a "
            "diagnostic. Every input, valid or not, must reach a diagnostic.",
            repro="uel check <project>",
            evidence={"traceback_tail": traceback.format_exc(limit=6).splitlines()[-1][:200]},
            sensitive={"traceback": traceback.format_exc(limit=12)},
        ))
        return c
    c.checked.append("load+resolve")

    try:
        from .checker import run_checks
        run_checks(res, bag, lock=False)
        c.checked.append("compile-time pipeline")
    except Exception:
        c.add(Finding(
            "DOCTOR-002", "kernel", "error",
            "the checker raised instead of diagnosing",
            "The compile-time pipeline raised an exception on a real model. Whatever the "
            "model does wrong, the answer is a diagnostic, never a traceback.",
            repro="uel check <project>",
            evidence={"traceback_tail": traceback.format_exc(limit=6).splitlines()[-1][:200]},
            sensitive={"traceback": traceback.format_exc(limit=12)},
        ))
        return c

    lock = Lock.load(project.lock_path)
    for name, fn in (
        ("projection integrity", lambda: _check_projections(root, res, lock, c)),
        ("lock integrity", lambda: _check_lock_integrity(res, lock, c)),
        ("staleness honesty", lambda: _check_staleness_honesty(res, lock, c)),
        ("diagnostic quality", lambda: _check_diagnostic_quality(bag, c)),
        ("formatter idempotence", lambda: _check_formatter_idempotence(project, c)),
        ("canonical round-trip", lambda: _check_roundtrip(res, c)),
        ("epistemic debt", lambda: _check_epistemic_debt(res, lock, bag, c)),
        ("kernel skew", lambda: _check_kernel_skew(lock, c)),
    ):
        try:
            fn()
            c.checked.append(name)
        except Exception:
            c.add(Finding(
                "DOCTOR-003", "kernel", "error",
                f"a doctor check raised: {name}",
                "The checkup itself failed, which is a kernel defect of its own.",
                repro="uel doctor <project>",
                evidence={"check": name,
                          "traceback_tail": traceback.format_exc(limit=6).splitlines()[-1][:200]},
                sensitive={"traceback": traceback.format_exc(limit=12)},
            ))
    return c


# ---------------------------------------------------------------------------
# The upstream issue (program §7.1: a typed claim with provenance)
# ---------------------------------------------------------------------------


def issue_title(findings: list[Finding]) -> str:
    head = findings[0]
    extra = f" (+{len(findings) - 1} more)" if len(findings) > 1 else ""
    return f"[doctor] {head.title}{extra}"


def issue_body(c: Checkup, findings: list[Finding], full: bool = False) -> str:
    env = environment()
    fps = ",".join(sorted(f.fingerprint() for f in findings))
    L = [
        "*Filed by `uel doctor` from a downstream project. This is a typed claim with "
        "provenance, not a bug report written from memory: every item below was observed "
        "on a real model by the kernel checking itself.*",
        "",
        "## What happened",
        "",
    ]
    for f in findings:
        L.append(f"### `{f.code}` — {f.title}")
        L.append("")
        L.append(f.detail)
        L.append("")
        if f.repro:
            L.append(f"- repro: `{f.repro}`")
        if f.evidence:
            L.append(f"- evidence: `{json.dumps(f.evidence, sort_keys=True)}`")
        if f.sensitive and not full:
            L.append(f"- withheld (project data): {', '.join(sorted(f.sensitive))} — "
                     f"re-run with `--full-evidence` to include, if your model is not confidential")
        elif f.sensitive:
            L.append(f"- detail: `{json.dumps(f.sensitive, sort_keys=True)[:1500]}`")
        L.append(f"- fingerprint: `{f.fingerprint()}`")
        L.append("")
    L += [
        "## Environment",
        "",
        f"- uel `{env['uel']}` · python `{env['python']}` · {env['platform']}",
        f"- checks run: {', '.join(c.checked)}",
        "",
        "## Impact",
        "",
        "Reported by a downstream project; severity is the reporter's, not triage's. "
        "Kernel-class findings are, by construction, cases where UEL failed its own "
        "promises rather than cases where a model was wrong.",
        "",
        "---",
        f"<!-- uel-doctor fingerprints: {fps} -->",
        "_Filed by `uel doctor`; deduped by fingerprint._",
    ]
    return "\n".join(L)


def _gh() -> str | None:
    return shutil.which("gh")


def find_existing_issue(upstream: str, fingerprints: list[str]) -> int | None:
    """A defect filed twice is noise. Search closed issues too: a re-appearing
    fingerprint on a closed issue is a regression report, not a new bug."""
    gh = _gh()
    if not gh or not fingerprints:
        return None
    try:
        r = subprocess.run(
            [gh, "issue", "list", "--repo", upstream, "--state", "all", "--limit", "50",
             "--search", fingerprints[0], "--json", "number"],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            return None
        rows = json.loads(r.stdout or "[]")
        return int(rows[0]["number"]) if rows else None
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError, KeyError):
        return None


def file_issue(upstream: str, title: str, body: str) -> tuple[bool, str]:
    """Create the issue with `gh` if it is available and authenticated.

    Returns (created, message). Never raises and never fails a build: when `gh`
    is absent the caller prints the body instead, and an agent with GitHub tools
    of its own files it from the JSON. That fallback is the normal path, not a
    degraded one — most sessions that run the doctor can file better than a
    subprocess can.
    """
    gh = _gh()
    if not gh:
        return False, "gh CLI not found"
    try:
        r = subprocess.run(
            [gh, "issue", "create", "--repo", upstream, "--title", title, "--body-file", "-"],
            input=body, capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"gh failed: {e}"
    if r.returncode != 0:
        return False, (r.stderr or "gh returned non-zero").strip().splitlines()[-1][:300]
    return True, (r.stdout or "").strip()


def upstream_for(path: Path) -> str:
    """`[doctor] upstream = "owner/repo"` in uel.toml, else the reference kernel."""
    manifest = Path(path) / "uel.toml"
    if manifest.is_file():
        try:
            import tomllib

            data = tomllib.loads(manifest.read_text(encoding="utf-8"))
            d = data.get("doctor", {})
            if isinstance(d, dict) and isinstance(d.get("upstream"), str):
                return d["upstream"]
        except Exception:
            pass
    return os.environ.get("UEL_UPSTREAM") or UPSTREAM_DEFAULT


def render(c: Checkup) -> str:
    if not c.findings:
        return (f"doctor: clean ({len(c.checked)} checks) — projections intact and current, "
                f"lock honest, nothing owed")
    L = []
    kernel, user = c.kernel(), c.user()
    for f in c.sorted():
        mark = {"error": "✗", "warning": "!", "info": "·"}.get(f.severity, "·")
        tag = "KERNEL" if f.audience == "kernel" else "yours"
        L.append(f"  {mark} [{tag}] {f.code}  {f.title}")
        for line in _wrap(f.detail, 76):
            L.append(f"        {line}")
        if f.advice:
            for line in _wrap(f"→ {f.advice}", 76):
                L.append(f"        {line}")
    L.append("")
    L.append(f"doctor: {len(user)} finding(s) for you, {len(kernel)} for the kernel "
             f"({len(c.checked)} checks run)")
    if kernel:
        L.append("        the kernel-class findings are evidence UEL failed its own promises;")
        L.append("        `uel doctor --issue` writes them up, `--file-issue` files them upstream")
    return "\n".join(L)


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines
