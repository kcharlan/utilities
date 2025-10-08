# Reversible Skew
Experimentation ground for a reversible Burrows–Wheeler transform (BWT) pipeline with Move-to-Front (MTF) encoding, run-length encoding (RLE), and passthrough fallbacks when compression would expand data.

## Scripts

- `rs.py` – Pure-Python implementation with optional `pydivsufsort` acceleration for suffix arrays. Self-validates every block before writing the transform.
- `rs-big.py` – Performance-oriented variant that JIT-compiles the MTF/RLE steps with Numba and skips round-trip validation for speed.
- `setup.sh` – Builds `venv/` (make sure to add `pydivsufsort` and `numba` manually if you want the fast paths).

## Workflow

1. **Transform a file**
   ```bash
   python rs.py transform input.bin output.rsbwt --block-size 4M --max-run 255 --verbose
   ```
   - Splits the file into fixed-size blocks (`--block-size`).
   - Applies BWT → MTF → RLE and writes the primary index + payload length per block.
   - If the compressed payload would be larger than the original block, writes the raw block with a sentinel so the inverse can copy it back.

2. **Invert the transform**
   ```bash
   python rs.py inverse output.rsbwt recovered.bin --verbose
   ```
   - Restores the original bytes block-by-block using the stored primary index or passthrough sentinel.

Switch to `rs-big.py` if you have `pydivsufsort` and `numba` installed; its CLI mirrors `rs.py`.

## Options

- `--block-size` / `-b` – Accepts raw integers or sizes like `256K`, `4M`, etc.
- `--max-run` – Caps RLE run length (255 by default to fit one byte).
- `--whole-file` – Process the entire file in one block (useful for small inputs).
- `--verbose` – Prints per-block mode (raw vs transform) and payload sizes.

## Dependencies

- Optional: `pydivsufsort` dramatically speeds up suffix array construction compared to the naive `O(n^2 log n)` rotation sort.
- Optional: `numba` enables the JIT paths in `rs-big.py`. Without it, the script falls back to slower pure-Python loops.

## Implementation Notes

- BWT inverse uses LF-mapping with explicit cumulative counts (`C`) and Occurrence tables.
- Validation in `rs.py` reconstructs each block and compares to the original before writing, guaranteeing reversibility even under rare corner cases.
- Output format: `[primary_index:uint32][payload_len:uint32][payload_bytes...]` repeated per block. Raw blocks are tagged with `primary_index = 0xFFFFFFFF`.

## Ideas for Future Work

- Add secondary entropy coding (e.g., `zlib`, `range coding`) on top of the RLE stream.
- Implement adaptive block sizing based on entropy estimators.
- Surface compression ratios and timings in the CLI output.
