# CSV Analyzer

A terminal UI for browsing, filtering, and analyzing CSV files.

![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)

## Prerequisites

- Python 3.8 or later — [python.org](https://python.org)
- The [`textual`](https://github.com/Textualize/textual) library — installed automatically on first run

## Installation

### Windows

Double-click **`setup.bat`**.

This registers CSV Analyzer as a handler for `.csv` files. Then do a one-time step to set it as the default:

1. Right-click any `.csv` file → **Open with** → **Choose another app**
2. Select **CSV Analyzer** → tick **Always use this app** → OK

To uninstall: `powershell -ExecutionPolicy Bypass -File install_csv_default.ps1 -Uninstall`

### macOS

```bash
bash install_csv_mac.sh
```

This builds `CSV Analyzer.app` in the same folder and registers it with Launch Services.

**First run only** — macOS will block the unsigned app. Right-click `CSV Analyzer.app` → **Open** → **Open** to allow it.

Then set as default:

1. Right-click any `.csv` file → **Get Info** (⌘I)
2. **Open with** → select **CSV Analyzer** → click **Change All...**

To uninstall: `bash install_csv_mac.sh --uninstall`

### Direct use (any OS)

```bash
# macOS / Linux
bash csv_tui_launcher.sh myfile.csv

# Windows
csv_tui_launcher.bat myfile.csv

# Or directly with Python
python csv_tui.py myfile.csv
```

## Usage

| Key | Action |
|-----|--------|
| `o` | Open a CSV file |
| `r` | Reload current file |
| `/` | Focus filter bar |
| `=` | Focus compute bar |
| `?` | Compute syntax reference |
| `v` | Distinct value counts |
| `s` | Save / export |
| `d` | Delete a computed column |
| PgUp / PgDn | Scroll table |
| Esc | Clear bar / return to table |
| `q` | Quit |

### Column stats

Click any column in the left panel to see its type, count, null %, and unique count. Numeric columns also show min, max, mean, median, and standard deviation.

### Filtering

Type in the filter bar (`/`) to narrow rows in real time.

```
age > 30                       numeric comparison
city = Berlin                  exact match (case-insensitive)
name ~ ali                     substring search
score >= 80 & city = Rome      AND — chain with &
berlin                         plain text searches every column
```

Operators: `=` `!=` `>` `<` `>=` `<=` `~`

### Computed columns

Type in the compute bar (`=`) and press Enter to add a derived column.

```
price * 1.2 [with_tax]         arithmetic, named column
round(score / total * 100, 1)  math functions, auto-named
col_a + col_b                  column names used directly
```

Arithmetic operators: `+` `-` `*` `/` `//` `%` `**`

Available functions: `abs` `round` `min` `max` `int` `float` `str` `len` `pow` `sqrt` `exp` `log` `log10` `floor` `ceil` `sin` `cos` `tan`

Constants: `pi` `e`

Press `?` inside the app for the full reference.

### Distinct values

Press `v` to open the distinct values view. Select one or more columns to group by; press `s` to cycle sort order (count desc, value asc, count asc).

### Save / Export

Press `s` to open the export dialog. Options:

- **All rows** or **filtered rows only**
- **Include / exclude computed columns**
- Browse to any destination path
