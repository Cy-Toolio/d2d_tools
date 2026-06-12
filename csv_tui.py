#!/usr/bin/env python3
"""csv_tui.py — Styled TUI for analyzing CSV files.

Usage:
    python csv_tui.py [file.csv]

Install:
    pip install textual

Filter syntax (/ bar):
    age > 30                     numeric comparison
    city = Berlin                exact match (case-insensitive)
    name ~ ali                   substring search
    score >= 80 & city = Rome    AND conditions
    plain text                   full-row text search

Compute syntax (= bar, press Enter to apply):
    col1 + col2 * 0.5 [total]   arithmetic with column names
    round(price * 1.2, 2) [inc] math functions supported
    [name] part is optional      defaults to computed_N
"""

from __future__ import annotations

import csv
import math
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


def _ensure_deps() -> None:
    try:
        import textual  # noqa: F401
    except ImportError:
        print("textual not found — installing…")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "textual"],
                stdout=subprocess.DEVNULL,
            )
            print("Installed. Starting…\n")
        except subprocess.CalledProcessError:
            print(
                "\nAuto-install failed. Run this manually then retry:\n"
                "    pip install textual",
                file=sys.stderr,
            )
            sys.exit(1)

_ensure_deps()

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    DirectoryTree,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    SelectionList,
    Static,
)


# ─────────────────────────────────────────────────────────────────
#  Type inference + stats
# ─────────────────────────────────────────────────────────────────

def _infer_type(values: list[str]) -> str:
    sample = [v for v in values[:300] if v.strip()]
    if not sample:
        return "empty"
    try:
        for v in sample:
            int(v)
        return "int"
    except ValueError:
        pass
    try:
        for v in sample:
            float(v)
        return "float"
    except ValueError:
        pass
    return "str"


def _col_stats(values: list[str], dtype: str) -> dict:
    total = len(values)
    null_count = sum(1 for v in values if not v.strip())
    non_null = [v for v in values if v.strip()]
    unique = len(set(non_null))
    stats: dict = {"total": total, "null": null_count, "unique": unique}

    if dtype in ("int", "float"):
        nums: list[float] = []
        for v in non_null:
            try:
                f = float(v)
                if math.isfinite(f):
                    nums.append(f)
            except (ValueError, OverflowError):
                pass
        if nums:
            stats["min"] = min(nums)
            stats["max"] = max(nums)
            stats["mean"] = sum(nums) / len(nums)
            s = sorted(nums)
            n = len(s)
            stats["median"] = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
            if n > 1:
                m = stats["mean"]
                stats["stdev"] = (sum((x - m) ** 2 for x in nums) / (n - 1)) ** 0.5
    return stats


# ─────────────────────────────────────────────────────────────────
#  CSV data
# ─────────────────────────────────────────────────────────────────

class CsvData:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.headers: list[str] = []
        self.rows: list[list[str]] = []
        self.types: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        with open(self.path, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            try:
                self.headers = next(reader)
            except StopIteration:
                return
            self.rows = list(reader)
        for i, col in enumerate(self.headers):
            vals = [row[i] if i < len(row) else "" for row in self.rows]
            self.types[col] = _infer_type(vals)

    def col_values(self, col: str) -> list[str]:
        idx = self.headers.index(col)
        return [row[idx] if idx < len(row) else "" for row in self.rows]

    def stats(self, col: str) -> dict:
        return _col_stats(self.col_values(col), self.types[col])

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.rows), len(self.headers)


# ─────────────────────────────────────────────────────────────────
#  Filter engine
#  Syntax:  col op val  [& col op val ...]
#  Ops:     = != > < >= <= ~(contains)
#  Plain text (no operator) → full-row substring search
# ─────────────────────────────────────────────────────────────────

def _parse_condition(
    expr: str, headers: list[str]
) -> Optional[tuple[str, str, str]]:
    """Parse 'col op val' → (matched_header, op, val) or None."""
    m = re.match(r'^(.+?)\s*(>=|<=|!=|~|=|>|<)\s*(.*)$', expr.strip())
    if not m:
        return None
    col_raw, op, val = m.group(1).strip(), m.group(2), m.group(3).strip()
    # Match against known headers (case-insensitive, longest first)
    for h in sorted(headers, key=len, reverse=True):
        if h.lower() == col_raw.lower():
            return h, op, val
    return None


def _col_pred(idx: int, op: str, val: str) -> Callable[[list[str]], bool]:
    def pred(row: list[str]) -> bool:
        cell = row[idx] if idx < len(row) else ""
        if op == "~":
            return val.lower() in cell.lower()
        if op in ("=", "!="):
            try:
                a, b = float(cell), float(val)
                return (a == b) if op == "=" else (a != b)
            except ValueError:
                eq = cell.lower() == val.lower()
                return eq if op == "=" else not eq
        try:
            a, b = float(cell), float(val)
        except ValueError:
            a, b = cell, val  # type: ignore[assignment]
        return {">=": a >= b, "<=": a <= b, ">": a > b, "<": a < b}[op]
    return pred


def build_filter(expr: str, headers: list[str]) -> Callable[[list[str]], bool]:
    """Compile a filter expression into a row → bool predicate."""
    if not expr.strip():
        return lambda _: True

    preds: list[Callable[[list[str]], bool]] = []
    for term in [t.strip() for t in expr.split("&") if t.strip()]:
        parsed = _parse_condition(term, headers)
        if parsed:
            col, op, val = parsed
            preds.append(_col_pred(headers.index(col), op, val))
        else:
            t = term.lower()
            preds.append(lambda row, t=t: any(t in v.lower() for v in row))

    return lambda row: all(p(row) for p in preds)


# ─────────────────────────────────────────────────────────────────
#  Computed columns
#  Syntax:  expression  [column_name]
#  Column names are available as variables; math functions built in
# ─────────────────────────────────────────────────────────────────

_SAFE_GLOBALS: dict = {
    "__builtins__": {},
    # builtins
    "abs": abs, "round": round, "min": min, "max": max,
    "int": int, "float": float, "str": str, "len": len, "pow": pow,
    # math
    "sqrt": math.sqrt, "exp": math.exp, "log": math.log, "log10": math.log10,
    "floor": math.floor, "ceil": math.ceil,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "pi": math.pi, "e": math.e,
}


def _to_varname(name: str) -> str:
    safe = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    return ('c_' + safe) if (not safe or safe[0].isdigit()) else safe


def _make_safe_formula(
    formula: str, headers: list[str]
) -> tuple[str, dict[str, str]]:
    """Rewrite formula replacing column names with safe Python identifiers."""
    col_map = {col: _to_varname(col) for col in headers}
    safe = formula
    for col in sorted(headers, key=len, reverse=True):
        safe_name = col_map[col]
        if col != safe_name:
            safe = re.sub(r'\b' + re.escape(col) + r'\b', safe_name, safe)
    return safe, col_map


def eval_computed(
    safe_formula: str,
    col_map: dict[str, str],
    row: list[str],
    headers: list[str],
) -> str:
    ns = dict(_SAFE_GLOBALS)
    for col, safe_name in col_map.items():
        idx = next((i for i, h in enumerate(headers) if h == col), -1)
        raw = row[idx] if 0 <= idx < len(row) else ""
        try:
            ns[safe_name] = float(raw) if raw.strip() else 0.0
        except ValueError:
            ns[safe_name] = raw
    try:
        result = eval(safe_formula, {"__builtins__": {}}, ns)  # noqa: S307
        if isinstance(result, float):
            if math.isnan(result):
                return "NaN"
            if math.isinf(result):
                return "∞" if result > 0 else "-∞"
            if result.is_integer() and abs(result) < 1e15:
                return str(int(result))
            return f"{result:.6g}"
        return str(result)
    except ZeroDivisionError:
        return "÷0"
    except Exception:
        return "ERR"


def parse_compute_input(raw: str) -> tuple[str, str]:
    """Split 'formula [name]' → (formula, name). Name is '' if absent."""
    m = re.match(r'^(.*?)\[([^\]]+)\]\s*$', raw.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return raw.strip(), ""


@dataclass
class ComputedCol:
    name: str
    formula: str   # the expression part only (no [name])
    raw: str       # full input as the user typed it


# ─────────────────────────────────────────────────────────────────
#  Distinct-value counts
# ─────────────────────────────────────────────────────────────────

MAX_DISTINCT = 5_000
_SORT_CYCLE = ["count_desc", "value_asc", "count_asc"]
_SORT_LABEL = {"count_desc": "count ↓", "count_asc": "count ↑", "value_asc": "value ↑"}


def _distinct_counts(
    all_headers: list[str],
    all_rows: list[list[str]],
    cols: list[str],
    sort_mode: str = "count_desc",
) -> list[tuple[tuple[str, ...], int]]:
    """Group all_rows by cols and return sorted (key_tuple, count) pairs."""
    indices = [all_headers.index(c) for c in cols if c in all_headers]
    counts: Counter = Counter()
    for row in all_rows:
        key = tuple(row[i] if i < len(row) else "" for i in indices)
        counts[key] += 1
    items = list(counts.items())
    if sort_mode == "count_desc":
        items.sort(key=lambda x: -x[1])
    elif sort_mode == "count_asc":
        items.sort(key=lambda x: x[1])
    else:
        items.sort(key=lambda x: x[0])
    return items


DISTINCT_CSS = """
DistinctModal { align: center middle; }

#dv-dialog {
    width: 92%;
    height: 88%;
    border: double $accent;
    background: #0d1117;
}
#dv-title {
    height: 1;
    padding: 0 2;
    background: #21262d;
    color: #58a6ff;
    text-style: bold;
}
#dv-body { height: 1fr; }

#dv-cols {
    width: 30;
    border-right: solid #30363d;
    background: #161b22;
}
#dv-cols-header {
    height: 1;
    padding: 0 1;
    background: #21262d;
    color: #58a6ff;
    text-style: bold;
}
#dv-col-select {
    height: 1fr;
    background: #161b22;
}

#dv-results { width: 1fr; }
#dv-results-header {
    height: 1;
    padding: 0 1;
    background: #21262d;
    color: #58a6ff;
    text-style: bold;
}
#dv-table {
    height: 1fr;
    background: #0d1117;
    scrollbar-color: #30363d #0d1117;
    scrollbar-size: 1 1;
}
DataTable > .datatable--header { background: #21262d; color: #79c0ff; text-style: bold; }
DataTable > .datatable--cursor { background: #1f3050; color: #e6edf3; }
DataTable > .datatable--even-row { background: #0d1117; color: #c9d1d9; }
DataTable > .datatable--odd-row  { background: #161b22; color: #c9d1d9; }

#dv-status {
    height: 1;
    padding: 0 2;
    background: #161b22;
    color: #8b949e;
}
"""


class DistinctModal(ModalScreen):
    CSS = DISTINCT_CSS
    BINDINGS = [
        Binding("escape", "dismiss(None)", "Close"),
        Binding("s",      "cycle_sort",    "Cycle sort"),
    ]

    def __init__(
        self,
        all_headers: list[str],
        all_rows: list[list[str]],
        initial_col: Optional[str],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._all_headers = all_headers
        self._all_rows = all_rows
        self._initial_col = initial_col
        self._sort_mode = "count_desc"

    def compose(self) -> ComposeResult:
        options = [
            (col[:26], col, col == self._initial_col)
            for col in self._all_headers
        ]
        with Vertical(id="dv-dialog"):
            yield Static("Distinct Values", id="dv-title")
            with Horizontal(id="dv-body"):
                with Vertical(id="dv-cols"):
                    yield Static("Group by  (space to toggle)", id="dv-cols-header")
                    yield SelectionList(*options, id="dv-col-select")
                with Vertical(id="dv-results"):
                    yield Static("Results", id="dv-results-header")
                    yield DataTable(id="dv-table", cursor_type="row", zebra_stripes=True)
            yield Static("", id="dv-status")

    def on_mount(self) -> None:
        self._refresh()

    @on(SelectionList.SelectedChanged)
    def _sel_changed(self) -> None:
        self._refresh()

    def action_cycle_sort(self) -> None:
        idx = _SORT_CYCLE.index(self._sort_mode)
        self._sort_mode = _SORT_CYCLE[(idx + 1) % len(_SORT_CYCLE)]
        self._refresh()

    def _refresh(self) -> None:
        sel = self.query_one("#dv-col-select", SelectionList)
        cols = list(sel.selected)
        table = self.query_one("#dv-table", DataTable)
        status = self.query_one("#dv-status", Static)
        table.clear(columns=True)

        if not cols:
            status.update("[dim]Select at least one column from the left panel[/]")
            return

        items = _distinct_counts(self._all_headers, self._all_rows, cols, self._sort_mode)
        total_rows = len(self._all_rows)
        distinct_n = len(items)
        shown = items[:MAX_DISTINCT]

        for col in cols:
            table.add_column(col, key=col)
        table.add_column("count", key="__count__")
        table.add_column("%",     key="__pct__")

        for key, count in shown:
            pct = count / total_rows * 100 if total_rows else 0
            table.add_row(*key, f"{count:,}", f"{pct:.1f}%")

        cap = (
            f"  [dim](showing {MAX_DISTINCT:,} of {distinct_n:,})[/]"
            if distinct_n > MAX_DISTINCT else ""
        )
        hdr = f"Results  [dim]{distinct_n:,} distinct from {total_rows:,} rows[/]"
        self.query_one("#dv-results-header", Static).update(hdr)
        status.update(
            f"  [#58a6ff]{distinct_n:,}[/] distinct  "
            f"[dim]sorted by[/] [yellow]{_SORT_LABEL[self._sort_mode]}[/]  "
            f"[dim][s] cycle  [Esc] close[/]" + cap
        )


# ─────────────────────────────────────────────────────────────────
#  Compute legend modal
# ─────────────────────────────────────────────────────────────────

LEGEND_CSS = """
ComputeLegendModal { align: center middle; }
#legend-dialog {
    width: 68;
    height: auto;
    border: double #f0883e;
    background: #0d1117;
    padding: 1 2;
}
#legend-title {
    height: 1;
    text-style: bold;
    color: #f0883e;
    margin-bottom: 1;
}
.legend-heading {
    height: 1;
    text-style: bold;
    color: #58a6ff;
    margin-top: 1;
}
.legend-row { height: 1; color: #c9d1d9; }
#legend-footer {
    height: 1;
    color: #8b949e;
    margin-top: 1;
}
"""

_LEGEND_SECTIONS = [
    ("Syntax", [
        ("[#f0883e]expr [col_name][/]   — add a column named col_name",
         "[dim]e.g.[/]  [#e6edf3]price * 1.2 [inflated][/]"),
        ("[dim][col_name] is optional — defaults to computed_1, computed_2 …[/]",
         ""),
    ]),
    ("Operators", [
        ("[#e6edf3]+   -   *   /[/]   arithmetic",
         "[#e6edf3]//   %[/]   floor-div  mod"),
        ("[#e6edf3]**[/]   exponent  [dim]e.g.[/] [#e6edf3]x ** 2[/]",
         ""),
    ]),
    ("Built-ins", [
        ("[#7ee787]abs[/](x)   [#7ee787]round[/](x, n)   [#7ee787]min[/](a, b)   [#7ee787]max[/](a, b)",
         "[#7ee787]int[/](x)   [#7ee787]float[/](x)   [#7ee787]str[/](x)   [#7ee787]len[/](x)   [#7ee787]pow[/](x, y)"),
    ]),
    ("Math", [
        ("[#d2a8ff]sqrt[/](x)   [#d2a8ff]exp[/](x)   [#d2a8ff]log[/](x)   [#d2a8ff]log10[/](x)",
         "[#d2a8ff]floor[/](x)   [#d2a8ff]ceil[/](x)"),
        ("[#d2a8ff]sin[/](x)   [#d2a8ff]cos[/](x)   [#d2a8ff]tan[/](x)",
         "[#d2a8ff]pi[/]   [#d2a8ff]e[/]"),
    ]),
    ("Special results", [
        ("[#8b949e]NaN[/]  not-a-number    [#8b949e]∞[/]  infinity",
         "[#8b949e]÷0[/]  division by zero    [#8b949e]ERR[/]  formula error"),
    ]),
]


class ComputeLegendModal(ModalScreen):
    CSS = LEGEND_CSS
    BINDINGS = [Binding("escape", "dismiss(None)", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(id="legend-dialog"):
            yield Static("Compute Reference", id="legend-title")
            for heading, rows in _LEGEND_SECTIONS:
                yield Static(heading, classes="legend-heading")
                for left, right in rows:
                    if right:
                        yield Static(f"  {left}    {right}", classes="legend-row")
                    elif left:
                        yield Static(f"  {left}", classes="legend-row")
            yield Static("[dim][Esc] close[/]", id="legend-footer")


# ─────────────────────────────────────────────────────────────────
#  File-picker modal
# ─────────────────────────────────────────────────────────────────

PICKER_CSS = """
FilePicker { align: center middle; }
#picker-dialog {
    width: 72; height: 38;
    border: double $accent;
    background: $surface;
    padding: 1 2;
}
#picker-title   { text-style: bold; color: $accent; height: 1; margin-bottom: 1; }
#picker-drives  { height: 3; margin-bottom: 1; }
.drive-btn      { min-width: 6; margin-right: 1; }
#picker-tree    { height: 16; border: solid $primary-darken-2; margin-bottom: 1; }
#picker-buttons { align: right middle; height: 3; }
"""


def _windows_drives() -> list[str]:
    """Return available drive root paths on Windows (e.g. ['C:\\', 'D:\\'])."""
    if sys.platform != "win32":
        return []
    import string
    return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]


class FilePicker(ModalScreen[Optional[Path]]):
    CSS = PICKER_CSS
    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def compose(self) -> ComposeResult:
        drives = _windows_drives()
        with Vertical(id="picker-dialog"):
            yield Label("Open CSV File", id="picker-title")
            yield Input(placeholder="Type or paste a file path…", id="picker-input")
            if drives:
                with Horizontal(id="picker-drives"):
                    for drive in drives:
                        yield Button(drive, name=drive, classes="drive-btn")
            yield DirectoryTree(str(Path(Path.home().anchor)), id="picker-tree")
            with Horizontal(id="picker-buttons"):
                yield Button("Cancel", variant="default", id="cancel-btn")
                yield Button("Open",   variant="primary",  id="open-btn")

    @on(Button.Pressed, ".drive-btn")
    def _drive_pressed(self, event: Button.Pressed) -> None:
        drive = event.button.name  # e.g. "C:\\"
        self.query_one("#picker-tree", DirectoryTree).path = Path(drive)
        self.query_one("#picker-input", Input).value = drive

    @on(DirectoryTree.FileSelected)
    def _tree_selected(self, event: DirectoryTree.FileSelected) -> None:
        if str(event.path).lower().endswith(".csv"):
            self.query_one("#picker-input", Input).value = str(event.path)

    @on(Button.Pressed, "#open-btn")
    def _do_open(self) -> None:
        raw = self.query_one("#picker-input", Input).value.strip()
        if raw:
            p = Path(raw)
            if p.is_file() and p.suffix.lower() == ".csv":
                self.dismiss(p)
            else:
                self.notify("Not a valid CSV file", severity="warning")

    @on(Button.Pressed, "#cancel-btn")
    def _do_cancel(self) -> None:
        self.dismiss(None)


# ─────────────────────────────────────────────────────────────────
#  Save / Export modal
# ─────────────────────────────────────────────────────────────────

SAVE_CSS = """
SaveExportModal { align: center middle; }
#se-dialog {
    width: 74;
    height: 42;
    border: double #3fb950;
    background: #0d1117;
}
#se-title {
    height: 1;
    padding: 0 2;
    background: #0f2318;
    color: #3fb950;
    text-style: bold;
}
#se-info {
    height: 1;
    padding: 0 2;
    color: #8b949e;
}
#se-input {
    height: 3;
    margin: 0 1;
    background: #0d1117;
    color: #c9d1d9;
    border: tall #30363d;
}
#se-input:focus { border: tall #3fb950; }
#se-drives { height: 3; padding: 0 1; }
.se-drive-btn { min-width: 6; margin-right: 1; }
#se-tree { height: 14; margin: 0 1; border: solid #30363d; }
#se-opts { height: 3; padding: 0 1; align: left middle; }
.se-opt-btn { min-width: 24; margin-right: 2; }
#se-buttons { height: 3; padding: 0 1; align: right middle; }
"""


@dataclass
class SaveOptions:
    path: Path
    filtered_only: bool
    include_computed: bool


class SaveExportModal(ModalScreen):
    CSS = SAVE_CSS
    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(
        self,
        current_path: Optional[Path],
        filtered_rows: int,
        total_rows: int,
        has_computed: bool,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._current_path = current_path
        self._filtered_rows = filtered_rows
        self._total_rows = total_rows
        self._has_computed = has_computed
        self._filtered_only = filtered_rows < total_rows
        self._include_computed = has_computed

    def compose(self) -> ComposeResult:
        drives = _windows_drives()
        start_dir = (
            str(self._current_path.parent)
            if self._current_path else str(Path.home())
        )
        info = (
            f"  Source: {self._current_path}"
            if self._current_path else "  No file loaded"
        )
        with Vertical(id="se-dialog"):
            yield Static("Save / Export", id="se-title")
            yield Static(info, id="se-info")
            yield Input(
                value=str(self._current_path) if self._current_path else "",
                placeholder="Target file path (adds .csv if needed)…",
                id="se-input",
            )
            if drives:
                with Horizontal(id="se-drives"):
                    for drive in drives:
                        yield Button(drive, name=drive, classes="se-drive-btn")
            yield DirectoryTree(start_dir, id="se-tree")
            with Horizontal(id="se-opts"):
                yield Button(
                    self._filtered_label(),
                    id="opt-filtered",
                    classes="se-opt-btn",
                    variant="primary" if self._filtered_only else "default",
                )
                if self._has_computed:
                    yield Button(
                        self._computed_label(),
                        id="opt-computed",
                        classes="se-opt-btn",
                        variant="primary" if self._include_computed else "default",
                    )
            with Horizontal(id="se-buttons"):
                yield Button("Cancel", variant="default", id="se-cancel")
                yield Button("Save", variant="success", id="se-save")

    def _filtered_label(self) -> str:
        return (
            f"Filtered  ({self._filtered_rows:,} rows)"
            if self._filtered_only
            else f"All rows  ({self._total_rows:,})"
        )

    def _computed_label(self) -> str:
        return "✓ Computed cols" if self._include_computed else "✗ Computed cols"

    @on(Button.Pressed, ".se-drive-btn")
    def _drive_pressed(self, event: Button.Pressed) -> None:
        drive = event.button.name
        self.query_one("#se-tree", DirectoryTree).path = Path(drive)
        self.query_one("#se-input", Input).value = drive

    @on(DirectoryTree.FileSelected)
    def _tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        self.query_one("#se-input", Input).value = str(event.path)

    @on(Button.Pressed, "#opt-filtered")
    def _toggle_filtered(self) -> None:
        self._filtered_only = not self._filtered_only
        btn = self.query_one("#opt-filtered", Button)
        btn.label = self._filtered_label()
        btn.variant = "primary" if self._filtered_only else "default"

    @on(Button.Pressed, "#opt-computed")
    def _toggle_computed(self) -> None:
        self._include_computed = not self._include_computed
        btn = self.query_one("#opt-computed", Button)
        btn.label = self._computed_label()
        btn.variant = "primary" if self._include_computed else "default"

    @on(Button.Pressed, "#se-save")
    def _do_save(self) -> None:
        raw = self.query_one("#se-input", Input).value.strip()
        if not raw:
            self.notify("Enter a target file path", severity="warning")
            return
        p = Path(raw)
        if p.suffix.lower() != ".csv":
            p = p.with_suffix(".csv")
        self.dismiss(SaveOptions(p, self._filtered_only, self._include_computed))

    @on(Button.Pressed, "#se-cancel")
    def _do_cancel(self) -> None:
        self.dismiss(None)


# ─────────────────────────────────────────────────────────────────
#  Main app
# ─────────────────────────────────────────────────────────────────

APP_CSS = """
Screen { background: #0d1117; }

Header { background: #161b22; color: #58a6ff; text-style: bold; height: 1; }
Footer { background: #161b22; color: #8b949e; height: 1; }

#body { height: 1fr; }

/* ── column panel ── */
#col-panel {
    width: 26; min-width: 18;
    border-right: solid #30363d;
    background: #161b22;
}
#col-header {
    height: 1; padding: 0 1;
    background: #21262d; color: #58a6ff; text-style: bold;
}
#col-count {
    height: 1; padding: 0 1;
    background: #161b22; color: #8b949e;
    border-bottom: solid #30363d;
}
#col-list { height: 1fr; background: #161b22; }

ListView > ListItem {
    padding: 0 1; background: #161b22; color: #c9d1d9;
}
ListView > ListItem.--highlight { background: #1f3050; color: #e6edf3; }
ListView > ListItem:hover        { background: #1c2333; }
ListView > ListItem.computed.--highlight { background: #2d1c09; }

/* ── data panel ── */
#data-panel { width: 1fr; }

#data-header {
    height: 1; padding: 0 1;
    background: #21262d; color: #58a6ff; text-style: bold;
}

/* filter bar — blue accent on focus */
#filter-input  { height: 3; background: #0d1117; color: #c9d1d9; border: tall #30363d; }
#filter-input:focus  { border: tall #58a6ff; }

/* compute bar — orange accent on focus */
#compute-input { height: 3; background: #0d1117; color: #c9d1d9; border: tall #30363d; }
#compute-input:focus { border: tall #f0883e; }

#data-table {
    height: 1fr; background: #0d1117;
    scrollbar-color: #30363d #0d1117; scrollbar-size: 1 1;
}
DataTable > .datatable--header { background: #21262d; color: #79c0ff; text-style: bold; }
DataTable > .datatable--cursor { background: #1f3050; color: #e6edf3; }
DataTable > .datatable--even-row { background: #0d1117; color: #c9d1d9; }
DataTable > .datatable--odd-row  { background: #161b22; color: #c9d1d9; }

/* ── stats panel ── */
#stats-panel {
    height: 6; border-top: solid #30363d;
    padding: 0 2; background: #0d1117; color: #c9d1d9;
}
"""

TYPE_ICONS = {
    "int":      ("# ", "#79c0ff"),
    "float":    ("~ ", "#d2a8ff"),
    "str":      ("A ", "#7ee787"),
    "empty":    ("∅ ", "#8b949e"),
    "computed": ("ƒ ", "#f0883e"),
}
MAX_ROWS = 10_000


class CsvTui(App[None]):
    TITLE = "CSV Analyzer"
    CSS = APP_CSS
    BINDINGS = [
        Binding("o",      "open_file",       "Open"),
        Binding("r",      "reload",          "Reload"),
        Binding("/",      "focus_filter",    "Filter"),
        Binding("=",      "focus_compute",   "Compute"),
        Binding("question_mark", "compute_help", "Compute Help"),
        Binding("v",      "distinct_values", "Distinct"),
        Binding("s",      "save_export",     "Save/Export"),
        Binding("d",      "delete_col",      "Del Computed"),
        Binding("pageup",   "page_up",   "Pg↑", show=False),
        Binding("pagedown", "page_down", "Pg↓", show=False),
        Binding("escape", "escape_input",    "Back", show=False),
        Binding("q",      "quit",            "Quit"),
    ]

    _data: Optional[CsvData]
    _computed: list[ComputedCol]
    _comp_counter: int
    _filter_timer: Optional[object]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._data = None
        self._computed = []
        self._comp_counter = 0
        self._filter_timer = None

    # ── composition ──────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="col-panel"):
                yield Static("Columns", id="col-header")
                yield Static("no file loaded", id="col-count")
                yield ListView(id="col-list")
            with Vertical(id="data-panel"):
                yield Static("Data", id="data-header")
                yield Input(
                    placeholder="  [/] filter:  age > 30  &  city = Berlin  &  name ~ ali",
                    id="filter-input",
                )
                yield Input(
                    placeholder="  [=] compute:  col1 + 62.5 * (col6 + 4)  [new_col]  — press Enter   [?] for help",
                    id="compute-input",
                )
                yield DataTable(id="data-table", cursor_type="row", zebra_stripes=True)
        yield Static(
            "[dim]Press [bold white]o[/] to open a CSV file[/]",
            id="stats-panel",
        )
        yield Footer()

    def on_mount(self) -> None:
        if len(sys.argv) > 1:
            p = Path(sys.argv[1])
            if p.is_file() and p.suffix.lower() == ".csv":
                self.load_csv(p)

    # ── actions ──────────────────────────────────────────────────

    def action_page_up(self) -> None:
        self.query_one("#data-table", DataTable).action_scroll_page_up()

    def action_page_down(self) -> None:
        self.query_one("#data-table", DataTable).action_scroll_page_down()

    def action_open_file(self) -> None:
        self.push_screen(FilePicker(), self._file_picked)

    def action_reload(self) -> None:
        if self._data:
            self.load_csv(self._data.path)

    def action_focus_filter(self) -> None:
        self.query_one("#filter-input", Input).focus()

    def action_focus_compute(self) -> None:
        self.query_one("#compute-input", Input).focus()

    def action_compute_help(self) -> None:
        self.push_screen(ComputeLegendModal())

    def action_escape_input(self) -> None:
        fi = self.query_one("#filter-input", Input)
        ci = self.query_one("#compute-input", Input)
        if fi.has_focus:
            if fi.value:
                fi.value = ""
                self._refresh_table()
            else:
                self.query_one("#data-table", DataTable).focus()
        elif ci.has_focus:
            ci.value = ""
            self.query_one("#data-table", DataTable).focus()

    def action_delete_col(self) -> None:
        lst = self.query_one("#col-list", ListView)
        child = lst.highlighted_child
        if not child or not child.name:
            return
        comp = next((c for c in self._computed if c.name == child.name), None)
        if comp:
            self._computed.remove(comp)
            self._populate_col_list()
            self._refresh_table(self.query_one("#filter-input", Input).value)
            self.notify(f"Removed computed column '{comp.name}'", timeout=2)
        else:
            self.notify(
                "Only computed columns (ƒ) can be deleted — select one first",
                severity="warning", timeout=3,
            )

    def action_save_export(self) -> None:
        if not self._data:
            self.notify("No file loaded", severity="warning")
            return
        fi = self.query_one("#filter-input", Input)
        pred = build_filter(fi.value, self._data.headers)
        filtered_rows = sum(1 for r in self._data.rows if pred(r))
        self.push_screen(
            SaveExportModal(
                current_path=self._data.path,
                filtered_rows=filtered_rows,
                total_rows=len(self._data.rows),
                has_computed=bool(self._computed),
            ),
            self._do_save_export,
        )

    def _do_save_export(self, opts: Optional[SaveOptions]) -> None:
        if not opts or not self._data:
            return
        fi = self.query_one("#filter-input", Input)
        pred = build_filter(fi.value, self._data.headers)

        if opts.include_computed and self._computed:
            export_headers = self._data.headers + [cc.name for cc in self._computed]
            safe_formulas = [
                _make_safe_formula(cc.formula, self._data.headers)
                for cc in self._computed
            ]
        else:
            export_headers = list(self._data.headers)
            safe_formulas = []

        source_rows = (
            [r for r in self._data.rows if pred(r)]
            if opts.filtered_only
            else self._data.rows
        )
        ncols = len(self._data.headers)

        try:
            opts.path.parent.mkdir(parents=True, exist_ok=True)
            with open(opts.path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(export_headers)
                for row in source_rows:
                    padded = (row + [""] * ncols)[:ncols]
                    if safe_formulas:
                        extra = [
                            eval_computed(sf, cm, padded, self._data.headers)
                            for sf, cm in safe_formulas
                        ]
                        writer.writerow(padded + extra)
                    else:
                        writer.writerow(padded)
            self.notify(
                f"Saved {len(source_rows):,} rows → {opts.path.name}",
                timeout=4,
            )
        except Exception as exc:
            self.notify(f"Save failed: {exc}", severity="error", timeout=8)

    def action_distinct_values(self) -> None:
        if not self._data:
            self.notify("No file loaded", severity="warning")
            return

        # Use the currently highlighted column as the default selection
        lst = self.query_one("#col-list", ListView)
        child = lst.highlighted_child
        initial_col = child.name if child and child.name else (
            self._data.headers[0] if self._data.headers else None
        )

        # Build full rows (original + computed) once
        all_headers = self._data.headers + [cc.name for cc in self._computed]
        safe_formulas = [
            _make_safe_formula(cc.formula, self._data.headers)
            for cc in self._computed
        ]
        ncols = len(self._data.headers)
        all_rows: list[list[str]] = []
        for row in self._data.rows:
            padded = (row + [""] * ncols)[:ncols]
            extra = [
                eval_computed(sf, cm, padded, self._data.headers)
                for sf, cm in safe_formulas
            ]
            all_rows.append(padded + extra)

        self.push_screen(DistinctModal(all_headers, all_rows, initial_col))

    # ── event handlers ────────────────────────────────────────────

    def _file_picked(self, path: Optional[Path]) -> None:
        if path:
            self.load_csv(path)

    @on(Input.Changed, "#filter-input")
    def _filter_changed(self, event: Input.Changed) -> None:
        if self._filter_timer is not None:
            self._filter_timer.stop()
            self._filter_timer = None
        if not event.value:
            self._refresh_table("")
        else:
            val = event.value
            self._filter_timer = self.set_timer(0.3, lambda: self._refresh_table(val))

    @on(Input.Submitted, "#compute-input")
    def _compute_submitted(self, event: Input.Submitted) -> None:
        if not self._data:
            self.notify("No file loaded", severity="warning")
            return
        raw = event.value.strip()
        if not raw:
            return

        formula, name = parse_compute_input(raw)
        if not formula:
            self.notify("Empty formula", severity="warning")
            return
        if not name:
            self._comp_counter += 1
            name = f"computed_{self._comp_counter}"

        taken = set(self._data.headers) | {c.name for c in self._computed}
        if name in taken:
            self.notify(f"'{name}' already exists — choose another name", severity="warning")
            return

        # Validate against first row before committing
        if self._data.rows:
            sf, cm = _make_safe_formula(formula, self._data.headers)
            test = eval_computed(sf, cm, self._data.rows[0], self._data.headers)
            if test == "ERR":
                self.notify(
                    "Formula error — check column names and syntax",
                    severity="error", timeout=5,
                )
                return

        self._computed.append(ComputedCol(name, formula, raw))
        self.query_one("#compute-input", Input).value = ""
        self._populate_col_list()
        self._refresh_table(self.query_one("#filter-input", Input).value)
        self.notify(f"Added computed column '{name}'", timeout=2)

    @on(ListView.Selected)
    def _col_selected(self, event: ListView.Selected) -> None:
        if event.item.name:
            self._show_col_stats(event.item.name)

    # ── core ──────────────────────────────────────────────────────

    def load_csv(self, path: Path) -> None:
        self.notify(f"Loading {path.name}…", timeout=2)
        try:
            data = CsvData(path)
        except Exception as exc:
            self.notify(f"Error: {exc}", severity="error", timeout=8)
            return
        self._data = data
        self._computed.clear()
        self._comp_counter = 0
        self.title = f"CSV Analyzer — {path.name}"
        self.sub_title = f"{data.shape[0]:,} rows  ×  {data.shape[1]} cols"
        self._populate_col_list()
        self._refresh_table()
        self.query_one("#stats-panel", Static).update(
            "[dim]Select a column to view statistics[/]"
        )

    def _populate_col_list(self) -> None:
        lst = self.query_one("#col-list", ListView)
        lst.clear()
        if not self._data:
            return

        # Type count summary badge
        tc: dict[str, int] = {}
        for t in self._data.types.values():
            tc[t] = tc.get(t, 0) + 1
        parts = []
        for dtype, sym in [("int", "#"), ("float", "~"), ("str", "A")]:
            if tc.get(dtype, 0):
                _, color = TYPE_ICONS[dtype]
                parts.append(f"[{color}]{sym}[/]{tc[dtype]}")
        if self._computed:
            _, color = TYPE_ICONS["computed"]
            parts.append(f"[{color}]ƒ[/]{len(self._computed)}")
        self.query_one("#col-count", Static).update("  " + "  ".join(parts))

        # Regular columns
        for col in self._data.headers:
            dtype = self._data.types[col]
            icon, color = TYPE_ICONS.get(dtype, ("? ", "#8b949e"))
            label = f"[{color}]{icon}[/]{col[:20]}" + ("…" if len(col) > 20 else "")
            lst.append(ListItem(Label(label), name=col))

        # Computed columns
        for cc in self._computed:
            _, color = TYPE_ICONS["computed"]
            label = f"[{color}]ƒ [/]{cc.name[:20]}" + ("…" if len(cc.name) > 20 else "")
            lst.append(ListItem(Label(label), name=cc.name, classes="computed"))

    def _refresh_table(self, filter_text: str = "") -> None:
        table = self.query_one("#data-table", DataTable)
        table.clear(columns=True)
        if not self._data:
            return

        all_cols = self._data.headers + [cc.name for cc in self._computed]
        for col in all_cols:
            table.add_column(col, key=col)

        # Pre-compile safe formulas once per refresh
        safe_formulas = [
            _make_safe_formula(cc.formula, self._data.headers)
            for cc in self._computed
        ]

        pred = build_filter(filter_text, self._data.headers)
        rows = [r for r in self._data.rows if pred(r)]
        matched = len(rows)
        shown = min(matched, MAX_ROWS)
        ncols = len(self._data.headers)

        for row in rows[:shown]:
            padded = (row + [""] * ncols)[:ncols]
            extra = [
                eval_computed(sf, cm, padded, self._data.headers)
                for sf, cm in safe_formulas
            ]
            table.add_row(*(padded + extra))

        total = len(self._data.rows)
        if filter_text:
            hdr = (
                f"Data  [dim]{shown:,} shown[/]  "
                f"[yellow]{matched:,} match[/]  [dim]of {total:,}[/]"
            )
        else:
            hdr = f"Data  [dim]{shown:,} of {total:,} rows[/]"
        if matched > MAX_ROWS:
            hdr += f"  [dim](capped at {MAX_ROWS:,})[/]"
        self.query_one("#data-header", Static).update(hdr)

    def _show_col_stats(self, col: str) -> None:
        if not self._data:
            return

        comp = next((c for c in self._computed if c.name == col), None)
        if comp:
            sf, cm = _make_safe_formula(comp.formula, self._data.headers)
            values = [
                eval_computed(sf, cm, row, self._data.headers)
                for row in self._data.rows
            ]
            dtype = _infer_type(values)
            stats = _col_stats(values, dtype)
            icon, color = TYPE_ICONS["computed"]
            formula_line = f"  [dim]ƒ[/] [#f0883e]{comp.formula}[/]"
        elif col in self._data.headers:
            dtype = self._data.types[col]
            stats = self._data.stats(col)
            icon, color = TYPE_ICONS.get(dtype, ("? ", "#8b949e"))
            formula_line = ""
        else:
            return

        pct_null = (stats["null"] / stats["total"] * 100) if stats["total"] else 0
        null_style = "red" if pct_null > 20 else ("yellow" if pct_null > 0 else "dim")
        name_disp = col if len(col) <= 40 else col[:37] + "…"

        line1 = f"[{color}]{icon}[/][bold #e6edf3]{name_disp}[/]  [dim]{dtype}[/]"
        line2 = (
            f"  [#58a6ff]count[/] [#e6edf3]{stats['total']:,}[/]"
            f"  [{null_style}]null[/] [{null_style}]{stats['null']:,} ({pct_null:.1f}%)[/]"
            f"  [#7ee787]unique[/] [#e6edf3]{stats['unique']:,}[/]"
        )
        lines = [line1, line2]
        if formula_line:
            lines.append(formula_line)

        if "min" in stats:
            def fmt(v: float) -> str:
                if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
                    return f"{int(v):,}"
                return f"{v:,.4g}" if abs(v) < 1_000_000 else f"{v:.4e}"

            line3 = (
                f"  [#58a6ff]min[/] [#e6edf3]{fmt(stats['min'])}[/]"
                f"  [#58a6ff]max[/] [#e6edf3]{fmt(stats['max'])}[/]"
                f"  [#58a6ff]mean[/] [#e6edf3]{fmt(stats['mean'])}[/]"
                f"  [#58a6ff]median[/] [#e6edf3]{fmt(stats['median'])}[/]"
            )
            if "stdev" in stats:
                line3 += f"  [#58a6ff]σ[/] [#e6edf3]{fmt(stats['stdev'])}[/]"
            lines.append(line3)

        self.query_one("#stats-panel", Static).update("\n".join(lines))


# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = CsvTui()
    app.run()
