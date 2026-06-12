# d2d_tools

Internal utilities for data analysis and manipulation.

---

## csv_tui.py

A terminal-based CSV analyzer built with [Textual](https://github.com/Textualize/textual).

![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)

### Features

- Browse any CSV in a scrollable, zebra-striped table
- **Filter** rows with an expressive query syntax
- **Compute** new columns from arithmetic expressions
- **Distinct value** counts and frequency breakdowns across one or more columns
- **Column stats** — count, nulls, unique, min/max/mean/median/stdev
- **Save/Export** — write filtered or full data (with or without computed columns) to a new CSV
- File picker with Windows drive navigation
- Auto-installs `textual` on first run if missing

### Install

```bash
pip install textual
```

### Usage

```bash
python csv_tui.py [file.csv]
```

If no file is passed, press `o` inside the app to open a file picker.

### Key bindings

| Key | Action |
|-----|--------|
| `o` | Open file |
| `r` | Reload current file |
| `/` | Focus filter bar |
| `=` | Focus compute bar |
| `?` | Compute syntax reference |
| `v` | Distinct value viewer |
| `s` | Save / Export |
| `d` | Delete selected computed column |
| `PgUp / PgDn` | Scroll table |
| `q` | Quit |

### Filter syntax

Type expressions in the `/` bar. Results update as you type.

```
age > 30                        numeric comparison
city = Berlin                   exact match (case-insensitive)
name ~ ali                      substring search
score >= 80 & city = Rome       AND conditions
berlin                          plain text searches all columns
```

Operators: `=` `!=` `>` `<` `>=` `<=` `~`

### Compute syntax

Type in the `=` bar and press Enter to add a new column.

```
price * 1.2 [inflated]          multiply with a custom column name
col1 + col2 * 0.5               arithmetic across columns
round(price * 1.2, 2) [inc]     math functions
sqrt(area)                      [name] is optional — defaults to computed_1, computed_2 …
```

Available functions: `abs`, `round`, `min`, `max`, `int`, `float`, `str`, `len`, `pow`, `sqrt`, `exp`, `log`, `log10`, `floor`, `ceil`, `sin`, `cos`, `tan`, `pi`, `e`
