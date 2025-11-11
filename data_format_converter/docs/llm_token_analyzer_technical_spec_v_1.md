# LLM Token Analyzer & Format Converter — Technical Specification (Build-Ready)

**Owner:** Kevin Harlan  
**Version:** 1.0  
**Date:** 2025-11-11

---

## 0. Purpose
Translate the PRD into precise implementation guidance suitable for an AI coding tool. Defines architecture, module boundaries, interfaces, error model, test plan, and acceptance criteria for a static Web tool and a Python CLI that convert between JSON/XML/TOON and report token counts for GPT‑5 with API→local fallback.

---

## 1. Scope
- **In scope**: Static HTML/JS front-end; Python CLI; local token estimator; conversion modules (JSON, XML, TOON); validation; unit tests; accessible UI; deterministic output formatting.  
- **Out of scope**: Server/backend, file uploads, persistence, analytics, third‑party CDNs, non‑OpenAI tokenizers (future work hooks only).

---

## 2. High-Level Architecture

```
+-------------------+             +----------------------------+
|   Web (HTML/JS)   |  tokenize?  |  OpenAI Tokenize Endpoint  |
| - UI components   | ----------> |  /v1/tokenize (optional)   |
| - Converters (JS) | <---------- |  (HTTP 2xx + counts)       |
| - Local tokenizer |  fallback   +----------------------------+
+-------------------+
        |
        | conversion, counts
        v
+-------------------+       
| Python CLI        |
| data_convert.py   |--Converters--> json_conv/xml_conv/toon_conv
| (no token counts) |
+-------------------+
```

**Key principles**: single-file web app; no network required beyond optional API; deterministic formatting; strict validation before conversion; all errors surfaced inline.

---

## 3. Detailed Design — Web Tool

### 3.1 Files
- `web_tool.html` — single HTML containing inline CSS and JS (no external deps).

### 3.2 UI Layout
- Five vertically stacked panels: **Raw Text**, **JSON (Pretty)**, **JSON (Compact)**, **XML**, **TOON**.  
- Each panel contains: editable `<textarea>`, **Calculate** button, result area with token count, status chip (✅ API or ⚙️ Local), and inline error region.  
- A **Comparison Table** shows: format, token count, % over min.

### 3.3 UX Rules
- **Raw Text entry →** clears & disables all structured inputs until **Calculate** completes successfully.  
- **Editable panels** do not auto‑recompute on keystroke; recompute only on **Calculate**.  
- **Error protocol**: first validation failure aborts pipeline, displays inline message, clears all counts, clears comparison table.

### 3.4 Data Model (JS)
```ts
// Pseudo‑TS types (implemented in plain JS)
const Formats = {
  RAW: 'raw', JSON_PRETTY: 'json_pretty', JSON_COMPACT: 'json_compact',
  XML: 'xml', TOON: 'toon'
};

/** Unified payload routed to tokenizer */
// note: text must be the exact string as shown in the corresponding textarea
// for deterministic counts.
// mode: 'api'|'local' resolved internally; callers don’t set it.
// sourceFormat used for conversion provenance and error reporting.
/** @typedef {Object} TokenizationRequest
 *  @property {string} text
 *  @property {string} sourceFormat // one of Formats
 */

/** @typedef {Object} TokenizationResult
 *  @property {number} tokens
 *  @property {'api'|'local'} engine
 */

/** @typedef {Object} ConversionResult
 *  @property {string} jsonPretty
 *  @property {string} jsonCompact
 *  @property {string} xml
 *  @property {string} toon
 */
```

### 3.5 Pipeline (on **Calculate**)
1. **Detect source** textbox that triggered action.  
2. **Validate** according to format schema.  
3. **Convert** to all other formats using pure JS converters (defined below).  
4. **Render** textboxes with converted outputs (disabled if source is Raw Text).  
5. **Tokenize** each format string in parallel: try API → fallback to local.  
6. **Update comparison table** with counts and % over the minimum.

### 3.6 Tokenization Subsystem (Web)

#### 3.6.1 API contract (assumed)
- **Endpoint:** `POST /v1/tokenize`  
- **Body:** `{ "model": "gpt-5", "input": "<text>" }`  
- **Response:** `{ "tokens": <integer> }`
- **Headers:** `Authorization: Bearer <key>`, `Content-Type: application/json`
- **Timeout:** 3s. Treat timeout or non‑2xx as failure → fallback.

> Implementation note: Do not hardcode keys. Read from `window.OPENAI_API_KEY` if present, else skip API attempt.

#### 3.6.2 Local estimator (embedded)
- Bundle a small JS port of `tiktoken`‑style BPE for GPT‑5 **or** include a calibrated heuristic backed by a prebuilt wasm/token table.  
- Expose `estimateTokens(text) -> number` with stable results across sessions.  
- Calibration constant and unit tests included in web script.

#### 3.6.3 Algorithm
```js
async function tokenizeText(text) {
  // Try API if key present
  if (window.OPENAI_API_KEY) {
    try {
      const controller = new AbortController();
      const id = setTimeout(() => controller.abort(), 3000);
      const res = await fetch('https://api.openai.com/v1/tokenize', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${window.OPENAI_API_KEY}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ model: 'gpt-5', input: text }),
        signal: controller.signal
      });
      clearTimeout(id);
      if (res.ok) {
        const json = await res.json();
        return { tokens: Number(json.tokens), engine: 'api' };
      }
    } catch (_) { /* fall through */ }
  }
  // Fallback local
  return { tokens: estimateTokens(text), engine: 'local' };
}
```

### 3.7 Converters (Web, Pure JS)
- **JSON**: parse/serialize; pretty (2 spaces, sorted keys) vs compact (no spaces, sorted keys).  
- **XML**: deterministic ordering by keys; attributes unsupported; text nodes preserved; round‑trip via JS `xml2json` micro‑impl.  
- **TOON**: provide pluggable adapter. If no library present in browser, implement minimal parser for key: value pairs, arrays, and objects subset.

```js
function toJsonPretty(obj) { return JSON.stringify(obj, Object.keys(obj).sort(), 2); }
function toJsonCompact(obj) { return JSON.stringify(obj, Object.keys(obj).sort()); }

function jsonFromPretty(s) { return JSON.parse(s); }
function jsonFromCompact(s) { return JSON.parse(s); }

function xmlFromJson(obj) { /* deterministic serializer */ }
function jsonFromXml(xmlStr) { /* parse to JS object */ }

function toonFromJson(obj) { /* serializer */ }
function jsonFromToon(toonStr) { /* parser */ }
```

### 3.8 Validation Rules
- **JSON**: must parse; disallow `NaN`, `Infinity`, and non‑string keys.  
- **XML**: well‑formed; no attributes; single root; whitespace normalized.  
- **TOON**: subset only; fail on comments or unsupported directives.  
- **Raw**: no validation (count‑only path).

### 3.9 Error Model (Web)
- All errors return `{code, message, details?}`.  
- Codes: `E_PARSE_JSON`, `E_PARSE_XML`, `E_PARSE_TOON`, `E_VALIDATE`, `E_TOKENIZE_API`, `E_UNKNOWN`.  
- On any error: clear all token displays and comparison table; show inline error under the offending panel.

### 3.10 Accessibility & Performance
- WCAG AA: labeled controls, keyboard navigation, ARIA live region for errors.  
- No blocking work >16ms on main thread: heavy parsing/tokenization in microtasks; chunk work via `requestIdleCallback` where needed.  
- Target initial load < 100KB gzipped.

---

## 4. Detailed Design — CLI

### 4.1 Files & Structure
```
src/
  data_convert.py
  converters/
    __init__.py
    json_conv.py
    xml_conv.py
    toon_conv.py
tests/
  test_json_conv.py
  test_xml_conv.py
  test_toon_conv.py
requirements.txt
README.md
```

### 4.2 CLI Interface
```
$ data_convert --input <file> --to <json|jsonc|xml|toon> [--output <file>]
```
- `json` → JSON Pretty (sorted keys, 2 spaces)  
- `jsonc` → JSON Compact (sorted keys, no spaces)  
- Default output filename: `<basename>.<ext>`

### 4.3 Python Module Contracts

#### 4.3.1 `json_conv.py`
```py
from typing import Any, Tuple

def load_json(text: str) -> Any: ...  # strict JSON parse

def dump_pretty(obj: Any) -> str: ... # 2-spaces, sorted keys

def dump_compact(obj: Any) -> str: ...# no spaces, sorted keys
```

#### 4.3.2 `xml_conv.py`
```py
import xmltodict
from typing import Any

def load_xml(text: str) -> Any: ...    # well-formed, single root, no attrs

def dump_xml(obj: Any) -> str: ...     # deterministic ordering
```

#### 4.3.3 `toon_conv.py`
```py
from typing import Any

class ToonUnavailable(Exception): ...

def load_toon(text: str) -> Any: ...   # subset parse if lib missing

def dump_toon(obj: Any) -> str: ...
```

#### 4.3.4 `data_convert.py`
```py
import argparse
from converters.json_conv import load_json, dump_pretty, dump_compact
from converters.xml_conv import load_xml, dump_xml
from converters.toon_conv import load_toon, dump_toon, ToonUnavailable

SUPPORTED_TO = { 'json': 'json', 'jsonc': 'jsonc', 'xml': 'xml', 'toon': 'toon' }

def detect_format(path: str, contents: str) -> str: ...

def convert(from_fmt: str, to_fmt: str, contents: str) -> str: ...

def main(argv=None) -> int: ...

if __name__ == '__main__':
    raise SystemExit(main())
```

### 4.4 Validation & Determinism
- Sort all object keys lexicographically before serialization.  
- Normalize newlines to `\n`.  
- Ensure a trailing newline in files.

### 4.5 Error Model (CLI)
- Exit codes: `0` OK, `2` usage error, `3` parse/validation error, `4` conversion unsupported, `5` unknown.  
- STDERR messages are single‑line JSON: `{ "code": "E_PARSE_JSON", "message": "...", "hint": "..." }`.

---

## 5. Deterministic Conversions
- **JSON ↔ XML**: Map object → element with child elements; arrays → repeated elements; strings/numbers/bools → text nodes; `null` → empty element `<k/>`.  
- **JSON ↔ TOON**: Draft a strict subset: objects `{}`; arrays `[]`; scalars; no comments; no trailing commas; UTF‑8 only.

---

## 6. Testing Strategy (pytest)

### 6.1 Unit Tests (CLI modules)
- **Positive**: round‑trip JSON pretty↔compact; JSON→XML→JSON equivalence; TOON→JSON on valid subset.  
- **Negative**: malformed JSON/XML/TOON; unsupported TOON features.

### 6.2 Web Unit (headless)
- Token fallback path: simulate API failure → expect `engine=local`.  
- Comparison math correctness.  
- Deterministic serializers yield stable strings.

### 6.3 Golden Files
- Place canonical inputs/outputs under `tests/data/`. Use snapshot tests for serializers.

---

## 7. Build & Tooling
- **Python**: `python>=3.10`; `pip install -r requirements.txt`; entry point via `console_scripts` in `setup.cfg` (optional) or a simple shim.  
- **Web**: no build; just open `web_tool.html` in modern browser.

`requirements.txt`
```
xmltodict
requests
tiktoken
pyyaml
# Optional; handled gracefully if missing
toon
```

---

## 8. Acceptance Criteria
1. Web page opens offline; converting JSON⇄XML⇄TOON works for provided samples.  
2. Clicking **Calculate** after valid input fills all other panels and token counts for each; status chip displays ✅ API when key present and endpoint returns counts; otherwise ⚙️ Local.  
3. Any parse error produces a visible inline error and clears all token counts and the comparison table.  
4. CLI converts between any supported formats and writes deterministic outputs with expected filenames by default.  
5. Test suite passes locally with `pytest -q` (excluding web UI interaction tests).

---

## 9. Risk Mitigations
- **TOON availability:** ship subset parser; mark advanced features unsupported with explicit errors.  
- **Tokenizer drift:** encapsulate local estimator behind single function; allow drop‑in replacement table.  
- **XML edge cases:** forbid attributes; normalize whitespace and enforce single root.

---

## 10. Work Breakdown (for AI Coding Tool)

### 10.1 Web
- [ ] Implement HTML structure with five panels and comparison table.  
- [ ] Write converters (json/xml/toon) in pure JS with deterministic ordering.  
- [ ] Implement tokenizer API client with 3s timeout and local fallback.  
- [ ] Wire validation → conversion → tokenization pipeline.  
- [ ] Inline error component and ARIA live region.  
- [ ] Unit helpers (pure functions) + small tests runnable via Node for determinism.

### 10.2 CLI (Python)
- [ ] Implement converters per contracts.  
- [ ] Implement detection and `convert()` orchestration.  
- [ ] Argparse CLI, default output naming, and exit codes.  
- [ ] Pytest coverage and golden files.

---

## 11. Example E2E Scenarios
1. **JSON Pretty input** → Calculate → all other panels filled; API tokenization succeeds (✅); table shows JSON Compact is smallest; % deltas correct.  
2. **Malformed XML input** → inline `E_PARSE_XML` with line/col; counts cleared; table cleared.  
3. **Raw Text input** → only counts computed; all structured panels disabled until next valid structured Calculate.

---

## 12. Future Hooks
- Plug‑in architecture for additional tokenizers (Anthropic/Gemini) via `tokenizeTextWith(engineId, text)`; engines config array.  
- Optional workerization for local tokenization.

---

## 13. Pseudocode — Deterministic XML Serializer
```py
# depth-first, key-sorted

def to_xml(obj, tag='root'):
    if obj is None:
        return f'<{tag}/>'
    elif isinstance(obj, (str, int, float, bool)):
        return f'<{tag}>{escape(str(obj))}</{tag}>'
    elif isinstance(obj, list):
        return ''.join(to_xml(item, tag) for item in obj)
    elif isinstance(obj, dict):
        children = []
        for k in sorted(obj.keys()):
            children.append(to_xml(obj[k], k))
        return f'<{tag}>' + ''.join(children) + f'</{tag}>'
    else:
        raise TypeError('Unsupported type')
```

---

## 14. Definitions of Done
- Reproducible deterministic outputs across OS/browser for same inputs.  
- No console errors; Lighthouse performance > 95 (local file).  
- CLI completes ≤3s on 1MB inputs; verified by simple timer harness.

