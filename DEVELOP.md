# Developer guide

This document covers local development, versioning, and publishing releases to PyPI.

## Local setup

Install the package in editable mode with developer dependencies:

```console
python -m pip install -e ".[dev]"
```

Install pre-commit hooks (optional but recommended):

```console
pre-commit install
```

Run tests:

```console
pytest
```

Build a wheel and sdist locally:

```console
python -m pip install build
python -m build
```

## Versioning

Package versions are derived automatically by [setuptools-scm](https://github.com/pypa/setuptools_scm) from git tags. There is no static `version` field in `pyproject.toml`.

Configuration in `pyproject.toml`:

- `version_scheme = "no-guess-dev"` — do not guess the next dev release number from commit distance.
- `local_scheme = "dirty-tag"` — append a local suffix when the working tree has uncommitted changes.
- `write_to = "src/materia_epd/_version.py"` — generate `__version__` at build/install time.

### How versions are resolved

| Situation | Example version |
|-----------|-----------------|
| Exactly on tag `v0.7.0` | `0.7.0` |
| Commits after `v0.7.0` | `0.7.0.post1.dev0+g<hash>` (not suitable for PyPI) |
| Uncommitted changes on a tag | `0.7.0+d<date>` (not suitable for PyPI) |

Release versions for PyPI must come from a **clean checkout of an annotated git tag** matching `vX.Y.Z`.

Check the version after an editable install:

```console
python -c "from materia_epd import __version__; print(__version__)"
```

The generated `src/materia_epd/_version.py` is not tracked in git. It is created when you run `pip install -e .` or `python -m build`.

## Release checklist

1. **Update the changelog** — add a `Version X.Y.Z (YYYY-MM-DD)` section to [`CHANGELOG.md`](CHANGELOG.md).
2. **Commit and merge** — land the changelog and any final changes on your release branch.
3. **Create an annotated tag** on the release commit:

   ```console
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```

4. **Verify the tag locally** (optional but recommended):

   ```console
   git checkout vX.Y.Z
   python -m pip install -e .
   python -c "from materia_epd import __version__; print(__version__)"
   ```

   The printed version should be exactly `X.Y.Z` with no `+` or `.dev` suffix.

5. **Dry-run on TestPyPI** — GitHub → Actions → **Publish to PyPI** → Run workflow:
   - Tag: `vX.Y.Z`
   - Target: `testpypi`

6. **Publish to PyPI** — run the same workflow with target `pypi`.

## One-time PyPI setup (trusted publishing)

This repository uses [PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/) (OIDC). No long-lived API tokens or GitHub repository settings are required.

Trusted publishing only needs configuration on PyPI/TestPyPI (which you control) and the `publish.yml` workflow file in this repository. You do **not** need access to GitHub **Settings → Environments** or **Secrets**.

### PyPI (production)

1. Open [materia-epd publishing settings](https://pypi.org/manage/project/materia-epd/settings/publishing/) on PyPI.
2. Add a new trusted publisher:
   - **PyPI project name:** `materia-epd`
   - **Owner:** `pbaustert`
   - **Repository name:** `materia-epd`
   - **Workflow name:** `publish.yml`
   - **Environment name:** leave **blank** (do not fill in)

### TestPyPI

1. Create the `materia-epd` project on [TestPyPI](https://test.pypi.org/) if it does not exist yet.
2. Add a trusted publisher with the same owner, repository, and workflow name.
3. Leave **Environment name** blank here as well.

When the environment field is empty on PyPI, it matches workflow runs that do not declare a GitHub environment. The workflow's `target` input (`pypi` vs `testpypi`) only selects the upload URL; authentication is handled separately by each platform's trusted publisher entry.

### Optional: GitHub environments (not required)

If you later gain repository admin access, you can add `pypi` / `testpypi` environments with required reviewers for an extra approval step. That is optional hardening, not required for trusted publishing to work.

## Troubleshooting

### `HEAD is not exactly tag vX.Y.Z`

The workflow checks out the tag you provide. Ensure the tag exists on GitHub and points to the intended commit:

```console
git fetch --tags
git show vX.Y.Z
```

### Version contains `+` or `.dev`

You are not on a clean release tag. Create and push a new `vX.Y.Z` tag on the release commit, then run the workflow with that tag.

### `git describe` fails in CI

The workflow uses `fetch-depth: 0` so setuptools-scm can see all tags. If you change the workflow, keep a full clone.

### PyPI: "File already exists"

That version was already uploaded. Bump the version (new git tag) and publish again. PyPI does not allow overwriting existing releases.

### Trusted publishing authentication failed

Confirm the trusted publisher on PyPI/TestPyPI matches:

- Repository: `pbaustert/materia-epd`
- Workflow file: `publish.yml`
- Environment name: **left blank** on PyPI (must match the workflow, which does not declare a GitHub environment)

If you previously configured an environment name (e.g. `pypi`) on PyPI, either clear that field or add the matching GitHub environment — otherwise OIDC authentication will fail.

### `from materia_epd import __version__` returns `unknown`

Run `pip install -e .` (or `pip install -e ".[dev]"`) so setuptools-scm generates `_version.py`.
