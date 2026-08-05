# The user-org loop — one iteration, continuously

*Stage 3 of the bootstrap plan (program §9), made operational. This runbook is
the standing protocol for the **hardware org's** working sessions: an agent
wakes on a schedule or an event, runs one iteration against the vehicle model,
and goes away. It is one instance of the parameterized protocol
([`loop-template.md`](loop-template.md)) — the extra boundary rules below are
this instance's, because here the user org lives inside the tool's own
repository; an adopter scaffolded by `uel init` owns their whole repo and gets
the same loop without the wall. Knowledge survives in the graph, the lock, the
overlays, and the issue channel — never in the session. The runbook exists so
that every session, with no shared context, runs the same loop.*

## Who runs this

An autonomous agent session, woken by a scheduled Routine (daily) or by an
event (a push, a landed measurement). The session is the **user org** (program
§1.2): it flies the vehicle programs and uses UEL as a tool. Its boundary
duties are absolute:

- **Never modify `uel/` internals, the conformance suite, or the constitution**
  (program §1.2: users never touch UEL internals). Kernel gripes go to the
  issue channel, not into the kernel.
- Work only under `examples/` (the vehicle models, analyses, geometry, test
  data) and this runbook's own log.
- Push only to `claude/user-org-*` branches. Open no pull requests; the
  session's deliverable is the branch plus filed issues. A human (or the
  software org's integrator) merges.

## The iteration

1. **Sync.** Fetch the repository's default branch. If the economics
   scheduler is not yet merged there, fetch and check out the newest
   `claude/`-prefixed branch that contains `uel/attention.py`.
2. **Read the agenda.** `python3 -m uel agenda examples/apache-one --json`.
   The agenda's section order is the standing work policy:
   1. compile errors — nothing outranks a red check;
   2. stale work, in attention order (`»` marks the buildable frontier);
   3. pending judgments — epistemic debt: run `uel build`, read outputs,
      write the judgment with residual doubts;
   4. open discrepancies, unreviewed investigation stubs, unreviewed
      entailment candidates — complete stubs into real investigation
      analyses; review candidates and file an issue recommending a
      `lib.claims` amendment where one is warranted;
   5. the top `info-value` measurement — draft or refine the test-campaign
      JSON that would capture it (`examples/apache-one/test/`), with
      instrumentation notes in the measurement `source`;
   6. tightest budget — if margin erosion is new, investigate which leaf
      moved and whether a design change is warranted.
3. **Do the top item. One item done beats five touched.** Real work only:
   re-run stale cores and judge results; refine a framing whose fence is hot;
   propose a design change as an edited model with a clean `uel check`.
4. **Gate.** `python3 -m uel check examples/apache-one` must be clean (or
   strictly cleaner than before) and `python3 -m uel build` run to freshness
   before pushing. Never commit a red graph.
5. **Record.** Commit to `claude/user-org-<UTC date>` with a message stating
   the agenda item taken and the judgment reached. Append one line to
   `docs/org/loop-log.md`: date, item, outcome, wall-clock minutes — this is
   the north-star denominator data (program §5.2: cost per merged claim).
6. **File.** Anything that blocked, surprised, or cost the session goes to
   the GitHub issue channel as a typed claim with provenance (program §7.1):
   what happened, which command, repro, cost. Software-org triage is not this
   session's job. A kernel bug is an issue, never a local patch.

## Kill switch

The loop is a scheduled Routine owned by the program principal. Disable or
delete it in claude.ai → Routines (or ask any session to
`delete_trigger` it). The runbook stays; the schedule is the only moving
part. Compute budget authority is the principal's (program §2.3); the
Routine's cadence is the budget.

## The point

Program §6.1's kill criterion — two consecutive iterations with no
improvement — is only evaluable if iterations *happen* and are *measured*.
This loop makes both true: the agenda decides where attention goes, the
loop-log records what it cost, and the leverage claim gets graded by data
instead of asserted (spec §1.2).
