# ADR-0007 — `uel doctor`: self-authenticating reports, and the issue the kernel files against itself

*Status: accepted · 2026-08-05 · serves program §7.1 (the org-to-org channel) and risks R4/R5/R6*

## Intent

Two problems, one instrument.

**Reports drift.** Spec §1.4 prohibits hand-editing a compiled projection "by
construction," but construction consisted of a header saying *do not
hand-edit*, which has never stopped anyone. A traveler with a number fixed on
the floor is the drift failure mode in its purest form: the document disagrees
with the model, and nothing downstream knows.

**Defects don't travel upstream.** Program §7.1 makes the issue channel the
only thing crossing the org boundary, and program §2.2 grades the kernel by
what users file. But a user who hits a kernel defect mid-design has every
incentive to route around it and no incentive to write the bug report — so the
maintainers never see the evidence, and R4/R5/R6 stay theoretical. The kernel
is in a better position to notice its own failures than the person they are
happening to.

## Framing

- Model: one checkup pass, findings classified by **audience** — `user`
  (your drift and debt) versus `kernel` (UEL broke a promise it makes in its
  own spec). Only kernel-class findings become issues.
- Boundary: the doctor observes and writes; it never repairs, never commits,
  and never files without an explicit flag. CI may run it; CI may not file.
- `assume public_upstream because "the reference kernel's tracker is public,
  so a proprietary model must not leak into it because a tool was helpful"` —
  hence redaction by default and `--full-evidence` as a deliberate act.

## Knowns

**Self-authenticating projections.** Every compiled artifact now ends with a
digest of its own body (`uel/projections.py: seal/verify_seal`, applied on
write). That single addition separates two diseases that used to look alike:

| | what it means | verdict |
|---|---|---|
| `DOCTOR-102` **doctored** | body no longer matches its own digest — edited after compilation, still claiming its graph hash | error |
| `DOCTOR-103` **stale** | intact, but compiled from an older graph | warning |

The distinction is exact and needs no re-render, which matters because a
re-render legitimately differs whenever the lock's outputs have moved. This is
integrity, not security: anyone can recompute a digest over edited text. It
catches the failure that actually happens, not an adversary.

**Kernel-class checks** — the kernel grading itself on data the maintainers do
not have: the checker raising instead of diagnosing (`DOCTOR-002`); recorded
output hashes that do not recompute from their recorded values (`DOCTOR-201`);
**staleness under-invalidation** measured by seeded in-memory perturbation of
the user's own graph against an independently computed reachability cone
(`DOCTOR-204`, program §5.2's staleness-honesty indicator, made a command);
formatter non-idempotence or meaning loss (`DOCTOR-303/304/305`); canonical
round-trip failure (`DOCTOR-306/307/308`); errors shipped without the reason
the spec promises (`DOCTOR-302`); required-but-unprovided structural claims
clustering, which usually means the shipped taxonomy is missing an entailment
(`DOCTOR-401`).

**The issue.** `--issue` writes a typed claim with provenance (program §7.1):
what happened, a repro, structural evidence, environment, and a **fingerprint**
over `(code, evidence)` only — deliberately excluding paths, versions, and
timestamps, so the same defect hitting two different users collides into one
issue rather than multiplying. `--file-issue` creates it through `gh`,
searching open *and* closed issues for the fingerprint first (a fingerprint on
a closed issue is a regression report, not a new bug).

**Filing is LLM-native by design.** `--json` carries `issue.title`,
`issue.body`, and `issue.fingerprints`, and the shipped `uel-doctor` skill
tells the agent to file with its own GitHub tools, treating `gh` as the
fallback. This is not a limitation dressed up as a virtue: an agent can search
the tracker, judge whether an existing issue is the same defect, comment "we
hit this too" with its environment, and notice a regression. A subprocess can
only create.

## Derivation

`uel/doctor.py`; `seal`/`verify_seal` in `uel/projections.py` with sealing at
write; `uel doctor [path] [--json|--issue|--file-issue] [--upstream]
[--full-evidence] [--strict]`; `[doctor] upstream` in `uel.toml`; the
`uel-doctor` skill and a `--strict` doctor step added to the scaffolded CI
(ADR-0006). 21 tests.

Dogfooding paid twice. The first doctor resolved projects **without applying
calibration overlays**, so it computed a different graph hash than every other
command and reported every honest projection on the vertical slice as stale —
a false-positive engine, caught by running it on real data before shipping.
And the first `DOCTOR-201/202` were **tautological**: `compute()` sets a node
stale exactly when its recipe differs, so "fresh with a mismatched recipe"
could never fire. Both were replaced with checks that can actually fail —
output-hash recomputation and seeded-perturbation staleness honesty.

## Judgment

Accepted. Doubts, honestly held: (1) the seal proves *edited*, not *who* or
*why* — it is a smoke alarm, and the skill deliberately tells the agent not to
regenerate the evidence away before understanding what the edit was trying to
say; (2) the staleness probe samples at most eight quantities and perturbs by a
fixed +1000 SI, so it demonstrates dishonesty rather than proving honesty —
absence of `DOCTOR-204` is weak evidence, and the doctor should not be read as
a proof of correctness; (3) redaction is a judgment about *categories* of
field, and a determined leak could still ride in a diagnostic message the
kernel composed — the withheld list is checked by tests, but a new finding type
with careless evidence could regress it; (4) auto-filing from many downstream
projects could bury a small maintainer under fingerprint-deduped-but-still-
numerous issues, which is a problem worth having only once adopters exist.
