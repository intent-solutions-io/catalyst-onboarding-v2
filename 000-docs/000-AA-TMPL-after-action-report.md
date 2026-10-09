**000-AA-TMPL — After-action report template (snapshot)**

> Snapshot of `/doc-filing` references `000-AA-TMPL` **v1.0.0**; the skill copy is canonical (filing
> standard v4.5 §3.2). Refresh this file when the canonical version changes. When an AAR is due and
> which lane applies: `009` section 10.

<!-- ── cut here ─────────────────────────────────────────────────────────────────────────── -->

# NNN-AA-AACR — <epic or milestone name> after-action report

> <Plain-English opening: what this was and why it mattered, for a reader who has never seen
> this project. Expand shorthand on first use.>

- **Lane:** full | lightweight
- **Epic or milestone:** <plain-English title> (bead: <id>)
- **Acceptance test:** <the one-line measurable test the epic was given>
- **GitHub:** <umbrella issue and closing PR(s)>
- **Period:** <start date> → <close date>
- **Author:** <who>
- **Template:** 000-AA-TMPL v1.0.0

<!-- ── LIGHTWEIGHT LANE: use these five sections only, then stop ────────────────────────── -->

## What

<What shipped or changed, in a paragraph.>

## Why

<Why it was needed; one line on any real alternative and why it lost.>

## Verification

<Evidence against the acceptance test above, with links: CI runs, test output, drill logs,
measurements. "Verified" without a link does not count.>

## Rollback

<How to undo it, and whether that path was exercised (or why exercising it is impractical).>

## Next

<Follow-on work, each with its bead or issue reference.>

<!-- ── FULL LANE: use sections 1-9 instead of the five above ─────────────────────────────── -->

## 1. Summary and business value

<What shipped, in two paragraphs. What the organization can now do that it could not before.>

## 2. Scope — planned, completed, deferred

<The original scope; what actually completed; what was deferred and where it went (bead or
issue references). List any required documentation rows skipped, and why.>

## 3. Architecture and tradeoffs

<What was built and the shape it took. Every real alternative considered and why it lost —
"chose X over Y because Z". Interfaces or schemas exposed for future phases.>

## 4. Verification evidence

<Checked against the acceptance test in the header, not a prose goal. What was tested or drilled
and the linked evidence: CI runs, drill transcripts, logs, before/after measurements. Report
PASS, FAIL, SKIPPED, NOT RUN and BLOCKED separately.>

## 5. Issues and root causes

<What went wrong during the work, each traced to a root cause, not the proximate symptom.>

## 6. Lessons learned

<What we would do differently; which lessons became standing rules, and where those rules now
live (instructions file section, standard, hook, CI gate).>

## 7. Operational impact, including cost

<New or changed automations (with their registry rows where the estate keeps one), runtime and
storage footprint, money cost delta, attention burden delta.>

- **Recovery objectives:** effect on the recovery-point objective (RPO) and recovery-time
  objective (RTO); "none" must be argued.

## 8. Rollback procedure and validation

<How to undo this work, and the evidence the rollback path was actually exercised, or the argued
reason exercising it is impractical.>

- **Last relevant restore drill:** <date and link>, measured RTO <value>. Backups and disaster
  recovery are not "verified" without a measured RTO and a dated drill.

## 9. Next steps

<Recommended follow-on work, dependency-ordered, each with its bead or issue reference.>
