"""The machine-facing door (docs/stability.md).

`uel/cli.py` is one engine with several doors; this module is the door built for
callers that are not human — harness hooks, CI gates, MCP wrappers. Two things
live here, and both exist because of the same observation: an agent reading this
tool's output cannot ask a follow-up question. Whatever the envelope says is
what it acts on.

**The envelope.** One JSON object on stdout, carrying a protocol version, so a
caller that understands protocol N refuses protocol N+1 loudly instead of
guessing. Everything a human might want — progress, chatter — goes to stderr,
so stdout can be piped into a parser unconditionally.

**The exit codes**, and specifically the split between 1 and 3:

    1  the model was rejected     the tool ran fine; the graph is wrong
    3  the tool could not run     nothing was judged; the environment is wrong

Those are opposite instructions. A caller that cannot tell them apart either
thrashes on a healthy model (rewriting physics to satisfy an unreadable lock
file) or silently ignores a genuine rejection. Conflating them is the single
most consequential thing a compiler can get wrong when its user is a machine,
and it is the reason this module exists rather than a bare `--json` flag.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, Optional

from . import __version__
from .diagnostics import Bag

PROTOCOL = 1

EXIT_OK = 0
EXIT_REJECTED = 1
EXIT_USAGE = 2
EXIT_UNAVAILABLE = 3

# Codes that mean "the tool could not run", not "the graph is wrong". They are
# the 00xx family: a missing manifest, an unreadable source, a corrupt lock, an
# internal defect. Nothing about them is a judgment on the engineering.
ENVIRONMENT_CODES = ("UEL0001", "UEL0002", "UEL0003", "UEL0004")

def exit_for(bag) -> int:
    """Map a diagnostic bag onto the contract's exit codes.

    The rule is deliberately conservative: a run is only *unavailable* when
    every error in it is an environment failure. One genuine finding alongside a
    missing file still means the graph was judged and found wrong, and a caller
    that stops reading diagnostics because it saw a 3 would miss it.
    """
    errs = bag.errors
    if not errs:
        return EXIT_OK
    if all(d.code in ENVIRONMENT_CODES for d in errs):
        return EXIT_UNAVAILABLE
    return EXIT_REJECTED

class ToolUnavailable(Exception):
    """The tool could not run: unreadable project, corrupt lock, missing core.

    Raised — never returned — so it cannot be mistaken for a verdict on the
    graph as it passes back up through a command. Carries an optional
    diagnostic code so the failure still lands in the envelope as a proper
    diagnostic rather than a bare string.
    """

    def __init__(self, message: str, code: str = "UEL0002") -> None:
        super().__init__(message)
        self.code = code

def envelope(command: str, bag: Optional[Bag] = None, result: Any = None,
             ok: Optional[bool] = None) -> dict:
    """Build the versioned envelope. `ok` defaults to "no error diagnostics"."""
    bag = bag if bag is not None else Bag()
    return {
        "uel": {
            "protocol": PROTOCOL,
            "kernel": __version__,
            "edition": "2026",
            "command": command,
            "ok": bag.ok() if ok is None else bool(ok),
        },
        "diagnostics": [d.to_obj() for d in bag.sorted()],
        "result": result if result is not None else {},
    }

def emit(command: str, bag: Optional[Bag] = None, result: Any = None,
         ok: Optional[bool] = None, stream=None) -> None:
    """Write exactly one envelope object to stdout."""
    json.dump(envelope(command, bag, result, ok), stream or sys.stdout,
              indent=2, ensure_ascii=False)
    (stream or sys.stdout).write("\n")

def guard(command: str, json_mode: bool, fn: Callable[[], int]) -> int:
    """Run a command body, mapping "could not run" onto exit 3.

    Unexpected exceptions are deliberately caught. An unhandled traceback tells
    a machine caller nothing it can act on, and — worse — a shell reads a crash
    as exit 1, which under this contract means *the model was rejected*. A
    kernel bug would masquerade as an engineering verdict. Anything that is not
    a judgment about the graph is a 3.
    """
    try:
        return fn()
    except ToolUnavailable as e:
        bag = Bag()
        bag.error(e.code, str(e),
                  reason="the tool could not run; this is not a judgment about the "
                         "graph (docs/stability.md, exit code 3) — fix the environment, "
                         "not the model")
        if json_mode:
            emit(command, bag, ok=False)
        else:
            print(f"error [{e.code}] {e}", file=sys.stderr)
        return EXIT_UNAVAILABLE
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_UNAVAILABLE
    except Exception as e:  # noqa: BLE001 — see docstring; a crash must not read as a verdict
        import traceback

        bag = Bag()
        bag.error("UEL0004", f"internal error in '{command}': {type(e).__name__}: {e}",
                  reason="this is a kernel defect, not a finding about the model; "
                         "please report it with the traceback on stderr")
        if json_mode:
            emit(command, bag, ok=False)
        else:
            print(f"error [UEL0004] internal error in '{command}': "
                  f"{type(e).__name__}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return EXIT_UNAVAILABLE
