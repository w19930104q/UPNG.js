#!/usr/bin/env python3
"""Generate the reference-PNG sample matrix for the UPNG.js interop regression.

For every sample this writes, into the output directory:
  <name>.png   a reference PNG (hand-written with a minimal spec writer, or
               encoded by Pillow for encoder-diversity cases)
  <name>.rgba  the expected RGBA8 pixel dump: what a correct decoder must
               produce (PNG spec semantics; 16-bit samples reduce to their
               high byte, sub-8-bit gray samples scale to 0..255)
  matrix.json  per-sample metadata consumed by test/interop.js and
               test/check_encode.py

Every hand-written reference is cross-validated with Pillow (the standard
decoder) before the matrix is accepted, so a broken generator fails here
rather than masquerading as a library bug.

Usage: python3 test/gen_refs.py <out-dir>
"""
import json
import struct
import sys
import zlib
from pathlib import Path

import numpy as np
from PIL import Image

W, H = 37, 23  # odd width exercises sub-byte row packing/padding

CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


# ---------------------------------------------------------------- minimal PNG writer

def _chunk(typ, payload):
    return (struct.pack(">I", len(payload)) + typ + payload
            + struct.pack(">I", zlib.crc32(typ + payload) & 0xFFFFFFFF))


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _filter_row(ftype, row, prev, bpp):
    out = bytearray(len(row))
    for i, x in enumerate(row):
        a = row[i - bpp] if i >= bpp else 0
        b = prev[i] if prev is not None else 0
        c = prev[i - bpp] if (prev is not None and i >= bpp) else 0
        if ftype == 0:
            v = x
        elif ftype == 1:
            v = x - a
        elif ftype == 2:
            v = x - b
        elif ftype == 3:
            v = x - (a + b) // 2
        else:
            v = x - _paeth(a, b, c)
        out[i] = v & 0xFF
    return bytes(out)


def write_png(path, w, h, ctype, depth, rows, plte=None, trns=None, filters=None):
    """rows: list of h packed scanline byte strings (unfiltered)."""
    ihdr = struct.pack(">IIBBBBB", w, h, depth, ctype, 0, 0, 0)
    parts = [_chunk(b"IHDR", ihdr)]
    if plte is not None:
        parts.append(_chunk(b"PLTE", bytes(plte)))
    if trns is not None:
        parts.append(_chunk(b"tRNS", trns))
    bpp = max(1, CHANNELS[ctype] * depth // 8)
    raw = bytearray()
    prev = None
    for y, row in enumerate(rows):
        ft = 0 if filters is None else filters[y]
        raw.append(ft)
        raw += _filter_row(ft, row, prev, bpp)
        prev = row
    parts.append(_chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
    parts.append(_chunk(b"IEND", b""))
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"".join(parts))


def pack_row(vals, depth):
    """Pack one row of integer samples at the given bit depth (big-endian)."""
    if depth == 8:
        return bytes(vals)
    if depth == 16:
        out = bytearray()
        for v in vals:
            out += struct.pack(">H", v)
        return bytes(out)
    out, acc, nbits = bytearray(), 0, 0
    for v in vals:
        acc = (acc << depth) | v
        nbits += depth
        if nbits == 8:
            out.append(acc)
            acc, nbits = 0, 0
    if nbits:
        out.append(acc << (8 - nbits))
    return bytes(out)


# ---------------------------------------------------------------- sample generators

def gray_vals(w, h, depth):
    n = 1 << depth
    return [[(x * 5 + y * 11 + (x * y) % 7 + (x // 3)) % n for x in range(w)]
            for y in range(h)]


def rgb_vals(w, h, depth):
    n = 1 << depth
    return [[((x * 6 + y * 3) % n, (x * 2 + y * 11 + 40) % n, (x * 13 + y * 7 + 90) % n)
             for x in range(w)] for y in range(h)]


def pal_vals(w, h, ncol):
    return [[(x // 2 + y * 3 + (x * y) // 5) % ncol for x in range(w)]
            for y in range(h)]


def ga_vals(w, h, depth):
    n = 1 << depth
    return [[((x * 9 + y * 4) % n, (x * 5 + y * 251 + (x * y) * 3) % n)
             for x in range(w)] for y in range(h)]


def rgba_vals(w, h, depth):
    n = 1 << depth
    out = []
    for y in range(h):
        row = []
        for x in range(w):
            a = (x * 17 + y * 31) % n
            if (x + y) % 11 == 0:
                a = 0  # fully transparent pixels with non-zero RGB underneath
            row.append(((x * 6 + y) % n, (x + y * 8) % n, (x * 3 + y * 5 + 60) % n, a))
        out.append(row)
    return out


# ---------------------------------------------------------------- expected RGBA8

def exp_gray(g, depth, trns=None):
    if depth == 16:
        v8, tv = g >> 8, trns
    elif depth == 8:
        v8, tv = g, trns
    else:
        v8 = g * 255 // ((1 << depth) - 1)
        tv = trns
    a = 0 if (trns is not None and g == tv) else 255
    return (v8, v8, v8, a)


def expected_rgba(entry, src):
    """src: the generator values; returns bytes of RGBA8."""
    depth, ctype = entry["depth"], entry["ctype"]
    trns = entry.get("trns_val")
    out = bytearray()
    for row in src:
        for px in row:
            if ctype == 0:
                out += bytes(exp_gray(px, depth, trns))
            elif ctype == 2:
                if depth == 16:
                    rgb = (px[0] >> 8, px[1] >> 8, px[2] >> 8)
                else:
                    rgb = px
                a = 0 if (trns is not None and tuple(px) == tuple(trns)) else 255
                out += bytes(rgb + (a,))
            elif ctype == 3:
                r, g, b = entry["palette"][px]
                alphas = entry.get("pal_alpha")
                a = alphas[px] if alphas is not None and px < len(alphas) else 255
                out += bytes((r, g, b, a))
            elif ctype == 4:
                g, a = px
                if depth == 16:
                    g, a = g >> 8, a >> 8
                out += bytes((g, g, g, a))
            elif ctype == 6:
                if depth == 16:
                    px = tuple(v >> 8 for v in px)
                out += bytes(px)
    return bytes(out)


# ---------------------------------------------------------------- matrix construction

def make_entries():
    entries = []

    def add(name, ctype, depth, gen, trns=None, pal=None, pal_alpha=None,
            filters=None, w=W, h=H):
        entries.append(dict(name=name, ctype=ctype, depth=depth, gen=gen,
                            trns=trns, palette=pal, pal_alpha=pal_alpha,
                            filters=filters, w=w, h=h))

    # --- grayscale (ctype 0), depths 1/2/4/8/16, with and without tRNS
    for d in (1, 2, 4, 8, 16):
        add(f"gray{d}", 0, d, lambda d=d: gray_vals(W, H, d))
    add("gray4_trns", 0, 4, lambda: gray_vals(W, H, 4), trns=5)
    add("gray8_trns", 0, 8, lambda: gray_vals(W, H, 8), trns=27)
    add("gray16_trns", 0, 16, lambda: gray_vals(W, H, 16), trns=gray_vals(W, H, 16)[5][3])
    add("gray1_w8", 0, 1, lambda: gray_vals(8, 4, 1), w=8, h=4)   # byte-aligned rows
    add("gray1_w7", 0, 1, lambda: gray_vals(7, 4, 1), w=7, h=4)   # padded rows

    # --- truecolor (ctype 2), 8/16 bit, with and without tRNS
    add("rgb8", 2, 8, lambda: rgb_vals(W, H, 8))
    add("rgb16", 2, 16, lambda: rgb_vals(W, H, 16))
    rgb8 = rgb_vals(W, H, 8)
    rgb16 = rgb_vals(W, H, 16)
    add("rgb8_trns", 2, 8, lambda: rgb8, trns=rgb8[4][6])
    add("rgb16_trns", 2, 16, lambda: rgb16, trns=rgb16[7][2])

    # --- all filter types in one file (ctype 2/8)
    add("rgb8_filters", 2, 8, lambda: rgb_vals(W, H, 8),
        filters=[y % 5 for y in range(H)])

    # --- palette (ctype 3), depths 1/2/4/8, with and without tRNS
    for d, ncol in ((1, 2), (2, 4), (4, 16), (8, 256)):
        pal = [((i * 37 + 11) % 256, (i * 91 + 23) % 256, (i * 53 + 7) % 256)
               for i in range(ncol)]
        add(f"pal{d}", 3, d, lambda ncol=ncol: pal_vals(W, H, ncol), pal=pal)
    pal4 = [((i * 37 + 11) % 256, (i * 91 + 23) % 256, (i * 53 + 7) % 256)
            for i in range(16)]
    add("pal4_trns", 3, 4, lambda: pal_vals(W, H, 16), pal=pal4,
        pal_alpha=[0, 255, 128, 255, 64])  # short tRNS: rest implicitly 255
    pal8 = [((i * 37 + 11) % 256, (i * 91 + 23) % 256, (i * 53 + 7) % 256)
            for i in range(256)]
    add("pal8_trns", 3, 8, lambda: pal_vals(W, H, 256), pal=pal8,
        pal_alpha=[(i * 255 // 255) if i % 3 else 0 for i in range(256)])

    # --- gray+alpha (ctype 4) and RGBA (ctype 6), 8/16 bit
    add("ga8", 4, 8, lambda: ga_vals(W, H, 8))
    add("ga16", 4, 16, lambda: ga_vals(W, H, 16))
    add("rgba8", 6, 8, lambda: rgba_vals(W, H, 8))
    add("rgba16", 6, 16, lambda: rgba_vals(W, H, 16))
    add("rgba8_1x1", 6, 8, lambda: [[(200, 100, 50, 128)]], w=1, h=1)

    return entries


def build_raw(entry, outdir):
    """Hand-write the reference PNG; returns expected RGBA8 bytes."""
    ctype, depth = entry["ctype"], entry["depth"]
    src = entry["gen"]()
    w, h = entry["w"], entry["h"]

    trns_bytes = None
    if entry.get("trns") is not None:
        t = entry["trns"]
        if ctype == 0:
            trns_bytes = struct.pack(">H", t)
            entry["trns_val"] = t
        elif ctype == 2:
            trns_bytes = struct.pack(">HHH", *t)
            entry["trns_val"] = t
    if ctype == 3 and entry.get("pal_alpha") is not None:
        trns_bytes = bytes(entry["pal_alpha"])

    rows = []
    for y in range(h):
        if ctype in (0, 3):
            rows.append(pack_row(src[y], depth))
        else:
            flat = [v for px in src[y] for v in px]
            rows.append(pack_row(flat, depth))

    plte = None
    if ctype == 3:
        plte = [c for rgb in entry["palette"] for c in rgb]

    write_png(outdir / f"{entry['name']}.png", w, h, ctype, depth, rows,
              plte=plte, trns=trns_bytes, filters=entry.get("filters"))
    return expected_rgba(entry, src), src


# ---------------------------------------------------------------- Pillow-encoded variants

def build_pil(entry, outdir):
    """Encode with Pillow (standard encoder) for encoder diversity."""
    name, w, h = entry["name"], entry["w"], entry["h"]
    path = outdir / f"{name}.png"
    kind = entry["pil_kind"]
    if kind == "L":
        src = gray_vals(w, h, 8)
        Image.fromarray(np.array(src, dtype=np.uint8)).save(path)
        entry.update(ctype=0, depth=8, gen=lambda: src)
    elif kind == "I;16":
        src = gray_vals(w, h, 16)
        Image.fromarray(np.array(src, dtype=np.uint16)).save(path)
        entry.update(ctype=0, depth=16, gen=lambda: src)
    elif kind == "RGB":
        src = rgb_vals(w, h, 8)
        Image.fromarray(np.array(src, dtype=np.uint8)).save(path)
        entry.update(ctype=2, depth=8, gen=lambda: src)
    elif kind == "RGBA":
        src = rgba_vals(w, h, 8)
        Image.fromarray(np.array(src, dtype=np.uint8)).save(path)
        entry.update(ctype=6, depth=8, gen=lambda: src)
    elif kind == "P":
        ncol = 200
        src = pal_vals(w, h, ncol)
        pal = [((i * 37 + 11) % 256, (i * 91 + 23) % 256, (i * 53 + 7) % 256)
               for i in range(ncol)]
        alphas = [0 if i % 7 == 0 else (128 if i % 5 == 0 else 255)
                  for i in range(ncol)]
        im = Image.frombytes("P", (w, h), bytes(np.array(src, dtype=np.uint8).ravel()))
        im.putpalette([c for rgb in pal for c in rgb])
        im.save(path, transparency=bytes(alphas))
        entry.update(ctype=3, depth=8, gen=lambda: src, palette=pal,
                     pal_alpha=alphas)
    return expected_rgba(entry, entry["gen"]()), entry["gen"]()


# ---------------------------------------------------------------- reference validation

def validate_with_pil(entry, png_path, expected):
    """Cross-check the reference PNG with the standard decoder (Pillow)."""
    im = Image.open(png_path)
    im.load()
    w, h = entry["w"], entry["h"]
    assert im.size == (w, h), f"{entry['name']}: size {im.size}"
    exp = np.frombuffer(expected, dtype=np.uint8).reshape(h, w, 4)

    if entry["depth"] == 16:
        # Pillow reduces 16-bit samples to the high byte (I;16 keeps 16 bits)
        if entry["ctype"] == 0:
            arr = np.array(im)
            assert arr.dtype == np.uint16, f"{entry['name']}: {arr.dtype}"
            got = (arr >> 8).astype(np.uint8)
            ok = np.array_equal(got, exp[:, :, 0])
            if entry.get("trns_val") is not None:
                ok = ok and im.info.get("transparency") == entry["trns_val"]
            else:
                ok = ok and np.array_equal(got, exp[:, :, 1])
        else:
            got = np.array(im)
            if got.ndim == 2:
                got = got[:, :, None]
            nch = got.shape[2]
            # compare color channels (and alpha for ctype 4/6) as high bytes
            ok = np.array_equal(got, exp[:, :, :nch] if nch > 1 else exp[:, :, :1])
            if entry["ctype"] in (4, 6):
                ok = np.array_equal(got, exp[:, :, [0, 3] if nch == 2 else [0, 1, 2, 3]])
            elif entry["ctype"] == 2:
                ok = np.array_equal(got, exp[:, :, :3])
    elif entry["ctype"] == 0 and entry["depth"] < 8 and entry.get("trns_val") is not None:
        # Pillow quirk: for sub-8-bit gray it compares the *unscaled* tRNS
        # sample against scaled 0..255 pixels, so it never applies the alpha.
        # Cross-check color channels + the raw tRNS value instead; the alpha
        # semantics are verified against the spec by the UPNG decode check.
        got = np.array(im.convert("RGBA"))
        ok = (np.array_equal(got[:, :, :3], exp[:, :, :3])
              and im.info.get("transparency") == entry["trns_val"])
    else:
        got = np.array(im.convert("RGBA"))
        ok = np.array_equal(got, exp)
    return ok


# ---------------------------------------------------------------- main

def main():
    outdir = Path(sys.argv[1])
    outdir.mkdir(parents=True, exist_ok=True)

    entries = make_entries()
    for kind, w, h in (("L", W, H), ("I;16", W, H), ("RGB", W, H),
                       ("RGBA", W, H), ("P", W, H)):
        entries.append(dict(name=f"pil_{kind.replace(';', '').lower()}",
                            pil_kind=kind, w=w, h=h))

    matrix, failures = {}, []
    for entry in entries:
        name = entry["name"]
        if "pil_kind" in entry:
            expected, _ = build_pil(entry, outdir)
        else:
            expected, _ = build_raw(entry, outdir)
        (outdir / f"{name}.rgba").write_bytes(expected)

        ok = validate_with_pil(entry, outdir / f"{name}.png", expected)
        print(f"{'REF-OK  ' if ok else 'REF-BAD '} {name}")
        if not ok:
            failures.append(name)
        matrix[name] = dict(w=entry["w"], h=entry["h"], ctype=entry["ctype"],
                            depth=entry["depth"],
                            trns=entry.get("trns") is not None or entry.get("pal_alpha") is not None,
                            encoder="pil" if "pil_kind" in entry else "raw")

    (outdir / "matrix.json").write_text(json.dumps(matrix, indent=2))
    print(f"\n{len(matrix)} reference samples written to {outdir}/")
    if failures:
        print(f"REFERENCE VALIDATION FAILED for: {failures}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
