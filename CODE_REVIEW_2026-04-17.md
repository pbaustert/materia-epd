# Code & Issue Review (April 17, 2026)

This review captures issues found during an initial local audit of the repository.

## 1) Test execution prerequisites are not obvious

### What I observed
- Running `pytest` in a fresh environment fails before test collection because project dependencies and test extras are not yet installed.
- Running `pytest` also fails if `pytest-cov` is missing, because coverage flags are configured in `pyproject.toml` `addopts`.

### Why this matters
Contributors can interpret this as a broken test suite when it is really an environment/setup problem.

### Recommendation
Document a canonical developer setup sequence:
1. `python -m pip install -e ".[dev]"`
2. `pytest`

## 2) Packaging configuration for data files appears incorrect

### What I observed
`pyproject.toml` currently sets:

```toml
[tool.setuptools.package-data]
materia = ["data/*.json"]
```

The importable package is `materia_epd`, and runtime code reads data from `materia_epd.data`.

### Why this matters
Built distributions may omit required JSON resource files, causing runtime failures after install (even if local source-tree runs pass).

### Recommendation
Use package-data key `materia_epd.data` with recursive JSON inclusion.

## 3) TODO in EPD model version metadata

### What I observed
`src/materia_epd/epd/models.py` contains a TODO where process version is hardcoded as `"00.00.000"`.

### Why this matters
Generated artifacts can carry non-actionable version metadata.

### Recommendation
Populate this dynamically (e.g., from input datasets or package/release metadata).

## 4) Minor documentation typo and clarity gaps

### What I observed
README contains minor typos in directory/wording examples (`provesses`, `strucured`, repeated filename example), and lacked explicit test setup instructions.

### Recommendation
Gradually clean docs for onboarding quality and reliability.

---

## Changes applied in this branch
- Fixed package-data target in `pyproject.toml` so JSON resources under `materia_epd.data` are included in distributions.
- Added a short "Development / running tests" section in `README.md` with explicit setup + test command.
