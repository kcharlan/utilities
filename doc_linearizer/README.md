# HTML Documentation Linearizer

Command-line tool that flattens the `full-ig` HTML documentation into a single Markdown file.

Key behaviors:
- Uses `site/toc.html` to determine the exact page order and scope, so the flattened document mirrors the navigation the authors intended.
- Preserves the CSS-driven numbering (e.g., “2.1.3”) by reading the page-specific heading counters and rewriting each heading before conversion.
- Converts “waffle”/“dict”/metadata tables into Markdown so complex grids stay readable after flattening.
- Copies referenced assets (images, JSON/XML/ZIP/etc.) into an `assets/` directory alongside the output and rewrites links accordingly.
- Strips decorative chrome (spacer gifs, copy buttons, nav icons) and expands “Show Usage” toggle panels so the Markdown contains only the content users would read on the site.

## Setup
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Usage
```bash
# default output = linearized_output.md (plus ./assets)
python linearize.py /path/to/full-ig

# specify a different destination (assets will sit next to this path)
python linearize.py /path/to/full-ig --output docs/flat_guide.md
```

The script prints progress as it walks the ToC. After completion you will have:
- `<output>.md`: concatenated Markdown with heading numbers and normalized tables.
- `<output dir>/assets/`: copies of every non-HTML asset referenced by the IG (images, NDJSON, XML, etc.) with rewritten links in the Markdown.
