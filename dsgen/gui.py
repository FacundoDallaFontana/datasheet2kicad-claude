"""Simple GUI (Tkinter): pick the PDF + part number + folder, review the extraction and generate."""
from __future__ import annotations

import queue
import tempfile
import threading
import tkinter as tk
import traceback
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Optional, get_args

from pydantic import ValidationError

from .extractor import MODELS, ExtractionError
from .schema import Component, Dim, ExposedPad, Family, Package, Pin, PinStyle, PinType, Side, Tab
from .validate import Issue, check

PIN_COLUMNS = ("number", "name", "type", "side", "unit", "style")
PIN_CHOICES = {"type": get_args(PinType), "side": get_args(Side), "style": get_args(PinStyle)}
DIM_FIELDS = [
    ("body_x", "Body X (E1)"), ("body_y", "Body Y (D)"), ("overall_x", "Overall X (E)"),
    ("overall_y", "Overall Y (QFP)"), ("body_height", "Height (A)"), ("lead_width", "Lead width (b)"),
    ("lead_len", "Lead length (L)"), ("ep.x", "EP X (E2)"), ("ep.y", "EP Y (D2)"),
    ("tab.width", "Tab width"), ("tab.length", "Tab length"),
]
RED = "#c62828"


def _num(text: str) -> Optional[float]:
    text = text.strip().replace(",", ".")
    return float(text) if text else None


def _fmt(v) -> str:
    return "" if v is None else f"{v:g}"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("dsgen — datasheet → KiCad symbol and footprint")
        self.geometry("1100x760")
        self.minsize(900, 600)
        self.component: Optional[Component] = None
        self.msgs: queue.Queue = queue.Queue()
        self._images: list[tk.PhotoImage] = []
        self._build_inputs()
        self._build_tabs()
        self._build_actions()
        self.after(100, self._drain_queue)

    # ------------------------------------------------------------------ layout
    def _build_inputs(self) -> None:
        f = ttk.LabelFrame(self, text="1. Input", padding=8)
        f.pack(fill="x", padx=8, pady=(8, 4))
        f.columnconfigure(1, weight=1)
        self.pdf_var, self.part_var = tk.StringVar(), tk.StringVar()
        self.out_var, self.lib_var = tk.StringVar(value=str(Path.cwd() / "out")), tk.StringVar(value="dsgen")
        self.model_var = tk.StringVar(value="sonnet")
        self.force_var, self.official_var = tk.BooleanVar(), tk.BooleanVar(value=True)

        ttk.Label(f, text="Datasheet (PDF)").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.pdf_var).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(f, text="Browse…", command=self._pick_pdf).grid(row=0, column=2)
        ttk.Label(f, text="Full part number").grid(row=1, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.part_var).grid(row=1, column=1, sticky="ew", padx=4)
        ttk.Label(f, text="e.g. TPS62130RGTR (the suffix defines the package)",
                  foreground="gray").grid(row=1, column=2, sticky="w")
        ttk.Label(f, text="Output folder").grid(row=2, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.out_var).grid(row=2, column=1, sticky="ew", padx=4)
        ttk.Button(f, text="Browse…", command=self._pick_out).grid(row=2, column=2)

        opts = ttk.Frame(f)
        opts.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(opts, text="Library").pack(side="left")
        ttk.Entry(opts, textvariable=self.lib_var, width=14).pack(side="left", padx=(4, 12))
        ttk.Label(opts, text="Model").pack(side="left")
        model_box = ttk.Combobox(opts, textvariable=self.model_var, values=MODELS, width=8, state="readonly")
        model_box.pack(side="left", padx=(4, 12))
        model_box.bind("<<ComboboxSelected>>", lambda _: self.model_var.get() == "haiku" and self.status.configure(
            text="Haiku reads pins well but makes mistakes on mechanical drawings; check the package."))
        ttk.Checkbutton(opts, text="Force re-extraction", variable=self.force_var).pack(side="left", padx=4)
        ttk.Checkbutton(opts, text="Use the official KiCad footprint if one exists",
                        variable=self.official_var).pack(side="left", padx=4)
        self.extract_btn = ttk.Button(opts, text="Extract with AI", command=self._extract)
        self.extract_btn.pack(side="left", padx=(16, 4))
        ttk.Button(opts, text="Open JSON…", command=self._open_json).pack(side="left")

    def _build_tabs(self) -> None:
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=4)

        self.log = ScrolledText(self.nb, height=10, font=("Consolas", 9), state="disabled")
        self.nb.add(self.log, text="Log")

        pins = ttk.Frame(self.nb, padding=4)
        self.tree = ttk.Treeview(pins, columns=PIN_COLUMNS, show="headings", selectmode="browse")
        widths = {"number": 60, "name": 220, "type": 130, "side": 80, "unit": 50, "style": 110}
        for c in PIN_COLUMNS:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=widths[c], stretch=c == "name")
        self.tree.tag_configure("bad", foreground=RED)
        sb = ttk.Scrollbar(pins, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        pins.rowconfigure(0, weight=1)
        pins.columnconfigure(0, weight=1)
        bar = ttk.Frame(pins)
        bar.grid(row=1, column=0, sticky="w", pady=4)
        ttk.Button(bar, text="+ Pin", command=self._add_pin).pack(side="left")
        ttk.Button(bar, text="− Pin", command=self._del_pin).pack(side="left", padx=4)
        ttk.Label(bar, text="Double-click a cell to edit it.", foreground="gray").pack(side="left", padx=8)
        self.tree.bind("<Double-1>", self._edit_cell)
        self.nb.add(pins, text="Pins")

        self._build_package_tab()
        self._build_info_tab()

        prev = ttk.Frame(self.nb, padding=8)
        self.sym_img = ttk.Label(prev, text="(symbol)", anchor="center")
        self.fp_img = ttk.Label(prev, text="(footprint)", anchor="center")
        self.sym_img.pack(side="left", fill="both", expand=True)
        self.fp_img.pack(side="left", fill="both", expand=True)
        self.nb.add(prev, text="Preview")

    def _build_package_tab(self) -> None:
        f = ttk.Frame(self.nb, padding=8)
        self.pkg_vars: dict[str, tk.Variable] = {}
        self.pkg_labels: dict[str, ttk.Label] = {}
        top = [("family", "Family"), ("name", "Name"), ("pin_count", "Pins (no EP/tab)"),
               ("pitch", "Pitch"), ("num_pins_x", "Pins per side X"), ("num_pins_y", "Pins per side Y"),
               ("deleted_pins", "Deleted positions"), ("confidence", "Confidence")]
        for i, (key, label) in enumerate(top):
            lbl = ttk.Label(f, text=label)
            lbl.grid(row=i // 2, column=(i % 2) * 2, sticky="w", padx=(0, 4), pady=2)
            self.pkg_labels[key] = lbl
            var = tk.StringVar()
            self.pkg_vars[key] = var
            if key == "family":
                w = ttk.Combobox(f, textvariable=var, values=get_args(Family), state="readonly", width=18)
            elif key == "confidence":
                w = ttk.Combobox(f, textvariable=var, values=("high", "medium", "low"), state="readonly", width=18)
            else:
                w = ttk.Entry(f, textvariable=var, width=22)
            w.grid(row=i // 2, column=(i % 2) * 2 + 1, sticky="w", pady=2, padx=(0, 24))

        dims = ttk.LabelFrame(f, text="Dimensions (mm)", padding=6)
        dims.grid(row=5, column=0, columnspan=4, sticky="w", pady=(10, 0))
        for j, h in enumerate(("", "min", "nom", "max")):
            ttk.Label(dims, text=h).grid(row=0, column=j)
        self.dim_vars: dict[str, tuple[tk.StringVar, tk.StringVar, tk.StringVar]] = {}
        for i, (key, label) in enumerate(DIM_FIELDS, start=1):
            lbl = ttk.Label(dims, text=label)
            lbl.grid(row=i, column=0, sticky="w", padx=(0, 8))
            self.pkg_labels[key] = lbl
            trio = (tk.StringVar(), tk.StringVar(), tk.StringVar())
            for j, var in enumerate(trio, start=1):
                ttk.Entry(dims, textvariable=var, width=9).grid(row=i, column=j, padx=2, pady=1)
            self.dim_vars[key] = trio

        extra = ttk.Frame(f)
        extra.grid(row=6, column=0, columnspan=4, sticky="w", pady=(8, 0))
        self.has_ep, self.has_tab = tk.BooleanVar(), tk.BooleanVar()
        self.ep_num, self.tab_num = tk.StringVar(), tk.StringVar()
        ttk.Checkbutton(extra, text="Has exposed pad, pin no.", variable=self.has_ep).pack(side="left")
        ttk.Entry(extra, textvariable=self.ep_num, width=6).pack(side="left", padx=(2, 20))
        ttk.Checkbutton(extra, text="Has tab, pin no.", variable=self.has_tab).pack(side="left")
        ttk.Entry(extra, textvariable=self.tab_num, width=6).pack(side="left", padx=2)
        self.nb.add(f, text="Package")

    def _build_info_tab(self) -> None:
        f = ttk.Frame(self.nb, padding=8)
        f.columnconfigure(1, weight=1)
        self.info_vars: dict[str, tk.StringVar] = {}
        fields = [("part_number", "Part number"), ("symbol_name", "Symbol name"),
                  ("manufacturer", "Manufacturer"), ("description", "Description"), ("keywords", "Keywords"),
                  ("datasheet_url", "Datasheet URL"), ("reference", "Reference")]
        for i, (key, label) in enumerate(fields):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="w", pady=1)
            var = tk.StringVar()
            ttk.Entry(f, textvariable=var).grid(row=i, column=1, sticky="ew", pady=1)
            self.info_vars[key] = var
        self.pages_frame = ttk.Frame(f)
        self.pages_frame.grid(row=len(fields), column=0, columnspan=2, sticky="w", pady=6)
        ttk.Label(f, text="Issues and notes").grid(row=len(fields) + 1, column=0, sticky="nw")
        self.issues_box = ScrolledText(f, height=12, font=("Segoe UI", 9), state="disabled")
        self.issues_box.grid(row=len(fields) + 1, column=1, sticky="nsew")
        self.issues_box.tag_configure("error", foreground=RED)
        self.issues_box.tag_configure("warning", foreground="#b26a00")
        f.rowconfigure(len(fields) + 1, weight=1)
        self.nb.add(f, text="Info")

    def _build_actions(self) -> None:
        f = ttk.Frame(self, padding=(8, 0, 8, 8))
        f.pack(fill="x")
        ttk.Button(f, text="Validate", command=self._validate).pack(side="left")
        self.gen_btn = ttk.Button(f, text="Generate symbol + footprint", command=self._generate)
        self.gen_btn.pack(side="left", padx=6)
        self.status = ttk.Label(f, text="Pick a PDF and enter the part number.", foreground="gray")
        self.status.pack(side="left", padx=12)

        u = ttk.Frame(self, padding=(8, 0, 8, 6))
        u.pack(fill="x")
        self.usage_lbl = ttk.Label(u, foreground="gray")
        self.usage_lbl.pack(side="left")
        ttk.Button(u, text="View details (CSV)", command=self._open_usage).pack(side="right")
        self._refresh_usage()

    def _refresh_usage(self) -> None:
        from . import usage
        self.usage_lbl.configure(text="Accumulated usage: " + usage.summary().describe())

    def _open_usage(self) -> None:
        import os
        from . import usage
        if usage.USAGE_FILE.exists():
            os.startfile(usage.USAGE_FILE)  # opens with Excel / the default editor
        else:
            messagebox.showinfo("dsgen", "No extractions recorded yet.")

    # ------------------------------------------------------------------ helpers
    def _log(self, text: str) -> None:
        self.msgs.put(("log", text))

    def _drain_queue(self) -> None:
        try:
            while True:
                kind, payload = self.msgs.get_nowait()
                if kind == "log":
                    self.log.configure(state="normal")
                    self.log.insert("end", payload + "\n")
                    self.log.see("end")
                    self.log.configure(state="disabled")
                elif kind == "call":
                    payload()
        except queue.Empty:
            pass
        self.after(100, self._drain_queue)

    def _in_thread(self, work, done) -> None:
        def runner():
            try:
                result = work()
                self.msgs.put(("call", lambda: done(result, None)))
            except Exception as e:  # noqa: BLE001 - shown to the user
                self._log(traceback.format_exc())
                self.msgs.put(("call", lambda: done(None, e)))
        threading.Thread(target=runner, daemon=True).start()

    def _pick_pdf(self) -> None:
        p = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")])
        if p:
            self.pdf_var.set(p)

    def _pick_out(self) -> None:
        p = filedialog.askdirectory()
        if p:
            self.out_var.set(p)

    # ------------------------------------------------------------------ extraction
    def _extract(self) -> None:
        pdf, part = Path(self.pdf_var.get().strip()), self.part_var.get().strip()
        if not pdf.is_file():
            messagebox.showerror("dsgen", "Pick a valid PDF.")
            return
        if not part:
            messagebox.showerror("dsgen", "The full part number is required: a datasheet usually "
                                          "covers several variants and packages.")
            return
        from .pipeline import extract_component

        self.extract_btn.configure(state="disabled")
        self.status.configure(text="Extracting with Claude… (may take 1-3 minutes)")
        self.nb.select(0)
        self._log(f"== {pdf.name} / {part}")
        model, force = self.model_var.get(), self.force_var.get()
        self._in_thread(lambda: extract_component(pdf, part, model, force, self._log), self._extracted)

    def _extracted(self, result, error) -> None:
        self.extract_btn.configure(state="normal")
        self._refresh_usage()
        if error:
            self.status.configure(text="Extraction error.")
            msg = str(error) if isinstance(error, ExtractionError) else repr(error)
            messagebox.showerror("dsgen", msg[:1500])
            return
        component, issues = result
        if component.status != "ok":
            self.status.configure(text=f"Part number: {component.status}")
            self._choose_candidate(component)
            return
        self._load_component(component, issues)
        n_err = sum(i.severity == "error" for i in issues)
        self.status.configure(text=f"Extraction done: review the data ({n_err} errors).")
        self.nb.select(1)

    def _choose_candidate(self, component: Component) -> None:
        msg = ("That part number was not found in the datasheet." if component.status == "part_not_found"
               else "The part number is ambiguous.")
        if not component.candidates:
            messagebox.showwarning("dsgen", msg + "\n" + "\n".join(component.notes))
            return
        win = tk.Toplevel(self)
        win.title("Pick the part number")
        ttk.Label(win, text=msg + " Candidates in the datasheet:", padding=8).pack()
        lb = tk.Listbox(win, height=min(12, len(component.candidates)), width=40)
        for c in component.candidates:
            lb.insert("end", c)
        lb.pack(padx=8)

        def use():
            if lb.curselection():
                self.part_var.set(lb.get(lb.curselection()[0]))
                win.destroy()
                self._extract()
        ttk.Button(win, text="Use this one and extract", command=use).pack(pady=8)

    def _open_json(self) -> None:
        p = filedialog.askopenfilename(filetypes=[("component.json", "*.json")])
        if not p:
            return
        try:
            component = Component.model_validate_json(Path(p).read_text(encoding="utf-8"))
        except ValidationError as e:
            messagebox.showerror("dsgen", f"Invalid JSON:\n{e}")
            return
        self.out_var.set(str(Path(p).parent))
        self._load_component(component, check(component))
        self.nb.select(1)

    # ------------------------------------------------------------------ form <-> Component
    def _load_component(self, c: Component, issues: list[Issue]) -> None:
        self.component = c
        self.part_var.set(c.part_number)
        self.tree.delete(*self.tree.get_children())
        for p in c.pins:
            self.tree.insert("", "end", values=(p.number, p.name, p.type, p.side, p.unit, p.style))
        for key, var in self.info_vars.items():
            var.set(getattr(c, key) or "")

        pkg = c.package
        for key, var in self.pkg_vars.items():
            value = getattr(pkg, key, "") if pkg else ""
            var.set(", ".join(map(str, value)) if isinstance(value, list) else _fmt(value)
                    if isinstance(value, float) else str(value if value is not None else ""))
        for key, trio in self.dim_vars.items():
            d = self._pkg_dim(pkg, key)
            for var, v in zip(trio, (d.min, d.nom, d.max) if d else (None, None, None)):
                var.set(_fmt(v))
        self.has_ep.set(bool(pkg and pkg.ep))
        self.ep_num.set(pkg.ep.number if pkg and pkg.ep else str((pkg.pin_count if pkg else 0) + 1))
        self.has_tab.set(bool(pkg and pkg.tab))
        self.tab_num.set(pkg.tab.number if pkg and pkg.tab else "")

        for w in self.pages_frame.winfo_children():
            w.destroy()
        ttk.Label(self.pages_frame, text="Open PDF at:").pack(side="left")
        for section, pages in c.source_pages.model_dump().items():
            for page in pages:
                ttk.Button(self.pages_frame, text=f"{section} p.{page}",
                           command=lambda n=page: self._open_page(n)).pack(side="left", padx=2)
        self._show_issues(issues, c)

    @staticmethod
    def _pkg_dim(pkg: Optional[Package], key: str) -> Optional[Dim]:
        if pkg is None:
            return None
        obj = pkg
        for part in key.split("."):
            obj = getattr(obj, part, None)
            if obj is None:
                return None
        return obj

    def _form_component(self) -> Component:
        """Builds the Component from the form (what the user reviewed)."""
        base = self.component or Component(status="ok", part_number=self.part_var.get())
        pins = [Pin(number=str(v[0]), name=str(v[1]), type=v[2], side=v[3], unit=int(v[4] or 1), style=v[5])
                for v in (self.tree.item(i, "values") for i in self.tree.get_children())]

        def dim(key: str) -> Dim:
            return Dim(**dict(zip(("min", "nom", "max"), (_num(v.get()) for v in self.dim_vars[key]))))

        pv = {k: v.get().strip() for k, v in self.pkg_vars.items()}
        package = None
        if pv["family"]:
            package = Package(
                family=pv["family"], name=pv["name"], pin_count=int(pv["pin_count"] or 0),
                pitch=_num(pv["pitch"]), num_pins_x=int(pv["num_pins_x"] or 0),
                num_pins_y=int(pv["num_pins_y"] or 0),
                deleted_pins=[int(x) for x in pv["deleted_pins"].replace(" ", "").split(",") if x],
                body_x=dim("body_x"), body_y=dim("body_y"), overall_x=dim("overall_x"),
                overall_y=dim("overall_y"), body_height=dim("body_height"),
                lead_width=dim("lead_width"), lead_len=dim("lead_len"),
                ep=ExposedPad(number=self.ep_num.get().strip(), x=dim("ep.x"), y=dim("ep.y"))
                if self.has_ep.get() else None,
                tab=Tab(number=self.tab_num.get().strip(), width=dim("tab.width"), length=dim("tab.length"))
                if self.has_tab.get() else None,
                confidence=pv["confidence"] or "medium",
                source_pages=base.package.source_pages if base.package else [],
            )
        info = {k: v.get().strip() for k, v in self.info_vars.items()}
        return base.model_copy(update={**info, "status": "ok", "pins": pins, "package": package})

    # ------------------------------------------------------------------ validation
    def _show_issues(self, issues: list[Issue], c: Component) -> None:
        bad_rows = {int(i.field[5:-1]) for i in issues if i.field.startswith("pins[")}
        for idx, item in enumerate(self.tree.get_children()):
            self.tree.item(item, tags=("bad",) if idx in bad_rows else ())
        bad_fields = {i.field.removeprefix("package.") for i in issues if i.severity == "error"}
        for key, lbl in self.pkg_labels.items():
            hit = any(key == f or f.startswith(key + ".") or key in f.split("/") for f in bad_fields)
            lbl.configure(foreground=RED if hit else "")

        box = self.issues_box
        box.configure(state="normal")
        box.delete("1.0", "end")
        conf = f"Confidence — pins: {c.pins_confidence}"
        if c.package:
            conf += f", package: {c.package.confidence} ({c.package.name})"
        box.insert("end", conf + "\n\n")
        if not issues:
            box.insert("end", "No issues found by the sanity checks.\n")
        for issue in issues:
            box.insert("end", f"• {issue.field}: {issue.message}\n", issue.severity)
        if c.notes:
            box.insert("end", "\nAI notes:\n")
            for n in c.notes:
                box.insert("end", f"• {n}\n")
        box.configure(state="disabled")

    def _validate(self) -> Optional[Component]:
        try:
            c = self._form_component()
        except (ValidationError, ValueError) as e:
            messagebox.showerror("dsgen", f"Invalid data in the form:\n{e}")
            return None
        issues = check(c)
        self._show_issues(issues, c)
        n_err = sum(i.severity == "error" for i in issues)
        self.status.configure(text=f"Validation: {n_err} errors, {len(issues) - n_err} warnings.")
        return c

    def _open_page(self, page: int) -> None:
        pdf = Path(self.pdf_var.get().strip())
        if pdf.is_file():
            webbrowser.open(f"{pdf.resolve().as_uri()}#page={page}")

    # ------------------------------------------------------------------ pin editing
    def _edit_cell(self, event) -> None:
        item, col = self.tree.identify_row(event.y), self.tree.identify_column(event.x)
        if not item or not col:
            return
        idx = int(col[1:]) - 1
        key = PIN_COLUMNS[idx]
        x, y, w, h = self.tree.bbox(item, col)
        values = list(self.tree.item(item, "values"))
        var = tk.StringVar(value=values[idx])
        if key in PIN_CHOICES:
            editor = ttk.Combobox(self.tree, textvariable=var, values=PIN_CHOICES[key], state="readonly")
        else:
            editor = ttk.Entry(self.tree, textvariable=var)
        editor.place(x=x, y=y, width=w, height=h)
        editor.focus_set()

        def commit(_=None):
            values[idx] = var.get()
            self.tree.item(item, values=values)
            editor.destroy()
        editor.bind("<Return>", commit)
        editor.bind("<FocusOut>", commit)
        editor.bind("<<ComboboxSelected>>", commit)
        editor.bind("<Escape>", lambda _: editor.destroy())

    def _add_pin(self) -> None:
        n = len(self.tree.get_children()) + 1
        self.tree.insert("", "end", values=(n, f"P{n}", "passive", "left", 1, "line"))

    def _del_pin(self) -> None:
        for item in self.tree.selection():
            self.tree.delete(item)

    # ------------------------------------------------------------------ generation
    def _generate(self) -> None:
        c = self._validate()
        if c is None:
            return
        errors = [i for i in check(c) if i.severity == "error"]
        if errors and not messagebox.askyesno(
                "dsgen", f"There are {len(errors)} validation errors (see the Info tab). Generate anyway?"):
            self.nb.select(3)
            return
        out = Path(self.out_var.get().strip() or "out")
        lib = self.lib_var.get().strip() or "dsgen"
        use_official = self.official_var.get()
        self.gen_btn.configure(state="disabled")
        self.nb.select(0)
        self._log(f"== Generating into {out}")
        self.component = c
        self._in_thread(lambda: self._generate_work(c, out, lib, use_official), self._generated)

    def _generate_work(self, c: Component, out: Path, lib: str, use_official: bool):
        from .footprint_gen import copy_official
        from .kicad_env import find_kicad
        from .pipeline import generate
        from .preview import footprint_png, symbol_png

        result = generate(c, out, lib, use_official=use_official, log=self._log)
        pngs: list[Optional[Path]] = [None, None]
        kicad = find_kicad()
        if kicad:
            tmp = Path(tempfile.mkdtemp(prefix="dsgen_prev_"))
            try:
                pngs[0] = symbol_png(kicad, result.symbol_lib, c.symbol_name or c.part_number, tmp / "sym.png")
                fp = result.footprint
                if fp:
                    mod = fp.generated_path or copy_official(fp.lib_id, kicad, tmp / "official.pretty")
                    pngs[1] = footprint_png(kicad, mod, tmp / "fp.png")
            except Exception as e:  # noqa: BLE001 - the preview is not critical
                self._log(f"Could not generate the preview: {e}")
        return result, pngs

    def _generated(self, result, error) -> None:
        self.gen_btn.configure(state="normal")
        if error:
            self.status.configure(text="Generation error.")
            messagebox.showerror("dsgen", str(error)[:1500])
            return
        gen, pngs = result
        self._images.clear()
        for label, png, text in ((self.sym_img, pngs[0], "(symbol)"), (self.fp_img, pngs[1], "(footprint)")):
            if png and png.exists():
                img = tk.PhotoImage(file=str(png))
                self._images.append(img)
                label.configure(image=img, text="")
            else:
                label.configure(image="", text=text + "\nno preview")
        fp_txt = gen.footprint.lib_id if gen.footprint else "no footprint"
        self.status.configure(text=f"Done: {gen.symbol_lib.name} → {fp_txt}")
        self._log(f"Add {gen.symbol_lib} and the .pretty folder (if one was generated) to KiCad's "
                  f"library tables.")
        self.nb.select(4)


def run_gui() -> None:
    App().mainloop()
