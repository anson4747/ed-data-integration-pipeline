# AIHW MyHospitals API: what probing it showed

Base URL `https://myhospitalsapi.aihw.gov.au/api/v1`. Data is published by the Australian Institute of
Health and Welfare under CC BY 4.0. Everything below was observed against the live service on
22 October 2026 (API 1.6.4.0, data_version 2026081901) by calling it from a GitHub Actions runner.

## Shape

| Need | Endpoint | Notes |
|---|---|---|
| Release marker | `GET /measure-categories` | Smallest response (about 1 KB). Every response carries `version_information.data_version`. |
| Reporting units | `GET /reporting-units` | 1,428 units (hospitals, networks, states, national, peer groups), about 2.3 MB. Hospital to network and state links are in `mapped_reporting_units`. |
| Flag codes | `GET /suppressions`, `GET /caveats` | 28 codes each. Same codes, different kinds. |
| Measures | `GET /flat-data-extract/{category}` | `skip` and `top` are both required. `top` is at most 1000. Optional `reporting_unit_code`, `measure_code`, dates. |

Emergency department categories used: `MYH-ED-TIME` (time in ED), `MYH-ED` (presentations),
`MYH-ED-WAITS` (waiting times by triage category).

## Behaviour that shaped the design

1. **Unfiltered deep paging returns duplicate rows.** Paging all of `MYH-ED-WAITS` (45,210 rows over
   46 pages) returned 971 exact duplicate rows. The same hospital pulled with `reporting_unit_code`
   gave 140 unique rows of 140. Offset paging without a stable ordering is the likely cause.
   The pipeline therefore extracts one reporting unit at a time and checks each extract against
   `pagination.total_results_available`. Duplicate keys are never silently removed: they fail the run.
2. **Large unfiltered requests time out.** The first page of unfiltered `MYH-ED-TIME` and `MYH-ED`
   did not answer within 60 seconds. The full `MYH-ED-WAITS` walk took about 11 minutes. Per unit
   requests return in well under a second.
3. **Empty is a valid answer.** A skip past the end, an unknown category and a hospital with no
   emergency department all return `200` with zero rows, not an error. An empty result is therefore
   never accepted as proof of anything. If a whole category is empty for every unit, the run fails.
4. **The gateway rejects the default `python-requests` User-Agent with 403.** The same request with
   curl, or with an identifying agent string, returns 200. The client sends
   `ed-data-integration-pipeline/0.1 (...)`. This was found when the first live run failed, and is
   covered by a unit test.
5. **Figures are not always numbers.** About 5% of rows carry a caveat or suppression code. Examples:
   `X40` "NP" (the reported data did not meet the criteria to calculate the indicator, no value),
   `X42` "*" (a value, but 5 to 10% of presentations had missing or invalid time data). The pipeline
   keeps the code, the decoded meaning and a three-way `result_status`:
   `Reported`, `ReportedWithCaveat`, `Withheld`. A withheld figure is NULL, never zero.
6. **Network membership is not yet updated for Bayside Health.** The API still maps The Alfred,
   Caulfield and Sandringham to "Alfred Health (Vic)" and Frankston and Rosebud to "Peninsula Health (Vic)".
   The merger into Bayside Health took effect on 1 January 2026. The hospital dimension (next stage)
   handles this as a slowly changing dimension with the effective date.

## Natural key

`(measure_code, reported_measure_code, reporting_unit_code, reporting_start_date, reporting_end_date)`
is unique within every recorded slice (27 slices, 0 duplicates).

## Release logic

`data_version` is a whole-dataset release marker (here `2026081901`, the 19 August 2026 upload).
The pipeline stores the last loaded version in `etl.watermark` (`aihw.myhospitals`, type
`ApiDataVersion`). A run that finds the same version records a `Skipped` step and does nothing else.
