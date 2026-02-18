# dloc (Daily Lines of Code)

`dloc` is a simple Python utility that analyzes a Git repository's history to provide a daily summary of lines of code added, removed, and the net change.

## Features

- Extracts statistics from `git log`.
- Aggregates insertions and deletions by date.
- Outputs a clean Markdown table.

## Usage

Run the script from within any Git repository (or point it to one if you modify the path):

```bash
python3 /path/to/dloc/dloc
```

### Example Output

| Date       | Added   | Removed | Net Change |
|------------|---------|---------|------------|
| 2024-05-20 |     150 |      20 |        130 |
| 2024-05-19 |      45 |      10 |         35 |

## Implementation Details

The tool uses `git log --pretty=format:%ad --date=short --shortstat` to get the raw data and then parses it using regular expressions.
