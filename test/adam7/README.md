# Adam7 (interlaced PNG) regression suite

Locks down Adam7 decoding in `UPNG.js`: all seven passes, every PNG filter
type, every legal color type / bit depth, pixel-exact against an independent
spec implementation, with non-interlaced output provably unchanged.

## What was broken (at commit 88f504b)

Three independent defects, all on the interlace-only code path. A bisect
applying each fix in isolation against this suite shows that the 1/2/4-bit
"wrong pixels" symptoms were a *downstream effect* of defect 2 (the pass data
stream was corrupted before placement); the bit-packing shifts themselves
were already spec-correct.

1. **Average filter first-row pre-resolution used absolute indexes
   (`_filterZero`).** `data[x+1]` / `data[x+1-bpp]` ignored the pass offset
   `off`, so for every pass after the first, type-3 (Average) first
   scanlines read and overwrote bytes belonging to earlier passes. All
   indexes are now `off`-relative, matching the main unfilter loop.

2. **Empty passes were still "filtered" (`_filterZero` / `_readInterlace`).**
   An Adam7 pass with zero width or zero height carries no bytes, but the
   decoder still ran the first-row filter-byte rewrite. That rewrote the
   first filter byte of the *next* pass (corrupting Up/Average/Paeth
   streams) whenever an empty pass preceded a non-empty one (e.g. 1×1, 2×1),
   which in turn produced wrong pixels for every bit depth including the
   sub-byte 1/2/4 cases. Empty passes now return immediately and never
   advance the data offset; `_readInterlace` skips them before filtering.

3. **Inflate target buffer under-sized (`_decompress`).** The buffer was
   sized as a single non-interlaced image `(bpl+1+interlace)*h`. The seven
   Adam7 passes can require more bytes than that, so the internal inflate
   could throw `RangeError: offset is out of bounds` on valid files (45
   fixtures crashed outright). The buffer is now allocated to the exact
   Adam7 stream size (`_interlaceSize`); non-interlaced allocation is
   unchanged (`(bpl+1)*h`).

## The fixed sample matrix

`gen_matrix.py` deterministically generates, with no randomness (per-case
LCG seed), `manifest.json` plus 2580 PNG files (1290 logical images, each
encoded interlaced `_i7` and non-interlaced `_ni`):

- **15 color type / bit depth combos** — gray (1/2/4/8/16), RGB (8/16),
  palette (1/2/4/8, with tRNS alpha), gray+alpha (8/16), RGBA (8/16).
- **6 filter modes** — every scanline forced to one of None/Sub/Up/Average/
  Paeth, plus a mixed per-scanline mode.
- **16 dimensions** — including 1×1 (only pass 1 populated), 1×2 / 2×1
  (pass 7 empty / populated), sub-byte widths, and 8/16/32 boundaries so
  that **all seven passes and every empty-pass boundary are exercised**.
- tRNS chunks on gray/RGB (8/16) and palette images cover the alpha-0 paths.

Regenerate bit-identically with `python3 gen_matrix.py`. The generator also
cross-checks its reference RGBA against Pillow (when installed); 16-bit
cases differ from Pillow only in the 16→8 scaling convention (UPNG uses the
high byte), which the reference mirrors.

## Oracles / acceptance

Three independent checks, all must pass:

1. `run_accept.js` — for every case: UPNG's interlaced RGBA8 must equal its
   non-interlaced RGBA8, and both must equal `expected/<name>.rgba`
   byte-for-byte.
2. `ref_decode.py` — a self-contained decoder that re-implements zlib
   inflate, all five filters and Adam7 de-interlacing from the PNG spec
   (no PNG library) and independently reproduces every expected RGBA.
3. Non-interlaced parity — the 1290 `_ni` files decode byte-identically to
   the pre-fix library (verified during development; the interlace branch is
   the only changed behavior).

Run everything:

```
npm test
# or individually
python3 test/adam7/gen_matrix.py     # (re)build fixtures + Pillow cross-check
python3 test/adam7/ref_decode.py      # independent spec decoder
node   test/adam7/run_accept.js       # UPNG pixel-exact acceptance
```
