# dsgen: from a datasheet PDF to a KiCad symbol and footprint

*[Leer en español](README.es.md)*

Inspired by scheMAGIC: give it the **datasheet PDF** and the **full orderable part number** and
you get the `.kicad_sym` and the `.kicad_mod`.

- **PDF reading:** Claude Code in headless mode (`claude -p`), guided by
  [`prompts/extract_component.md`](prompts/extract_component.md). It uses your Claude Code
  subscription; no API key needed.
- **Symbol:** [KiPart](https://github.com/devbisme/kipart).
- **Footprint:** the official IPC-7351 generators from
  [kicad-footprint-generator](https://gitlab.com/kicad/libraries/kicad-footprint-generator)
  (KicadModTree). If your KiCad installation already has an official footprint with the same pad
  geometry, that one is used.

## Requirements

- **Python 3.11+** and **git** in the PATH.
- **KiCad 8, 9 or 10.** It is detected automatically (`C:\Program Files\KiCad\<ver>`,
  `D:\kicad9.0`, …). If it is not found, set the `DSGEN_KICAD_DIR` environment variable or add
  `"kicad_dir"` to `~/.dsgen/config.json`.
- **Claude Code** (`claude`) installed and logged in on the machine:
  - Logging in once is enough (open `claude` and use `/login`). Claude Code does not need to be
    open while you use dsgen.
  - dsgen uses whichever account is logged in on that machine, so usage counts against that
    account's limits. To check which one, open `claude` and run `/status`.
  - If the `ANTHROPIC_API_KEY` environment variable is set, Claude Code may use that API key
    instead of the subscription.

## Quick start: double-click `dsgen.bat`

`dsgen.bat` is the Windows launcher:
- **The first time** it installs the environment with `setup.ps1` (takes a few minutes).
- **Afterwards** it opens the GUI directly, without leaving a console window open.

You can create a desktop shortcut to the `.bat`.

## Manual installation and usage

### Install

```powershell
cd "C:\path\to\datasheet2kicad-claude"
powershell -ExecutionPolicy Bypass -File setup.ps1
```

`setup.ps1` does the following:
1. Clones [kicad-footprint-generator](https://gitlab.com/kicad/libraries/kicad-footprint-generator)
   into `vendor/`, pinned to a tested commit.
2. Creates the `.venv/` virtual environment.
3. Installs the dependencies (KiPart, KicadModTree, pydantic, PyMuPDF…) and dsgen itself into it.

It is safe to run again, e.g. after deleting `.venv/`.

### Run

```powershell
.venv\Scripts\python -m dsgen            # GUI
.venv\Scripts\python -m dsgen datasheet.pdf --part TPS62130RGTR -o out   # command line
.venv\Scripts\python -m dsgen --from-json out\TPS62130RGT.component.json -o out   # without AI
.venv\Scripts\python -m dsgen --usage    # accumulated Claude usage
```

Command-line options:
- `--model sonnet|haiku|opus`: model to use (default `sonnet`).
- `--force`: ignore the cache and extract again.
- `--no-official`: generate the footprint even if an equivalent official one exists.
- `--lib name`: output library name (default `dsgen`).

Equivalent shortcuts:
```powershell
.venv\Scripts\dsgen                  # executable created by pip on install
.venv\Scripts\Activate.ps1           # activates the environment in this terminal...
python -m dsgen                      # ...after which plain "python" is enough
```

### What is and isn't in git

`.venv/`, `vendor/`, `out/` and `pdf-test/` are in `.gitignore`:
- `.venv/` is hundreds of MB, contains absolute paths of the machine where it was created, and
  can be regenerated.
- `vendor/` is an external repo that `setup.ps1` clones again.
- `pdf-test/` holds local datasheets for testing (see [Tests](#tests)).

What is versioned is the recipe to rebuild them: `pyproject.toml` and `setup.ps1`. On another
machine:

```powershell
git clone https://github.com/FacundoDallaFontana/datasheet2kicad-claude.git
cd datasheet2kicad-claude
.\dsgen.bat          # or: powershell -ExecutionPolicy Bypass -File setup.ps1
```

## Using the GUI

The flow is:
1. Pick the PDF, the part number and the output folder, and click **Extract with AI**.
2. Review and fix the pins, the package and the info. Problems are shown in red, and there are
   buttons to open the PDF at the page each value came from.
3. Click **Generate symbol + footprint** and check the symbol and footprint preview.

Output in the chosen folder:
- `<lib>.kicad_sym`: symbol library. Each new part is added; if it already existed, it is
  replaced.
- `<lib>.pretty/`: generated footprints. Only created when there is no equivalent official one.
- `<part>.component.json`: the extracted data. It can be edited and regenerated without calling
  the AI.

You need to add the `.kicad_sym` and the `.pretty` to KiCad's library tables.

## Usage tracking

Every Claude call (including retries and errors) is logged to `~/.dsgen/usage.csv`: date, PDF,
part number, model, turns, duration, tokens (input, output, cache) and equivalent cost in USD.
Extractions served from the cache cost nothing and are not logged.

- The GUI shows the running total at the bottom; "View details (CSV)" opens the file.
- From the command line: `.venv\Scripts\python -m dsgen --usage`

With a Claude Code subscription the cost is not billed separately, but it counts against your
usage limits. With Sonnet, one symbol + footprint costs roughly USD 0.10-0.15.

## How it works

```
PDF + part number
 → preprocess.py   candidate pages (ordering / pinout / package) with PyMuPDF
 → cache.py        if that PDF + part number was already extracted, Claude is not called
 → extractor.py    claude -p --json-schema … (output validated with schema.py)
 → validate.py     sanity checks; if there are errors, 1 retry with the details
 → [GUI: review]
 → footprint_gen.py  generates with the IPC generator → compares pads with the official library
                     (kicad_lib.py) → uses the official one or saves the generated one
 → symbol_gen.py     KiPart (with the Footprint property pointing to the chosen one)
```

Footprint families supported:
- `gullwing`: SOIC, SSOP, TSSOP, MSOP, QFP and SOT-23.
- `nolead`: QFN, DFN and SON, with EP.
- `tab`: SOT-223, TO-252 and TO-263.

For anything else (`other`) only the symbol is generated.

To tune what the AI looks for in the PDF, edit `prompts/extract_component.md` and bump
`PROMPT_VERSION` in `dsgen/cache.py` to invalidate the cache.

## Tests

```powershell
.venv\Scripts\python -m pytest            # generator tests, no AI
.venv\Scripts\python -m pytest -m ai -v   # end-to-end tests on real datasheets (call Claude)
```

- **Generator tests (default):** they build known JEDEC packages, check that they match the
  official KiCad footprints and that `kicad-cli` can open every generated file.
- **Datasheet tests (`-m ai`):** they run on the PDFs in `pdf-test/`, a local, git-ignored
  folder. For each PDF, add a `<name>.case.json` with the part number and the expected result
  (pins, package family, footprint…); the format is described in
  [`tests/test_datasheets.py`](tests/test_datasheets.py). They use the extraction cache; set
  `DSGEN_FORCE=1` to call Claude again (for example after changing the prompt).

## Notes

- Model: `sonnet` by default. In our tests `haiku` got the pins right but misread the mechanical
  drawing dimensions, and it was also slower.
- kicad-footprint-generator writes the KiCad 10 format. If your KiCad is 8 or 9, the file is
  converted automatically (`kicad_env.downgrade_footprint`).
- For the tab family, the land pattern is computed with nominal IPC-7351B. The official
  SOT-223/DPAK footprints are hand-made, so matching them is more tolerant (±0.3 mm).

## License

[MIT](LICENSE). Dependencies have their own licenses: KiPart is MIT and kicad-footprint-generator
is GPL-3.0. The latter is not included in the repo: `setup.ps1` downloads it into `vendor/`.
