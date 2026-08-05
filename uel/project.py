"""Project loading: uel.toml, model files, project libraries, and the stdlib.

A project is a directory with an optional `uel.toml`:

    [project]
    name = "apache-one"
    edition = "2026"
    model = ["model", "analysis"]     # dirs (or files) with .uel sources; default: root, recursive

    [tolerances]                      # hash-quantization per dimension name (spec §4.3)
    mass = "0.1 g"
    length = "0.01 mm"
    force = "1 N"
    default_rel = 1e-6                # relative grid for dimensions not listed

    [tools]
    python = "3"                      # informational; the lock records exact versions

Namespaces: model files land in the project namespace (requirements under `req.`);
files under lib/ land under `lib.<stem>.`; the kernel's stdlib (uel/stdlib/*.uel)
loads first under the same rule. Projects may add lib names but not redefine them.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .diagnostics import Bag, Span
from .units import UnitError, parse_unit

STDLIB_DIR = Path(__file__).resolve().parent / "stdlib"

@dataclass
class TolerancePolicy:
    """Quantization grid for hashing (spec §4.3 draft rule).

    Each `[tolerances]` entry is a labeled quantity like `mass = "0.1 g"`; the
    entry's *own unit* determines which dimension it grids (so `Ixx = "0.001 mm^4"`
    just works). A level-unit entry (`margin = "0.001 dB"`) grids level quantities
    of that referenced dimension, on the dB scale. Quantities whose type has no
    absolute grid quantize to `default_rel` significant precision.
    """

    abs_tol: dict[tuple, float] = field(default_factory=dict)  # Dim -> grid in SI units
    level_tol: dict[tuple, float] = field(default_factory=dict)  # Dim -> grid in dB
    labels: dict[str, str] = field(default_factory=dict)  # label -> original text (docs)
    default_rel: float = 1e-6

    @classmethod
    def from_toml(cls, d: dict, bag: Bag, file: str) -> "TolerancePolicy":
        pol = cls()
        for k, v in d.items():
            if k == "default_rel":
                if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
                    bag.error("UEL0705", f"default_rel must be a positive number, got {v!r}", Span(file))
                else:
                    pol.default_rel = float(v)
                continue
            if not isinstance(v, str):
                bag.error("UEL0705", f"tolerance for '{k}' must be a string like \"0.1 g\"", Span(file))
                continue
            partsv = v.strip().split(None, 1)
            try:
                mag = float(partsv[0])
                unit = parse_unit(partsv[1] if len(partsv) > 1 else "")
            except (ValueError, IndexError):
                bag.error("UEL0705", f"cannot parse tolerance '{v}' for '{k}'", Span(file))
                continue
            except UnitError as e:
                bag.error("UEL0301", f"tolerance for '{k}': {e}", Span(file))
                continue
            if mag <= 0:
                bag.error("UEL0705", f"tolerance for '{k}' must be positive, got {mag}", Span(file))
                continue
            grid = mag * unit.factor  # affine/level offset irrelevant for a grid spacing
            table = pol.level_tol if unit.level else pol.abs_tol
            if unit.dim in table and table[unit.dim] != grid:
                bag.error("UEL0705",
                          f"tolerance '{k}' conflicts with an earlier entry for the same dimension",
                          Span(file))
                continue
            table[unit.dim] = grid
            pol.labels[k] = v
        return pol

@dataclass
class SourceFile:
    path: Path  # absolute
    rel: str  # project-relative display path
    namespace: str  # "" for model files, "lib.<stem>" for libraries, "stdlib:lib.<stem>"
    text: str

@dataclass
class Project:
    root: Path
    name: str = "unnamed"
    edition: str = "2026"
    tolerances: TolerancePolicy = field(default_factory=TolerancePolicy)
    files: list[SourceFile] = field(default_factory=list)  # stdlib first, then project
    manifest_path: Path | None = None

    @property
    def lock_path(self) -> Path:
        return self.root / "uel.lock"

    def sources_map(self) -> dict[str, str]:
        return {f.rel: f.text for f in self.files}

def _read(p: Path, bag: Bag, rel: str) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError as e:
        bag.error("UEL0002", f"cannot read {rel}: {e.strerror or e}", Span(rel))
        return ""

def find_root(start: Path) -> Path:
    """Walk upward from `start` looking for uel.toml; fall back to `start` itself."""
    start = start.resolve()
    if start.is_file():
        start = start.parent
    for cand in [start, *start.parents]:
        if (cand / "uel.toml").is_file(): return cand
    return start

def load_project(path: str | Path, bag: Bag, include_stdlib: bool = True) -> Project:
    root = find_root(Path(path))
    proj = Project(root=root)

    manifest = root / "uel.toml"
    model_specs: list[str] = []
    if manifest.is_file():
        proj.manifest_path = manifest
        try:
            data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError) as e:
            bag.error("UEL0001", f"uel.toml: {e}", Span("uel.toml"))
            data = {}
        p = data.get("project", {})
        if isinstance(p, dict):
            proj.name = str(p.get("name", proj.name))
            proj.edition = str(p.get("edition", proj.edition))
            m = p.get("model", [])
            if isinstance(m, list):
                model_specs = [str(x) for x in m]
        t = data.get("tolerances", {})
        if isinstance(t, dict):
            proj.tolerances = TolerancePolicy.from_toml(t, bag, "uel.toml")

    # stdlib first: the shipped libraries (spec §5.3)
    if include_stdlib and STDLIB_DIR.is_dir():
        for p in sorted(STDLIB_DIR.glob("*.uel")):
            ns = f"lib.{p.stem}"
            proj.files.append(SourceFile(p, f"<stdlib>/{p.name}", f"stdlib:{ns}", _read(p, bag, p.name)))

    # project libraries
    libdir = root / "lib"
    if libdir.is_dir():
        for p in sorted(libdir.rglob("*.uel")):
            rel = str(p.relative_to(root))
            proj.files.append(SourceFile(p, rel, f"lib.{p.stem}", _read(p, bag, rel)))

    # model files
    seen: set[Path] = set()

    def add_model(p: Path) -> None:
        if p in seen or not p.is_file(): return
        seen.add(p)
        rel = str(p.relative_to(root)) if p.is_relative_to(root) else str(p)
        proj.files.append(SourceFile(p, rel, "", _read(p, bag, rel)))

    if model_specs:
        for spec in model_specs:
            sp = root / spec
            if sp.is_dir():
                for p in sorted(sp.rglob("*.uel")):
                    add_model(p)
            elif sp.is_file():
                add_model(sp)
            else:
                bag.error("UEL0001", f"model path '{spec}' from uel.toml does not exist", Span("uel.toml"))
    else:
        for p in sorted(root.rglob("*.uel")):
            if libdir in p.parents or any(part.startswith(".") for part in p.relative_to(root).parts):
                continue
            add_model(p)

    if not any(f.namespace == "" for f in proj.files):
        bag.error("UEL0001", f"no .uel model files found under {root}", Span(str(root)))
    return proj
