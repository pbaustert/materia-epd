=========
Changelog
=========

Version 0.5.0 (2026-02-12)
===========

- Try, Except blocks introduced to prevent the calculation loop to stop (Issue 42).
- An structlog logger with two handlers (file and console) was introduced and print statements were removed.
- The flag `--verbose` was introduced to control the verbosity of the logger.
- The logic of the EPDs calculation in `src/epd/pipeline.py` was changed. The `gen_epds` generator is now created just once making the mode more efficient.

Version 0.4.0 (2025-12-05)
===========

- MISSING

Version 0.3.0 (2025-11-12)
===========

- Rename package to materia-epd.
- Update cli tool to receive encompassing ILCD folders
- Integrate market generation based on comtrade

Version 0.2.4 (2025-11-11)
===========

- Add robust functionality to deal with cases of no appropriate epd data.

Version 0.2.3 (2025-10-27)
===========

- Correct coverage badge on pypi.

Version 0.2.2 (2025-10-27)
===========

- Add correct readme and Changelog file.

Version 0.2.1 (2025-10-27)
===========

- Fix version reading issue.

Version 0.2.0 (2025-10-24)
===========

- Added function to write output pocesses
- Updated badges

Version 0.1.0 (2025-10-23)
===========

- Initial release
- Added EPD aggregation features
- Normalization of material properties and LCIA modules
- Cli tool to access basic functions
