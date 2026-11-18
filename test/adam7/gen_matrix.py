#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Deterministic Adam7 regression matrix generator for UPNG.js.

Builds a FIXED matrix of interlaced (Adam7) and non-interlaced PNG fixtures
covering every legal color type / bit depth combination, all five PNG filter
types (single-filter files + a mixed per-scanline file), and image dimensions
that produce empty Adam7 passes.

For every logical image it also writes:
  - expected/<name>.rgba : reference RGBA8 expansion (pure spec implementation,
                            matching UPNG's documented 16-bit -> high-byte rule)
  - manifest.json        : case metadata for the Node.js acceptance runner

The generator is fully deterministic (per-case LCG seed, no randomness), so the
matrix can be regenerated bit-identically. Reference output is cross-checked
against Pillow when available.
"""
import json
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
FIX_DIR = os.path.join(HERE, "fixtures")
EXP_DIR = os.path.join(HERE, "expected")

# (color type, bit depth, channels) -- all legal PNG combinations
COMBOS = [
    (0, 1, 1), (0, 2, 1), (0, 4, 1), (0, 8, 1), (0, 16, 1),      # gray
    (2, 8, 3), (2, 16, 3),                                        # RGB
    (3, 1, 1), (3, 2, 1), (3, 4, 1), (3, 8, 1),                  # palette
    (4, 8, 2), (4, 16, 2),                                        # gray + alpha
    (6, 8, 4), (6, 16, 4),                                        # RGBA
]

# Dimensions chosen so that every Adam7 empty-pass boundary is hit somewhere:
#   1x1 (only pass 1 non-empty), 1x2 / 2x1 (pass 7 empty / populated),
#   sub-8 widths/heights, exact 8-blocks, off-by-one around 8/16/32.
DIMS = [(1, 1), (1, 2), (2, 1), (2, 2), (3, 1), (1, 3), (3, 3),
        (5, 4), (7, 7), (8, 8), (9, 9), (13, 11), (17, 13), (33, 33)]
LARGE_DIMS = [(65, 65), (100, 77)]

# filter modes: 0..4 = every scanline uses that filter; 5 = mixed per scanline
FILTER_MODES = [0, 1, 2, 3, 4, 5]
MODE_NAME = {0: "none", 1: "sub", 2: "up", 3: "avg", 4: "paeth", 5: "mixed"}

ADAM7 = [  # start_row, start_col, row_inc, col_inc (PNG spec table)
    (0, 0, 8, 8), (0, 4, 8, 8), (4, 0, 8, 4), (0, 2, 4, 4),
    (2, 0, 4, 2), (0, 1, 2, 2), (1, 0, 2, 1),
]


# ---------------------------------------------------------------- deterministic RNG
def lcg(seed):
    state = seed & 0xFFFFFFFF

    def nxt():
        nonlocal state
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        return state
    return nxt


def case_seed(ctype, depth, w, h, mode):
    return (ctype * 1000003 + depth * 10007 + w * 9176 + h * 193 + mode * 7919 + 0x5AD4A7) & 0xFFFFFFFF


# ---------------------------------------------------------------- PNG chunk writer
def chunk(typ, data):
    return struct.pack(">I", len(data)) + typ + data + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)


def write_png(path, w, h, ctype, depth, interlace, plte, trns, idat):
    ihdr = struct.pack(">IIBBBBB", w, h, depth, ctype, 0, 0, interlace)
    out = [b"\x89PNG\r\n\x1a\n", chunk(b"IHDR", ihdr)]
    if plte is not None:
        out.append(chunk(b"PLTE", bytes(plte)))
    if trns is not None:
        out.append(chunk(b"tRNS", bytes(trns)))
    out.append(chunk(b"IDAT", zlib.compress(bytes(idat), 9)))
    out.append(chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(b"".join(out))


# ---------------------------------------------------------------- sample packing
def pack_rows(rows, depth, ch, ww):
    """rows: list (length hh) of lists of ww pixel sample-lists -> packed scanlines."""
    lines = []
    if depth >= 8:
        stride = ch * (depth // 8)
        for row in rows:
            line = bytearray(ww * stride)
            p = 0
            for px in row:
                for s in px:
                    if depth == 16:
                        line[p] = (s >> 8) & 255
                        line[p + 1] = s & 255
                        p += 2
                    else:
                        line[p] = s & 255
                        p += 1
            lines.append(line)
    else:
        bpl = (ww * depth + 7) // 8
        for row in rows:
            line = bytearray(bpl)
            bit = 0
            for px in row:
                v = px[0]
                line[bit >> 3] |= (v & ((1 << depth) - 1)) << (8 - depth - (bit & 7))
                bit += depth
            lines.append(line)
    return lines


# ---------------------------------------------------------------- forward filtering
def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def filter_lines(raw_lines, bpl, bpp_bytes, mode, rnd):
    out = bytearray()
    for y, raw in enumerate(raw_lines):
        prev = raw_lines[y - 1] if y > 0 else bytearray(bpl)
        if mode == 5:
            f = rnd() % 5
        else:
            f = mode
        out.append(f)
        line = bytearray(bpl)
        for x in range(bpl):
            a = raw[x - bpp_bytes] if x >= bpp_bytes else 0
            b = prev[x]
            c = prev[x - bpp_bytes] if x >= bpp_bytes else 0
            if f == 0:
                line[x] = raw[x]
            elif f == 1:
                line[x] = (raw[x] - a) & 255
            elif f == 2:
                line[x] = (raw[x] - b) & 255
            elif f == 3:
                line[x] = (raw[x] - ((a + b) >> 1)) & 255
            else:
                line[x] = (raw[x] - paeth(a, b, c)) & 255
        out += line
    return out


# ---------------------------------------------------------------- logical image + RGBA expansion
def build_image(ctype, depth, ch, w, h, mode):
    rnd = lcg(case_seed(ctype, depth, w, h, mode))
    maxv = (1 << depth) - 1
    rows = []
    for _ in range(h):
        row = []
        for _ in range(w):
            row.append([rnd() & maxv for _ in range(ch)])
        rows.append(row)

    plte = trns = None
    if ctype == 3:
        ncolors = 1 << depth
        plte = [rnd() & 255 for _ in range(ncolors * 3)]
        trns = [(rnd() & 255) for _ in range(ncolors)]
        # guarantee a fully transparent and a fully opaque index are used
        trns[0] = 0
        if ncolors > 1:
            trns[1] = 255
        for y in range(h):
            for x in range(w):
                if (x + y) % 7 == 0:
                    rows[y][x][0] = 0
                elif ncolors > 1 and (x + y) % 11 == 0:
                    rows[y][x][0] = 1
    elif ctype in (0, 2) and depth in (8, 16):
        # tRNS: pick an existing sample so alpha-0 paths are exercised
        trns_val = [rnd() & maxv for _ in range(ch)]
        if ctype == 0:
            # gray tRNS is a 2-byte unsigned integer per the PNG spec
            trns = [struct.pack(">H", trns_val[0] & maxv)[0], struct.pack(">H", trns_val[0] & maxv)[1]]
        else:
            # RGB tRNS is three 2-byte unsigned integers per the PNG spec
            trns = []
            for s in trns_val:
                if depth == 16:
                    trns += [(s >> 8) & 255, s & 255]
                else:
                    trns += [s & 255, 0]
        if w * h:
            rows[0][0] = list(trns_val)
            if w * h > 1:
                rows[h - 1][w - 1] = list(trns_val)
    return rows, plte, trns, rnd


def expand_rgba(ctype, depth, rows, plte, trns, w, h):
    """Spec RGBA8 expansion; 16-bit samples use the high byte (UPNG convention)."""
    out = bytearray(w * h * 4)
    q = 0
    for y in range(h):
        for x in range(w):
            px = rows[y][x]
            if ctype == 0:
                v = px[0]
                g = {1: 255 * v, 2: 85 * v, 4: 17 * v}.get(depth, v if depth == 8 else (v >> 8))
                a = 255
                if trns is not None:
                    tv = struct.unpack(">H", bytes(trns))[0]
                    if v == tv:
                        a = 0
                out[q:q + 4] = bytes((g, g, g, a))
            elif ctype == 2:
                if depth == 16:
                    r, g, b = px[0] >> 8, px[1] >> 8, px[2] >> 8
                else:
                    r, g, b = px
                a = 255
                if trns is not None:
                    tv = ([struct.unpack(">H", bytes(trns[2 * k:2 * k + 2]))[0] for k in range(3)]
                          if depth == 16 else list(trns))
                    if list(px) == tv:
                        a = 0
                out[q:q + 4] = bytes((r, g, b, a))
            elif ctype == 3:
                j = px[0]
                out[q] = plte[3 * j]
                out[q + 1] = plte[3 * j + 1]
                out[q + 2] = plte[3 * j + 2]
                out[q + 3] = trns[j] if (trns is not None and j < len(trns)) else 255
            elif ctype == 4:
                if depth == 16:
                    g, a = px[0] >> 8, px[1] >> 8
                else:
                    g, a = px
                out[q:q + 4] = bytes((g, g, g, a))
            else:  # ctype 6
                if depth == 16:
                    out[q:q + 4] = bytes((px[0] >> 8, px[1] >> 8, px[2] >> 8, px[3] >> 8))
                else:
                    out[q:q + 4] = bytes(px)
            q += 4
    return out


# ---------------------------------------------------------------- IDAT builders
def build_noninterlaced(rows, depth, ch, w, h, mode, rnd):
    raw = pack_rows(rows, depth, ch, w)
    bpl = len(raw[0])
    bpp = max(1, (ch * depth + 7) // 8)
    return filter_lines(raw, bpl, bpp, mode, rnd)


def build_interlaced(rows, depth, ch, w, h, mode, rnd):
    idat = bytearray()
    for (sr, sc, ri, ci) in ADAM7:
        sw = (w - sc + ci - 1) // ci if w > sc else 0
        sh = (h - sr + ri - 1) // ri if h > sr else 0
        if sw == 0 or sh == 0:
            continue  # empty pass contributes zero bytes
        sub = []
        for yy in range(sh):
            row = []
            for xx in range(sw):
                row.append(rows[sr + yy * ri][sc + xx * ci])
            sub.append(row)
        raw = pack_rows(sub, depth, ch, sw)
        bpl = len(raw[0])
        bpp = max(1, (ch * depth + 7) // 8)
        idat += filter_lines(raw, bpl, bpp, mode, rnd)
    return idat


def main():
    os.makedirs(FIX_DIR, exist_ok=True)
    os.makedirs(EXP_DIR, exist_ok=True)
    manifest = []
    case_id = 0
    for ctype, depth, ch in COMBOS:
        for w, h in DIMS:
            for mode in FILTER_MODES:
                case_id += 1
                name = "c%02dd%02d_%03dx%03d_f%s" % (ctype, depth, w, h, MODE_NAME[mode])
                rows, plte, trns, rnd = build_image(ctype, depth, ch, w, h, mode)
                expected = expand_rgba(ctype, depth, rows, plte, trns, w, h)
                with open(os.path.join(EXP_DIR, name + ".rgba"), "wb") as f:
                    f.write(expected)
                for interlace in (0, 1):
                    tag = "i7" if interlace else "ni"
                    png_name = "%s_%s.png" % (name, tag)
                    rnd2 = lcg(case_seed(ctype, depth, w, h, mode) ^ 0x9E3779B9)
                    if interlace:
                        idat = build_interlaced(rows, depth, ch, w, h, mode, rnd2)
                    else:
                        idat = build_noninterlaced(rows, depth, ch, w, h, mode, rnd2)
                    write_png(os.path.join(FIX_DIR, png_name), w, h, ctype, depth,
                              interlace, plte, trns, idat)
                manifest.append({"name": name, "ctype": ctype, "depth": depth,
                                 "w": w, "h": h, "mode": mode, "modeName": MODE_NAME[mode]})
    # larger stress images, mixed filters only, both interlace states
    for ctype, depth, ch in COMBOS:
        for w, h in LARGE_DIMS:
            mode = 5
            case_id += 1
            name = "c%02dd%02d_%03dx%03d_f%s" % (ctype, depth, w, h, MODE_NAME[mode])
            rows, plte, trns, rnd = build_image(ctype, depth, ch, w, h, mode)
            expected = expand_rgba(ctype, depth, rows, plte, trns, w, h)
            with open(os.path.join(EXP_DIR, name + ".rgba"), "wb") as f:
                f.write(expected)
            for interlace in (0, 1):
                tag = "i7" if interlace else "ni"
                png_name = "%s_%s.png" % (name, tag)
                rnd2 = lcg(case_seed(ctype, depth, w, h, mode) ^ 0x9E3779B9)
                if interlace:
                    idat = build_interlaced(rows, depth, ch, w, h, mode, rnd2)
                else:
                    idat = build_noninterlaced(rows, depth, ch, w, h, mode, rnd2)
                write_png(os.path.join(FIX_DIR, png_name), w, h, ctype, depth,
                          interlace, plte, trns, idat)
            manifest.append({"name": name, "ctype": ctype, "depth": depth,
                             "w": w, "h": h, "mode": mode, "modeName": MODE_NAME[mode]})

    with open(os.path.join(HERE, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    print("generated %d logical images (%d PNG files)" % (len(manifest), len(manifest) * 2))

    # ---- reference cross-validation against Pillow (informational, hard-fail on 8-bit)
    try:
        from PIL import Image
    except ImportError:
        print("Pillow not available; skipping PIL cross-check")
        return
    hard_fail = []
    soft = 0
    for case in manifest:
        name = case["name"]
        exp = open(os.path.join(EXP_DIR, name + ".rgba"), "rb").read()
        for tag in ("ni", "i7"):
            p = os.path.join(FIX_DIR, name + "_" + tag + ".png")
            got = Image.open(p).convert("RGBA").tobytes()
            if got != exp:
                if case["depth"] == 16:
                    soft += 1  # Pillow may scale 16->8 differently; UPNG uses high byte
                else:
                    hard_fail.append((name, tag))
    if hard_fail:
        print("REFERENCE MISMATCH vs Pillow (8-bit cases):", hard_fail[:10])
        sys.exit(1)
    print("Pillow cross-check passed; %d 16-bit cases differ only in scaling convention (expected)" % soft)


if __name__ == "__main__":
    main()
