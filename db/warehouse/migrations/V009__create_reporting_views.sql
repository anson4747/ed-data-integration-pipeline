/*
    Reporting views for Power BI. Reports read rpt.*, never dw.* or ods.* directly, so the model underneath can
    change without breaking a report.

    rpt.ed_measure
        One row per figure, with the unit as it was at the end of the period (network_at_period) and as it is now
        (current_network). Withheld figures are kept with a NULL value and their reason, not dropped.

    rpt.network_ed_four_hour_current_definition
    rpt.network_ed_four_hour_as_at_period
        Share of ED patients leaving within four hours, per financial year, rolled up from hospitals and weighted
        by the number of presentations. "Current definition" groups every hospital under the network it belongs to
        today, so Bayside Health has a history before it existed. "As at period" groups hospitals under the network
        they belonged to when the figure was reported: figures for periods ending before 1 January 2026 stay under
        Alfred Health, Peninsula Health and the others, and Bayside Health appears with the first period that ends on
        or after that date (2025-26, not yet published by AIHW as at the current release).
        A hospital-year is included only when both its four-hour figure and its presentations are reported.
*/
CREATE OR ALTER VIEW rpt.ed_measure AS
SELECT f.reporting_unit_code, u.unit_name, u.unit_type_code, u.state_code,
       u.network_code AS network_code_at_period, u.network_name AS network_name_at_period,
       cur.network_code AS current_network_code, cur.network_name AS current_network_name,
       f.financial_year, f.reporting_start_date, f.reporting_end_date,
       f.measure_code, m.measure_name, f.reported_measure_code, f.reported_measure_name,
       f.value, f.lower_value, f.upper_value, m.units_name, m.units_display,
       f.result_status, f.suppression_codes, f.caveat_codes, f.peer_group_name, f.peer_value, f.data_version
FROM dw.fact_ed_measure AS f
JOIN dw.dim_reporting_unit AS u ON u.unit_key = f.unit_key
JOIN dw.dim_measure AS m ON m.measure_code = f.measure_code
LEFT JOIN dw.dim_reporting_unit AS cur ON cur.reporting_unit_code = f.reporting_unit_code AND cur.is_current = 1;
GO

CREATE OR ALTER VIEW rpt.network_ed_four_hour_current_definition AS
SELECT h.current_network_code AS network_code, h.current_network_name AS network_name, h.financial_year,
       COUNT(*) AS hospitals, SUM(p.value) AS presentations,
       CAST(SUM(h.value * p.value) / NULLIF(SUM(p.value), 0) AS decimal(9, 2)) AS four_hour_percent
FROM rpt.ed_measure AS h
JOIN rpt.ed_measure AS p
  ON p.reporting_unit_code = h.reporting_unit_code AND p.reporting_end_date = h.reporting_end_date
 AND p.measure_code = 'MYH0012' AND p.reported_measure_name = 'All patients' AND p.value IS NOT NULL
WHERE h.unit_type_code = 'H' AND h.measure_code = 'MYH0005' AND h.reported_measure_name = 'All patients'
  AND h.value IS NOT NULL AND h.current_network_code IS NOT NULL AND h.financial_year IS NOT NULL
GROUP BY h.current_network_code, h.current_network_name, h.financial_year;
GO

CREATE OR ALTER VIEW rpt.network_ed_four_hour_as_at_period AS
SELECT h.network_code_at_period AS network_code, h.network_name_at_period AS network_name, h.financial_year,
       COUNT(*) AS hospitals, SUM(p.value) AS presentations,
       CAST(SUM(h.value * p.value) / NULLIF(SUM(p.value), 0) AS decimal(9, 2)) AS four_hour_percent
FROM rpt.ed_measure AS h
JOIN rpt.ed_measure AS p
  ON p.reporting_unit_code = h.reporting_unit_code AND p.reporting_end_date = h.reporting_end_date
 AND p.measure_code = 'MYH0012' AND p.reported_measure_name = 'All patients' AND p.value IS NOT NULL
WHERE h.unit_type_code = 'H' AND h.measure_code = 'MYH0005' AND h.reported_measure_name = 'All patients'
  AND h.value IS NOT NULL AND h.network_code_at_period IS NOT NULL AND h.financial_year IS NOT NULL
GROUP BY h.network_code_at_period, h.network_name_at_period, h.financial_year;
GO
