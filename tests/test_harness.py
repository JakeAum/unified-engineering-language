"""The adapter layer is generated, not authored — and this file is what makes
that claim testable (ADR-0010).

Three obligations, in order of how much they matter:

1. **No authorship.** A template may not contain a sentence about UEL. The
   mechanical form of that rule: no live subcommand name, no diagnostic code, no
   project filename may appear as a literal in any template — they arrive only
   through `{{TOKEN}}` substitution from live kernel tables.
2. **No drift.** This repository installs its own adapter; CI fails if the
   installed copy differs from what the generator currently emits. That is what
   makes an adapter safe to regenerate and cheap to throw away — extending the
   v0.5 skill-drift test to the whole harness.
3. **No assumptions about neighbouring work.** The emitted brief names commands
   that may not exist in the kernel it runs against, and must degrade to one
   that does.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from uel import __version__, harness
from uel.agentdoc import FAMILIES, SKILL_REL
from uel.diagnostics import CODES

REPO = Path(__file__).resolve().parent.parent
SH = shutil.which("sh") or "/bin/sh"  # absolute: these tests hollow out PATH on purpose


def _templates() -> list[Path]:
    return sorted(p for p in harness.ADAPTERS.rglob("*") if p.is_file() and p.name != "adapter.json")


class GenerationNotAuthorship(unittest.TestCase):
    """The rule the whole design rests on, enforced mechanically."""

    def test_no_template_names_a_subcommand(self):
        # If you type `uel check` into a template you have hand-written a claim
        # about the kernel, and it will rot. Use a token.
        tool = harness.tool()
        for path in _templates():
            text = path.read_text(encoding="utf-8")
            for name in harness.commands():
                self.assertNotIn(f"{tool} {name}", text,
                                 f"{path.name} hardcodes `{tool} {name}` — substitute it instead")

    def test_no_template_names_a_diagnostic_code(self):
        bands = {code[:5] for code in CODES}
        for path in _templates():
            text = path.read_text(encoding="utf-8")
            for band in bands:
                self.assertNotIn(band, text, f"{path.name} hardcodes diagnostic band {band}")

    def test_no_template_names_a_project_file(self):
        from uel.project import LOCK, MANIFEST

        for path in _templates():
            text = path.read_text(encoding="utf-8")
            for literal in (MANIFEST, LOCK):
                self.assertNotIn(literal, text, f"{path.name} hardcodes {literal}")

    def test_every_token_resolves(self):
        for target in harness.TARGETS.values():
            for art in target.artifacts():
                self.assertNotIn("{{", art.text, f"{target.name}/{art.rel} has an unsubstituted token")

    def test_every_token_is_load_bearing(self):
        """A token no adapter uses is dead weight (ADR-0008's rule, on ourselves)."""
        blob = "".join(p.read_text(encoding="utf-8") for p in _templates())
        for key in harness.tokens():
            self.assertIn("{{" + key + "}}", blob, f"token {key} is generated but unused")

    def test_emitted_text_carries_the_live_tables(self):
        subs = harness.tokens()
        agents = next(a for a in harness.TARGETS["agents-md"].artifacts() if a.rel == "AGENTS.md")
        self.assertIn(__version__, agents.text)
        self.assertIn(f"{len(CODES)} stable codes", agents.text)
        for name in harness.commands():  # includes `harness` itself: added to the CLI, present for free
            self.assertIn(f"`{harness.tool()} {name}`", agents.text)
        for band, label, _ in harness.code_families():
            self.assertIn(band, agents.text)
            self.assertIn(label, agents.text)
        self.assertIn(subs["BRIEFING"], agents.text, "the tool's own briefing is quoted verbatim")

    def test_every_code_band_is_labelled(self):
        """Minting a code in a new band without labelling it breaks generation."""
        labelled = {band for band, _ in FAMILIES}
        for band, label, _ in harness.code_families():
            self.assertIn(band, labelled, f"{band} has no entry in agentdoc.FAMILIES")
            self.assertNotEqual(label, "(unlabelled band)")

    def test_loop_and_ladder_are_grounded_in_the_live_table(self):
        cmds = harness.commands()
        for name, _ in harness.LOOP:
            if name is not None:
                self.assertIn(name, cmds, "the loop names a command this kernel does not expose")
        self.assertIn(harness.BRIEF_FLOOR[0], cmds, "the brief's floor rung must always exist")
        self.assertEqual(harness.BRIEF_LADDER[-1], harness.BRIEF_FLOOR,
                         "the last rung of the ladder must be the guaranteed floor")


class RepoAdapterDoesNotDrift(unittest.TestCase):
    """Obligation 2: this repository eats its own adapter."""

    def test_installed_claude_code_artifacts_match_the_generator(self):
        drift = harness.check("claude-code", REPO)
        self.assertEqual(drift, [],
                         "harness drift: re-run `uel harness install --target claude-code "
                         "--dir . --force` at the repo root and commit the result")

    def test_hooks_are_executable(self):
        for rel in (".claude/hooks/uel-check.py", ".claude/hooks/uel-agenda.sh"):
            self.assertTrue(os.access(REPO / rel, os.X_OK), f"{rel} is not executable")

    def test_emitted_check_hook_is_valid_python(self):
        path = REPO / ".claude/hooks/uel-check.py"
        compile(path.read_text(encoding="utf-8"), str(path), "exec")

    def test_emitted_agenda_hook_is_valid_shell(self):
        r = subprocess.run([SH, "-n", str(REPO / ".claude/hooks/uel-agenda.sh")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    # Raised from 200 when protocol tolerance landed (docs/stability.md): an
    # adapter outlives the kernel that generated it, so reading either JSON shape
    # is load-bearing rather than optional, and it costs ~20 lines. The budget
    # exists to keep adapters throw-away-able, not to keep them wrong — but it is
    # moved deliberately and in the open, never silently to fit a change.
    ADAPTER_LINE_BUDGET = 240

    def test_adapters_stay_small_and_disposable(self):
        for name, target in harness.TARGETS.items():
            lines = sum(len((target.dir / p.name).read_text(encoding="utf-8").splitlines())
                        for p in sorted(target.dir.iterdir()))
            self.assertLess(lines, self.ADAPTER_LINE_BUDGET,
                            f"adapter '{name}' is {lines} lines — too big to throw away")


class SettingsMergeNeverClobbers(unittest.TestCase):
    """Users have their own config. Destroying it is unacceptable."""

    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)
        self.settings = self.td / ".claude" / "settings.json"

    def _seed(self, obj):
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        self.settings.write_text(json.dumps(obj), encoding="utf-8")

    def test_foreign_keys_hooks_and_matchers_survive(self):
        self._seed({"permissions": {"allow": ["Bash(npm test:*)"]},
                    "hooks": {"PostToolUse": [{"matcher": "Edit",
                                               "hooks": [{"type": "command", "command": "./mine.sh"}]}],
                              "Stop": [{"hooks": [{"type": "command", "command": "./notify.sh"}]}]}})
        harness.install("claude-code", self.td)
        after = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(after["permissions"], {"allow": ["Bash(npm test:*)"]})
        self.assertEqual(after["hooks"]["Stop"][0]["hooks"][0]["command"], "./notify.sh")
        post = after["hooks"]["PostToolUse"]
        self.assertEqual(post[0]["hooks"][0]["command"], "./mine.sh", "a foreign hook was displaced")
        self.assertTrue(any("uel-check.py" in h["command"] for g in post for h in g["hooks"]))
        self.assertTrue(any("uel-agenda.sh" in h["command"]
                            for g in after["hooks"]["SessionStart"] for h in g["hooks"]))

    def test_reinstall_is_a_no_op(self):
        harness.install("claude-code", self.td)
        first = self.settings.read_text(encoding="utf-8")
        harness.install("claude-code", self.td)
        self.assertEqual(self.settings.read_text(encoding="utf-8"), first)
        self.assertEqual(harness.check("claude-code", self.td), [])

    def test_unparseable_settings_are_left_untouched(self):
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        self.settings.write_text("{ not json", encoding="utf-8")
        rep = harness.install("claude-code", self.td)
        self.assertEqual(self.settings.read_text(encoding="utf-8"), "{ not json")
        self.assertTrue(any("unparseable" in k for k in rep.kept))

    def test_existing_artifacts_are_kept_without_force(self):
        harness.install("claude-code", self.td)
        hook = self.td / ".claude" / "hooks" / "uel-check.py"
        hook.write_text("# a human edited this\n", encoding="utf-8")
        harness.install("claude-code", self.td)
        self.assertEqual(hook.read_text(encoding="utf-8"), "# a human edited this\n")
        self.assertTrue(harness.check("claude-code", self.td), "drift must be reported")
        harness.install("claude-code", self.td, force=True)
        self.assertEqual(harness.check("claude-code", self.td), [])

    def test_agents_md_target_writes_only_agents_md(self):
        harness.install("agents-md", self.td)
        self.assertTrue((self.td / "AGENTS.md").is_file())
        self.assertFalse((self.td / ".claude").exists(), "the neutral target stays vendor-neutral")


class EmittedHooksBehave(unittest.TestCase):
    """The hooks are the product. Run them."""

    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)
        from uel.agentdoc import init_project

        init_project(self.td, "hooked")
        harness.install("claude-code", self.td)
        self.model = self.td / "model" / "design.uel"

    def _fire(self, path: Path):
        event = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(path)},
                            "cwd": str(self.td)})
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.td),
                   PYTHONPATH=os.pathsep.join([str(REPO), os.environ.get("PYTHONPATH", "")]))
        return subprocess.run([sys.executable, str(self.td / ".claude/hooks/uel-check.py")],
                              input=event, capture_output=True, text=True, env=env, timeout=300)

    def test_clean_edit_is_silent(self):
        r = self._fire(self.model)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr.strip(), "")

    def test_broken_edit_exits_2_with_structured_diagnostics(self):
        self.model.write_text(self.model.read_text(encoding="utf-8") +
                              '\nanalysis Broken {\n  knowns { a <- req.NOPE.x }\n'
                              '  core expr {\n    y = a\n  }\n  outputs {\n    y : W\n  }\n'
                              '  judgment pending\n}\n', encoding="utf-8")
        r = self._fire(self.model)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("UEL0202", r.stderr)  # the code an agent can act on
        self.assertIn("design.uel", r.stderr)

    def test_non_model_edit_is_ignored(self):
        other = self.td / "notes.md"
        other.write_text("hello\n", encoding="utf-8")
        r = self._fire(other)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr.strip(), "")

    def test_edit_outside_any_project_is_ignored(self):
        outside = Path(tempfile.mkdtemp()) / "loose.uel"
        self.addCleanup(shutil.rmtree, outside.parent, ignore_errors=True)
        outside.write_text("analysis X { judgment pending }\n", encoding="utf-8")
        self.assertEqual(self._fire(outside).returncode, 0)

    def test_hook_is_a_silent_no_op_without_a_kernel(self):
        """A repository must never be *broken* by its own tooling."""
        event = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(self.model)},
                            "cwd": str(self.td)})
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.td), PYTHONPATH="",
                   PATH=str(self.td))  # no `uel`, and the module is unimportable
        r = subprocess.run([sys.executable, str(self.td / ".claude/hooks/uel-check.py")],
                           input=event, capture_output=True, text=True, env=env, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr)


class HookReadsEitherJsonShape(unittest.TestCase):
    """An adapter outlives the kernel that generated it (docs/stability.md).

    `check --json` emits a bare diagnostics array today and will emit the
    versioned envelope once the machine surface is wired. A hook that assumes
    the array does not merely misread the envelope — it iterates the dict's
    *keys*, every `.get` raises, and the compile gate stops firing while
    reporting success. Silent loss of the gate is the worst available outcome,
    so both shapes are pinned here and an unknown protocol must be loud.
    """

    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)
        harness.install("claude-code", self.td, force=True)
        ns: dict = {}
        exec(compile((self.td / ".claude/hooks/uel-check.py").read_text(),
                     "uel-check.py", "exec"), ns)
        self.unwrap = ns["unwrap"]
        self.known = ns["KNOWN_PROTOCOLS"]

    def test_bare_array_is_read(self):
        diags = [{"code": "UEL0501", "severity": "error"}]
        self.assertEqual(self.unwrap(diags), diags)

    def test_envelope_is_read(self):
        diags = [{"code": "UEL0403", "severity": "error"}]
        env = {"uel": {"protocol": self.known[0], "ok": False}, "diagnostics": diags,
               "result": {}}
        self.assertEqual(self.unwrap(env), diags)

    def test_unknown_protocol_is_refused_not_guessed(self):
        env = {"uel": {"protocol": max(self.known) + 1}, "diagnostics": [{"severity": "error"}]}
        self.assertIsNone(self.unwrap(env),
                          "a future protocol must be refused loudly, never partially read")

    def test_garbage_is_refused(self):
        for junk in ("a string", 42, None, {"diagnostics": "not a list"}):
            self.assertIsNone(self.unwrap(junk), f"{junk!r} should not parse as diagnostics")

    def test_known_protocols_tracks_the_live_table(self):
        """The token is generated, not typed — so it cannot fall behind api.py."""
        from uel import api

        self.assertIn(api.PROTOCOL, self.known)

class BriefDegradesGracefully(unittest.TestCase):
    """Obligation 3: the brief names `stale --rank` and `doctor`, which concurrent
    kernel work may or may not have landed. It probes; it never assumes."""

    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)
        from uel.agentdoc import init_project

        init_project(self.td, "briefed")
        harness.install("claude-code", self.td)
        self.hook = self.td / ".claude" / "hooks" / "uel-agenda.sh"

    def _run(self, path_prefix: str = "") -> subprocess.CompletedProcess:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.td),
                   PYTHONPATH=os.pathsep.join([str(REPO), os.environ.get("PYTHONPATH", "")]))
        if path_prefix:
            env["PATH"] = os.pathsep.join([path_prefix, env["PATH"]])
        return subprocess.run([SH, str(self.hook)], capture_output=True, text=True,
                              env=env, timeout=300)

    def _fake_kernel(self, body: str) -> str:
        binroot = self.td / "fakebin"
        binroot.mkdir(exist_ok=True)
        shim = binroot / harness.tool()
        shim.write_text(body, encoding="utf-8")
        shim.chmod(0o755)
        return str(binroot)

    def test_ladder_names_the_ranked_brief(self):
        ladder, _ = harness.brief_ladder()
        self.assertIn("--rank", ladder, "the brief must ask for the ranked work queue")
        self.assertIn("--rank", self.hook.read_text(encoding="utf-8"))

    def test_falls_back_when_the_ranked_brief_does_not_exist(self):
        """An older kernel has no `--rank`; the agent still gets a work queue.

        Originally this asserted the *live* kernel lacked `--rank` and said so
        loudly if that changed. It has since changed — the economics scheduler
        landed — so the premise moves to a shim. The property under test is
        unchanged and is now the durable one: an adapter outlives the kernel
        that generated it, so it must degrade against a kernel *older* than
        itself, which no live-table assertion can ever exercise.
        """
        binroot = self._fake_kernel(
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            "  --version) echo 'uel 0.0.1'; exit 0 ;;\n"
            "  stale) [ \"$2\" = --help ] && { echo 'usage: stale [--json]'; exit 0; }\n"
            "         echo 'MISSING-RANK-PLAIN'; exit 0 ;;\n"
            "  *) exit 2 ;;\nesac\n")
        r = self._run(binroot)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("MISSING-RANK-PLAIN", r.stdout, "a work queue was printed anyway")
        self.assertNotIn("--rank", r.stdout, "an unsupported rung must not be invoked")

    def test_uses_the_ranked_brief_on_the_live_kernel(self):
        """The other side of the same coin, now that `--rank` really exists:
        the ladder's top rung is what actually runs."""
        self.assertTrue(harness.supports("stale", "--rank"))
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--rank", r.stdout, "the best available rung must be used")

    def test_uses_the_ranked_brief_when_the_kernel_has_it(self):
        binroot = self._fake_kernel(
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            "  --version) echo 'uel 9.9.9'; exit 0 ;;\n"
            "  stale) [ \"$2\" = --help ] && { echo 'usage: stale [--json] [--rank]'; exit 0; }\n"
            "         [ \"$2\" = --rank ] && { echo 'RANKED-OK'; exit 0; }\n"
            "         echo 'PLAIN'; exit 0 ;;\n"
            "  doctor) exit 0 ;;\n"
            "  *) exit 2 ;;\nesac\n")
        r = self._run(binroot)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("RANKED-OK", r.stdout)
        self.assertNotIn("PLAIN", r.stdout)

    def test_optional_commands_are_hidden_on_a_kernel_without_them(self):
        """`doctor` has since landed, so absence is exercised with a shim —
        again the durable direction: an adapter must not advertise a command
        the kernel in front of it does not have."""
        binroot = self._fake_kernel(
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            "  --version) echo 'uel 0.0.1'; exit 0 ;;\n"
            "  stale) [ \"$2\" = --help ] && { echo 'usage: stale'; exit 0; }; echo 'PLAIN'; exit 0 ;;\n"
            "  *) exit 2 ;;\nesac\n")
        self.assertNotIn("doctor", self._run(binroot).stdout)

    def test_surfaces_optional_commands_only_when_present(self):
        self.assertIn("doctor", self._run().stdout,
                      "doctor is in this kernel; the brief should point at it")
        binroot = self._fake_kernel(
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            "  --version) echo 'uel 9.9.9'; exit 0 ;;\n"
            "  stale) [ \"$2\" = --help ] && { echo 'usage: stale'; exit 0; }; echo 'PLAIN'; exit 0 ;;\n"
            "  doctor) exit 0 ;;\n"
            "  *) exit 2 ;;\nesac\n")
        self.assertIn("doctor", self._run(binroot).stdout)

    def test_brief_is_silent_without_a_kernel(self):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.td), PYTHONPATH="", PATH=str(self.td))
        r = subprocess.run([SH, str(self.hook)], capture_output=True, text=True, env=env, timeout=300)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")


class SkillIsReusedNotDuplicated(unittest.TestCase):
    def test_claude_code_target_installs_the_packaged_skill(self):
        td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        harness.install("claude-code", td)
        self.assertTrue((td / SKILL_REL / "SKILL.md").is_file())
        self.assertEqual(harness.check_skill(td), [])


if __name__ == "__main__":
    unittest.main()
