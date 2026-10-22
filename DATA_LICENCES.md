# Data licences and attribution

No source data is committed to this repository except a small recorded AIHW API sample used by the tests
(`tests/fixtures/aihw/`). Everything else is downloaded at run time from its publisher.

## AIHW MyHospitals

* Publisher: Australian Institute of Health and Welfare (AIHW)
* Source: MyHospitals API, `https://myhospitalsapi.aihw.gov.au/api/v1`
* Licence: [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/)
* Use here: emergency department measures by hospital and network, loaded into `ods.aihw_*` and `dw.fact_ed_measure`.
  Figures are reproduced as published; suppressed values keep AIHW's own codes.
* Attribution: "Source: Australian Institute of Health and Welfare, MyHospitals." The recorded test sample is a
  verbatim subset of API responses.

## MIMIC-IV-ED demo and MIMIC-IV demo (version 2.2)

* Publisher: PhysioNet, on behalf of the MIT Laboratory for Computational Physiology and Beth Israel Deaconess
  Medical Center
* Sources: [MIMIC-IV-ED Demo](https://physionet.org/content/mimic-iv-ed-demo/2.2/) and
  [MIMIC-IV Clinical Database Demo](https://physionet.org/content/mimic-iv-demo/2.2/)
* Licence: [Open Data Commons Open Database License v1.0 (ODbL)](https://opendatacommons.org/licenses/odbl/1-0/)
* Use here: loaded into the mock EMR (`SourceEMR` database) to imitate a live hospital system. Files are downloaded
  by `edpipe.sources.fetch` and checked against SHA-256 checksums before loading. They are git-ignored.
* Please cite the datasets as shown on their PhysioNet pages, together with the standard PhysioNet citation
  (Goldberger et al., *Circulation*, 2000).
* Notes on the data: it covers 100 patients and 222 ED stays; dates are shifted into the 2100s for de-identification;
  triage acuity uses the US Emergency Severity Index (ESI), not the Australasian Triage Scale; temperatures are in
  Fahrenheit.
* ODbL share-alike: any derived database published from this data must also be under ODbL. Nothing derived is
  published from this repository.

## Bayside Health merger

* Source: Premier of Victoria media release, 29 August 2025,
  [Bayside Health voluntary merger to strengthen care](https://www.premier.vic.gov.au/bayside-health-voluntary-merger-strengthen-care)
* Use here: the effective date (1 January 2026) and the five merging services, recorded as facts in
  `ref.lhn_reorganisation` with the source URL on every row.

## Code

The code in this repository is under the [MIT licence](LICENSE). The licences above apply to the data, not the code.
