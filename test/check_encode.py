#!/usr/bin/env python3
"""Verify UPNG.js encoder output with a standard decoder (Pillow) and print
the acceptance matrix.

Checks, for every reference sample:
  encode    <out>/<name>.png (produced by UPNG.encode in test/interop.js)
            decoded by Pillow must equal refs/<name>.rgba
Plus:
  encodeLL  <out>/ll_*.png decoded by Pillow must match the exact source
            samples (<out>/ll_*.raw); 16-bit outputs are compared at full
            precision where Pillow keeps it (I;16), else by high byte
  quantize  <out>/quantize64.png must decode to the right size with <= 64
            distinct colors (lossy path: no pixel-equality requirement)

Merges node-side results (<out>/decode_results.json) into the final sample
matrix, writes test RESULTS to <out>/RESULTS.md, exits non-zero on failure.

Usage: python3 test/check_encode.py <refs-dir> <out-dir>
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def check_encode(refs, out, name):
    exp = np.frombuffer((refs / f"{name}.rgba").read_bytes(), dtype=np.uint8)
    im = Image.open(out / f"{name}.png")
    im.load()
    got = np.array(im.convert("RGBA"), dtype=np.uint8).ravel()
    if got.shape != exp.shape:
        return f"FAIL(shape {got.shape} vs {exp.shape})"
    if np.array_equal(got, exp):
        return "PASS"
    i = int(np.nonzero(got != exp)[0][0])
    return f"FAIL(byte {i}: got {got[i]}, want {exp[i]})"


def check_ll(out, name, meta):
    raw = np.frombuffer((out / f"{name}.raw").read_bytes(), dtype=np.uint8)
    im = Image.open(out / f"{name}.png")
    im.load()
    w, h = meta["w"], meta["h"]
    if im.size != (w, h):
        return f"FAIL(size {im.size})"
    nch = meta["cc"] + meta["ac"]
    if meta["depth"] == 16 and meta["cc"] == 1 and meta["ac"] == 0:
        # Pillow keeps 16-bit gray at full precision
        got = np.array(im)
        if got.dtype != np.uint16:
            return f"FAIL(dtype {got.dtype})"
        want = raw.reshape(h, w, 2)
        want16 = (want[:, :, 0].astype(np.uint16) << 8) | want[:, :, 1]
        return "PASS" if np.array_equal(got, want16) else "FAIL(16-bit gray mismatch)"
    got = np.frombuffer(im.tobytes(), dtype=np.uint8)
    if meta["depth"] == 8:
        want = raw
    else:
        want = raw.reshape(-1, 2)[:, 0]  # high byte of each 16-bit sample
    if got.shape != want.shape:
        # Pillow maps 16-bit gray+alpha to RGBA (gray replicated): expand
        if nch == 2 and got.shape == (want.size * 2,):
            g, a = want[0::2], want[1::2]
            want = np.stack([g, g, g, a], axis=1).ravel()
        else:
            return f"FAIL(shape {got.shape} vs {want.shape})"
    return "PASS" if np.array_equal(got, want) else "FAIL(pixel mismatch)"


def check_quantize(out):
    im = Image.open(out / "quantize64.png")
    im.load()
    if im.size != (41, 29):
        return f"FAIL(size {im.size})"
    ncolors = len(np.unique(np.array(im.convert("RGBA")).reshape(-1, 4), axis=0))
    return "PASS" if ncolors <= 64 else f"FAIL({ncolors} colors > 64)"


def main():
    refs, out = Path(sys.argv[1]), Path(sys.argv[2])
    matrix = json.loads((refs / "matrix.json").read_text())
    node_results = {r["name"]: r for r in json.loads((out / "decode_results.json").read_text())}

    rows, failures = [], 0

    def emit(name, decode, roundtrip, encode):
        nonlocal failures
        fails = [v for v in (decode, roundtrip, encode)
                 if v not in ("PASS", "n/a", None)]
        if fails:
            failures += 1
        rows.append((name, decode or "-", roundtrip or "-", encode or "-"))
        print(f"{decode or '-':<28} {roundtrip or '-':<28} {encode or '-':<28} {name}")

    print(f"{'decode(UPNG)':<28} {'roundtrip(UPNG)':<28} {'encode->PIL':<28} sample")
    for name in matrix:
        nr = node_results.get(name, {})
        enc = check_encode(refs, out, name)
        emit(name, nr.get("decode"), nr.get("roundtrip"), enc)

    ll_meta = json.loads((out / "ll_meta.json").read_text())
    for name, meta in ll_meta.items():
        emit(name, None, None, check_ll(out, name, meta))

    emit("quantize64", node_results.get("quantize64", {}).get("decode"),
         None, check_quantize(out))

    total = len(rows)
    print(f"\n{total - failures}/{total} samples fully green")

    lines = ["# UPNG.js interop regression — sample matrix results", "",
             "| sample | decode (UPNG vs reference pixels) | roundtrip (decode→encode→decode) | encode (UPNG → Pillow) |",
             "|---|---|---|---|"]
    for name, d, r, e in rows:
        lines.append(f"| {name} | {d} | {r} | {e} |")
    lines += ["", f"**{total - failures}/{total} samples fully green**", ""]
    (out / "RESULTS.md").write_text("\n".join(lines))

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
