# Generic EPD Aggregator

[![Build](https://github.com/pbaustert/materia-epd/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/pbaustert/materia-epd/actions/workflows/ci.yml)
![Coverage](https://raw.githubusercontent.com/pbaustert/materia-epd/main/coverage.svg)
[![PyPI](https://img.shields.io/pypi/v/materia-epd.svg)](https://pypi.org/project/materia-epd/)
[![Python](https://img.shields.io/pypi/pyversions/materia-epd.svg)](https://pypi.org/project/materia-epd/)
[![Documentation](https://readthedocs.org/projects/materia-epd/badge/?version=latest)](https://materia-epd.readthedocs.io/en/latest/)
[![License](https://img.shields.io/github/license/pbaustert/materia-epd)](https://github.com/pbaustert/materia-epd/blob/main/LICENSE.txt)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://pre-commit.com/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Flake8](https://img.shields.io/badge/linting-flake8-blue)](https://flake8.pycqa.org/en/latest/)

---

# Features

- Parse ILCD process and flow XMLs
- Normalize material properties and LCIA modules
- Aggregate impacts and compute weighted averages
- Write new ILCD XML datasets

---

## Installation

Install via PyPI:

```console
pip install materia-epd
```

Requires Python 3.10+.

---

## Documentation

Full documentation is hosted on [Read the Docs](https://materia-epd.readthedocs.io/en/latest/).

It covers the EPD pipeline, module reference, contributing guidelines, and the changelog.

---

## Usage

### Run the aggregator

```console
python -m materia_epd <generic_processes_dir> <epd_processes_dir> -o <output_dir> -v
```

Note that you need to point to the root `processes` folders and need to provide a `matches` folder in the generic data folder to link generic products and EPDs.
Add the flag `--v` or `-v` for verbosity. Logs files with details will be automatically created in `<output_dir>`.

#### Run for specific processes only

By default, the pipeline runs for all processes with defined matches. To run only for specific processes, provide a JSON file containing an array of UUIDs via the `--process-list` or `-p` option:

```console
python -m materia_epd <generic_processes_dir> <epd_processes_dir> -p process_list.json -o <output_dir>
```

Example `process_list.json`:
```json
[
  "8a3b1c4d-5e6f-7g8h-9i0j-1k2l3m4n5o6p",
  "2d4e6f8a-9b1c-2d3e-4f5g-6h7i8j9k0l1m"
]
```
The `<generic_processes_dir>` folder should be structured like this:


```
<generic_process_dir>
├── flows
│   ├── <flow-uuid-1>.xml   # Reference flow of generic-uuid-1
│   ├── <flow-uuid-2>.xml
│   └── ...
├── matches
│   ├── <generic-uuid-1>.json   # Source EPDs for generic-uuid-1
│   ├── <generic-uuid-2>.json
│   └── ...
├── PDFs
├── processes
│   ├── <generic-uuid-1>.xml   # Skeleton process for generic-uuid-1
│   ├── <generic-uuid-2>.xml
│   └── ...
└── templates
    ├── GenPro_template.xml # Template with the EPD schema
    └── GenRef_template.xml # Template with the flow schema

```

Instead of XML skeletons in `processes/`, a generic product can be described by a JSON object in
`jsons/<generic-uuid>.json` (fields such as `ID`, `Product Reference (French)`, `Cat. 1 (French)`,
`Declared Unit`, `Market Shares`, `HS Code`; unknown fields are ignored). When `processes/` has no
skeleton for an ID that has a `matches/<ID>.json` file, the process and its reference flow are built from
`templates/GenPro_template.xml` / `GenRef_template.xml` (or the templates bundled with the package), and
the market shares of the JSON object are used.

#### Source EPDs (`<epd_processes_dir>`)

```
<epd_process_dir>
├── flows       # Reference flows for all source EPDs
└── processes   # All potential source EPD process XMLs
```

### Matches JSON

Files in `matches/` are named after the corresponding generic product UUID:

```json
{
  "type": "<aggregation_type>",
  "uuids": [
    "<uuid-1>",
    "<uuid-2>",
    "<uuid-3>",
    "... more UUIDs ..."
  ]
}
```

`type` is `"average"`, `"market-average"`, `"assembled"` or `"regression"`. The `uuids` list links to process files in the source EPD `processes/` folder.

### Run from a file server (from-url mode)

Instead of local folders, the source EPDs can be fetched from an HTTP file server that serves
`<base_url>/xml/<uuid>.xml` (process datasets) and `<base_url>/flows/<uuid>.xml` (flows):

```console
python -m materia_epd --from-url spec.json --base-url http://erp-canaria.private.list.lu:44003/raw -o <output_dir>
```

The base URL can also be given as `base_url` in the spec or through the `MATERIA_EPD_BASE_URL`
environment variable. The spec lists the generic processes to compute:

```json
{
  "base_url": "http://erp-canaria.private.list.lu:44003/raw",
  "processes": [
    {
      "uuid": "<generic-uuid, random if omitted>",
      "name": "Generic concrete slab",
      "location": "LU",
      "matches": { "type": "average", "uuids": ["<epd-uuid-1>", "<epd-uuid-2>"] }
    }
  ]
}
```

A plain list of EPD UUIDs (`["<uuid-1>", "<uuid-2>"]`) is a shorthand for one `average` process.

A process can also be a **generic EPD JSON object** (the `jsons/<ID>.json` format) with its matches,
either as `{"generic": {...}, "matches": {...}}` or as the object with an embedded `"matches"` key. The
export of the MECO EPD website, `{"project_name": "...", "data": [<generic EPD>, ...]}`, is accepted
as a spec as is. The generic process is then built from the templates (UUID = `ID`, declared unit, HS
code, market shares from the object) instead of a source EPD.
`matches` has the same format as the files in `matches/` (or use `"uuids": [...]` with an optional
`"type"`). Optional per-process keys:

| key | meaning |
| --- | --- |
| `template` | UUID of the source EPD used as skeleton for the generic process (default: first fetched EPD) |
| `template_url`, `template_flow_url` | URLs of a ready generic process XML and its reference flow, used instead of a source EPD |
| `declared_unit` | `mass`, `volume`, `surface`, `length` or `unit_count` (default: the template's) |
| `location` | ILCD location code of the generic process, e.g. `LU` (default: the template's) |
| `hs_class` | HS code, needed for `market-average` / `regression` and the A4 market transport |

A skeleton built from a source EPD gets the new UUID and name, a renamed reference flow and a
declared amount of 1 unit; only the LCIA indicators/modules present in that EPD are written to the
output process XML. Outputs (`processes/`, `flows/`, `reports/`) are as in local mode, plus
`from_url_summary.json`. From Python:

```python
from materia_epd.pipeline.run import run_materia_from_url

result = run_materia_from_url(["<uuid-1>", "<uuid-2>"], output_path=None,
                              base_url="http://erp-canaria.private.list.lu:44003/raw")
result["processes"][0]["avg_impacts"]["Climate change-Total"]["A1-A3"]
```

---

## Development / running tests

See [DEVELOP.md](DEVELOP.md) for local setup, versioning, and PyPI release instructions.

For local development, install the package in editable mode with developer dependencies:

```console
python -m pip install -e ".[dev]"
```

Then run tests:

```console
pytest
```
