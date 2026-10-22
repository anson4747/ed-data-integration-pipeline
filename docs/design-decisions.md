# Design decisions and known limits

Each entry says what was chosen, why, and what it costs. Written so the reasoning can be defended, not just repeated.

## Replication: Change Tracking, not CDC
Change Tracking records that a row changed and returns its current values. CDC records every historical version
of every change, but needs SQL Server Agent, which Express and some managed editions do not have. This pipeline
needs the current state of each row, not its history, so Change Tracking is enough and runs everywhere.
Cost: intermediate states between two runs are not seen. If the warehouse fell behind the retention window,
changes are gone, so the run detects that, reloads in full and raises a warning.

## Migrations: never edit an applied script
Each migration has a SHA-256 checksum. Editing an applied file is detected as drift and fails the deploy.
Fixes ship as a new numbered migration (see warehouse V004 and V010). Cost: some procedures appear twice in
the history; the latest definition wins.

## AIHW API: one reporting unit at a time
Unfiltered deep paging returned duplicate rows (971 of 45,210). Per unit extracts are clean, small and quick.
Each extract is checked against the API's own total. Duplicates fail the run instead of being quietly removed,
because removing them would hide a source fault.

## AIHW release marker, not timestamps
The API publishes `data_version`. An unchanged version is a no-op; a changed version replaces the stored slices
in one transaction and moves the marker with them. Cost: a revision inside an unchanged version would be missed.
`--force` reloads regardless.

## Dimension: Type 2 with effective dates
Network membership changes over time and reports must group by the network at the time. A dated reorganisation
starts a new version on its effective date even when the pipeline learns of it later; an ordinary source change
starts on the day it was seen.
* `valid_from = 1900-01-01` means "start of recorded history", not a founding date.
* Only network membership has dated history. Historic versions carry today's name and PHN, because the source
  gives no earlier values. Anyone reading old versions should know that.
* A period that straddles a change belongs to the version valid on its LAST day. The 2025-26 financial year
  (1 July 2025 to 30 June 2026) therefore lands on Bayside Health although half of it preceded the merger.
  The alternative (split or prorate) would invent figures. The choice is visible in `unit_key` and documented here.
* A unit that disappears from AIHW keeps its current version; nothing closes it. Retirement would need a
  deliberate rule, and AIHW has not retired codes in the observed releases.
* Reorganisations apply to hospitals only. A network's own row (for example LHN268) is AIHW's series for that
  legacy network and keeps its own code, so old and new series stay comparable.
* A reorganisation row that matches no hospital raises a Warning alert (found in review; it used to be silent).

## Fact: rebuilt, not merged
`dw.fact_ed_measure` holds tens of thousands of rows and is fully derivable from `ods.aihw_measurement`.
A transactional rebuild is simpler than an incremental merge and cannot drift. At a hundred million rows the
decision would change.

## Withheld is not zero
About 0.5% of figures are suppressed or not published (for example "NP", "<5"). They are stored with a NULL value,
the code, and `result_status = Withheld`. Rollups ignore them and say how many hospitals contributed.

## Data caveats
* Recorded AIHW data ends at 2024-25; no real period yet falls after the Bayside Health merger (1 January 2026).
  Tests simulate a 2025-26 release to prove the behaviour.
* The combined Bayside figure is not like for like across years: Bass Coast Hospital enters in 2019-20.
* MIMIC-IV-ED demo dates are shifted into the 2100s and its triage scale is the US ESI, not the Australasian Triage Scale (ATS).
