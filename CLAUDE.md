# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

dsgen turns a datasheet PDF + full orderable part number into a KiCad symbol (`.kicad_sym`, via
KiPart) and footprint (`.kicad_mod`, via kicad-footprint-generator / KicadModTree). The PDF is read
by Claude Code running headless (`claude -p`). Windows-first (Tkinter GUI, `dsgen.bat`,
`setup.ps1`). All code, UI text, prompts and new commit messages are in English; `README.es.md`
is the Spanish mirror of `README.md` and must be kept in sync.

## Commands

Always use the project venv (`.venv\Scripts\python`); the global Python lacks the dependencies.

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1   # clone vendor/ (pinned commit) + create .venv + install
.venv\Scripts\python -m dsgen                        # GUI (also: dsgen.bat)
.venv\Scripts\python -m dsgen file.pdf --part NE555DR -o out    # CLI extraction + generation
.venv\Scripts\python -m dsgen --from-json out\NE555D.component.json -o out   # regenerate, no AI
.venv\Scripts\python -m dsgen --usage                # accumulated Claude usage

.venv\Scripts\python -m pytest                       # generator tests, no AI (default excludes -m ai)
.venv\Scripts\python -m pytest tests/test_generators.py::test_symbol     # single test
.venv\Scripts\python -m pytest -k "QFN" -v           # parametrized cases by id
.venv\Scripts\python -m pytest -m ai -v              # end-to-end on pdf-test/ (calls Claude, costs usage)
```

`pytest -m ai` uses the extraction cache; set `DSGEN_FORCE=1` to call Claude again. `pdf-test/` is
git-ignored and local only: PDFs plus `<name>.case.json` expectation files (format documented in
the `tests/test_datasheets.py` docstring). There is no linter configured.

## Architecture

Pipeline (`dsgen/pipeline.py` orchestrates; the CLI in `__main__.py` and the GUI in `gui.py` both
call `extract_component()` and `generate()`):

1. `preprocess.py` — PyMuPDF keyword scoring → suggested ordering/pinout/package pages.
2. `cache.py` — key = sha256(PDF) + part number + `PROMPT_VERSION`, stored in `~/.dsgen/cache/`.
3. `extractor.py` — runs `claude -p` with `--append-system-prompt-file prompts/extract_component.md`,
   `--json-schema` (from `schema.component_json_schema()`, `$ref`s inlined), `--output-format
   stream-json --verbose`, `--tools Read`. The validated object comes back in the result event's
   `structured_output`. Every call is logged by `usage.py` to `~/.dsgen/usage.csv`.
4. `validate.py` — sanity checks; errors trigger one retry with the errors fed back to Claude.
5. `footprint_gen.py` — builds the footprint with a family builder (`families/`), then
   `kicad_lib.py` compares it against the installed official KiCad library; if an equivalent exists
   the symbol references the official footprint and nothing is written.
6. `symbol_gen.py` — KiPart CSV → `.kicad_sym` (merged into the output library).

`schema.py` (`Component`/`Package`/`Pin`/`Dim`) is the contract between AI and generators, and
its `Field(description=...)` texts are sent to Claude. **When changing the prompt or the schema,
bump `PROMPT_VERSION` in `cache.py`** or stale cached extractions are reused.

### Non-obvious details

- **Field conventions follow KLC**, not datasheet letters: `body_x` = E1 (between dual rows),
  `body_y` = D, `overall_x` = E tip-to-tip, `num_pins_x` = pins on top/bottom rows (0 for dual
  packages), `deleted_pins` = grid positions counted counter-clockwise. The prompt, the validator
  and the family builders all rely on this.
- **kicad-footprint-generator global state** (`families/__init__.py:init_kfg`): its modules read
  `generators.tools.cli_args.CLI_ARGS` at import time, so it must be initialized before importing
  `generators.package.*`, and later calls must mutate that same Namespace (not replace it).
  `generators` is a namespace package: use `generators.__path__`, not `__file__`.
- **gullwing / nolead** use the official IPC generators (`GullwingSpec`/`NoLeadSpec` +
  `create_footprints`) with dicts in the upstream YAML format; they write into a temp dir and the
  single `.kicad_mod` is picked up. **tab** (SOT-223/TO-252) is hand-built with KicadModTree and
  simplified IPC-7351B math; tab-family pins are numbered by grid position (no renumbering).
- **EP numbering:** generators emit the EP as `pin_count+1` (KLC). If the datasheet numbers it
  differently, the generated file is renumbered, or, when the official footprint is used, the
  symbol pins are renamed via `FootprintResult.pin_renames`.
- **Library matching** (`kicad_lib.py`) compares pad geometry, not names: pads normalized to their
  bounding-box center, same pad-number multiset, tolerances in `TOLERANCES` (looser for tab
  because official SOT-223/DPAK footprints are hand-made); ties prefer the same package-type
  prefix (QFN vs LQFN have identical pads). The index is cached in `~/.dsgen/fp_index_<ver>.json`.
- **Format downgrade:** the vendored generator writes KiCad 10 format (`version 20260206`, plus
  `duplicate_pad_numbers_are_jumpers`), which KiCad 9 cannot load. `kicad_env.downgrade_footprint`
  rewrites it according to the detected KiCad major version.
- **KiCad detection** (`kicad_env.find_kicad`): config `~/.dsgen/config.json` `kicad_dir`, env
  `DSGEN_KICAD_DIR`, `Program Files\KiCad\<ver>`, or `<drive>:\kicad<ver>` roots.
- **Claude auth:** dsgen uses whatever account is logged in to Claude Code on the machine. Do not
  add `--bare` to the `claude -p` call (it requires `ANTHROPIC_API_KEY`).
- Default model is `sonnet`; `haiku` was tested and misread mechanical drawing dimensions.
- `vendor/kicad-footprint-generator` is pinned to a commit in `setup.ps1` and installed into the
  venv; `.venv/`, `vendor/`, `out/` and `pdf-test/` are git-ignored.

## Tests

`tests/test_generators.py` defines packages with known JEDEC dimensions and asserts that each
generates, loads in `kicad-cli`, and matches a specific official footprint (e.g.
`Package_SO:SOIC-8_3.9x4.9mm_P1.27mm`). Tests that need KiCad are skipped if it is not found.
Rendering checks use `kicad-cli fp/sym export svg`, the same path `preview.py` uses for the GUI.
