=========
Changelog
=========

Unreleased (branch `web-site-version`)
--------------------------------------

- Generic EPD JSON objects (the ``jsons/<ID>.json`` format: "ID", "Product Reference
  (French)", "Cat. 1-3", "Declared Unit", "Market Shares", "HS Code", ...) are turned into
  generic process + reference flow XMLs from the GenPro/GenRef templates
  (new `materia_epd.epd.generic`: `build_generic_datasets`, `generic_process_from_json`).
  The templates are bundled in `materia_epd/data/templates`; `<gen>/templates` takes
  precedence in local mode. The generic ID is the process UUID, the reference flow declares
  1 "Declared Unit", and "Market Shares" from the object are used as the market (unknown
  location codes are ignored with a warning). Unused fields, e.g. the website's
  `cptax_classification`, are ignored.
- from-url mode accepts these objects: per process `{"generic": {...}, "matches": {...}}`,
  a generic object with an embedded `"matches"`, or the website export
  `{"project_name": ..., "data": [...]}` as a whole spec.
- Local mode also builds generic processes from `<gen>/jsons/<ID>.json` +
  `<gen>/matches/<ID>.json` when there is no XML skeleton in `<gen>/processes`
  (`load_generic_jsons`; only the objects with a matches file are read).
- New `resources.list_locations()` (location codes for "Market Shares") and
  `resources.templates_dir()`.
- Writing the outputs of a process (XML, JSON / PDF report) no longer aborts the run on
  error; the failure is recorded as a diagnostic.

- Add a "from-url" mode that fetches the source EPDs from an HTTP file server
  (`{base_url}/xml/<uuid>.xml`, reference flows from `{base_url}/flows/<uuid>.xml`)
  instead of local folders. The conventional local-folder mode is unchanged.
  - CLI: `materia-epd --from-url spec.json [--base-url URL] -o <output_dir>`; the base
    URL can also come from the spec (`base_url`) or `$MATERIA_EPD_BASE_URL`.
  - Python API: `materia_epd.pipeline.run.run_materia_from_url(spec, output_path=None)`
    returns a JSON-serializable summary per generic process (status, selected / missing /
    rejected EPDs, averaged properties and impacts, report, diagnostics, written files)
    and writes `from_url_summary.json` when an output folder is given.
  - The spec is a list of EPD UUIDs, a single process object or `{"processes": [...]}`;
    each process takes `matches` (same format as `matches/<uuid>.json`) or `uuids` + `type`,
    plus optional `uuid`, `name`, `location`, `hs_class`, `declared_unit`, and the skeleton
    options `template` (source EPD UUID) or `template_url` / `template_flow_url`.
  - Without a template URL the generic process skeleton is built from a source EPD (default:
    first fetched match): new process UUID, renamed reference flow, 1 declared unit.
- New `materia_epd.io.remote.UrlSource`: cached, concurrent download of process XMLs with
  their reference flows; unreachable EPDs are reported as missing with the HTTP error.
- `IlcdProcess` accepts an optional `flow_loader` to resolve its reference flow without a
  local `flows` folder; new helper `reference_flow_uuid(root)`.
- `IlcdProcess.get_hs_class` no longer fails on datasets without an HS classification
  (`hs_class = None`), and `get_market` returns `{}` without location or HS class instead
  of generating a Comtrade market.
- `run_materia` was split into reusable steps (`expand_process_uuids`,
  `collect_required_epd_uuids`, `execute_processes`) and now returns the pipeline context of
  each process. An exception in one process is recorded as an error diagnostic instead of
  stopping the run, and no files are written when no output folder is given.
- `EpdPipelineContext.outputs` lists the files written for the process.

Version 0.8.0 (2026-09-08)
--------------------------

- Add `--process-list` CLI option to run pipeline only for specified process UUIDs from a JSON file

Version 0.7.0 (2026-06-16)
--------------------------

- Codex/colors
- Adding new surface-based scaling to fix #73
- Refactor report generation and PDF output (metadata extraction, market sankey, layout) fix #75
- Add mass conversion validation stage and tests fix #78
- Handle singular matrix in physics projection solver fix #79
- Derive A4 transport impacts from market shares and add per-kg transport factors fix #80
- Handle missing module impact values in impact comparison table fix #81
- Enhance PDF report with multilingual product names, A4 impacts and icon-based change column fix #83
- Include A4 in impact tables/plots, tweak report layout, and add tests fix #84
- Fix canvas variable shadowing in report drawing and add regression test fix #85
- Derive A4 and C2 transport impacts, zero averaged C1, update pipeline and tests fix #86
- fixes for #87 and #89
- Add assembled-products recipe with component aggregation stages and orchestration fix #88

Version 0.6.0 (2026-04-08)
--------------------------

- Update pipeline structure to flexible structure
- Allow for simple averaging as well as market-averaging

Version 0.5.0 (2026-02-12)
--------------------------

- Try, Except blocks introduced to prevent the calculation loop to stop (Issue 42).
- An structlog logger with two handlers (file and console) was introduced and print statements were removed.
- The flag `--verbose` was introduced to control the verbosity of the logger.
- The logic of the EPDs calculation in `src/epd/pipeline.py` was changed. The `gen_epds` generator is now created just once making the mode more efficient.

Version 0.4.0 (2025-12-05)
--------------------------

- MISSING

Version 0.3.0 (2025-11-12)
--------------------------

- Rename package to materia-epd.
- Update cli tool to receive encompassing ILCD folders
- Integrate market generation based on comtrade

Version 0.2.4 (2025-11-11)
--------------------------

- Add robust functionality to deal with cases of no appropriate epd data.

Version 0.2.3 (2025-10-27)
--------------------------

- Correct coverage badge on pypi.

Version 0.2.2 (2025-10-27)
--------------------------

- Add correct readme and Changelog file.

Version 0.2.1 (2025-10-27)
--------------------------

- Fix version reading issue.

Version 0.2.0 (2025-10-24)
--------------------------

- Added function to write output pocesses
- Updated badges

Version 0.1.0 (2025-10-23)
--------------------------

- Initial release
- Added EPD aggregation features
- Normalization of material properties and LCIA modules
- Cli tool to access basic functions
