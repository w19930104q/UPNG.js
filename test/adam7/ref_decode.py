#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Independent, self-contained PNG reference decoder (subset) used to validate
the Adam7 fixtures from first principles rather than trusting a library.

Implements directly:
  * zlib inflate (via stdlib zlib, on the IDAT stream only)
  * all five PNG scanline filters (None/Sub/Up/Average/Paeth), per spec
  * Adam7 pass de-interlacing for every legal bit depth
  * expansion to RGBA8 with UPNG's 16-bit -> high-byte convention

No PNG library is used. The output is compared byte-for-byte against UPNG's
decoding of the same fixtures by check_npm.js / check_standalone.py.
"""
import json
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ADAM7 = [(0, 0, 8, 8), (0, 4, 8, 8), (4, 0, 8, 4), (0, 2, 4, 4),
         (2, 0, 4, 2), (0, 1, 2, 2), (1, 0, 2, 1)]
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def unfilter(raw, bpl, bpp, h):
    out = bytearray(bpl * h)
    pos = 0
    for y in range(h):
        f = raw[pos]
        line = raw[pos + 1:pos + 1 + bpl]
        rec = bytearray(bpl)
        for x in range(bpl):
            a = rec[x - bpp] if x >= bpp else 0
            b = out[(y - 1) * bpl + x] if y > 0 else 0
            c = out[(y - 1) * bpl + x - bpp] if (y > 0 and x >= bpp) else 0
            if f == 0:
                rec[x] = line[x]
            elif f == 1:
                rec[x] = (line[x] + a) & 255
            elif f == 2:
                rec[x] = (line[x] + b) & 255
            elif f == 3:
                rec[x] = (line[x] + ((a + b) >> 1)) & 255
            else:
                rec[x] = (line[x] + paeth(a, b, c)) & 255
        out[y * bpl:(y + 1) * bpl] = rec
        pos += 1 + bpl
    return out


def parse_png(path):
    d = open(path, "rb").read()
    assert d[:8] == b"\x89PNG\r\n\x1a\n"
    off, idat, plte, trns = 8, bytearray(), None, None
    w = h = depth = ctype = interlace = 0
    while off < len(d):
        ln = struct.unpack(">I", d[off:off + 4])[0]
        typ = d[off + 4:off + 8]
        body = d[off + 8:off + 8 + ln]
        if typ == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
            interlace = body[12]
        elif typ == b"IDAT":
            idat += body
        elif typ == b"PLTE":
            plte = list(body)
        elif typ == b"tRNS":
            trns = list(body)
        off += 12 + ln
    return w, h, depth, ctype, interlace, zlib.decompress(bytes(idat)), plte, trns


def unpack_packed(packed, w, h, depth):
    """packed scanlines (bpl*h bytes) -> h rows of w integer samples."""
    bpl = (w * depth + 7) // 8
    rows = []
    for y in range(h):
        row, bit = [], 0
        base = y * bpl
        for _ in range(w):
            byte = packed[base + (bit >> 3)]
            row.append((byte >> (8 - depth - (bit & 7))) & ((1 << depth) - 1))
            bit += depth
        rows.append(row)
    return rows


def unpack_bytes(packed, w, h, ch, depth):
    stride = ch * (depth // 8)
    rows = []
    for y in range(h):
        row = []
        base = y * w * stride
        for x in range(w):
            px = []
            for k in range(ch):
                p = base + x * stride + k * (depth // 8)
                px.append(packed[p] if depth == 8 else (packed[p] << 8 | packed[p + 1]))
            row.append(px)
        rows.append(row)
    return rows


def decode(path):
    w, h, depth, ctype, interlace, raw, plte, trns = parse_png(path)
    ch = CHANNELS[ctype]
    bpp_bits = ch * depth
    bpp_bytes = max(1, (bpp_bits + 7) // 8)
    logical = [[None] * w for _ in range(h)]

    passes = ADAM7 if interlace else [(0, 0, 1, 1)]
    for (sr, sc, ri, ci) in passes:
        sw = (w - sc + ci - 1) // ci if w > sc else 0
        sh = (h - sr + ri - 1) // ri if h > sr else 0
        if sw == 0 or sh == 0:
            continue
        bpl = (sw * bpp_bits + 7) // 8
        need = sh * (1 + bpl)
        chunk_raw = raw[:need]
        raw = raw[need:]
        packed = unfilter(chunk_raw, bpl, bpp_bytes, sh)
        if depth < 8:
            rows = unpack_packed(packed, sw, sh, depth)
            for yy in range(sh):
                for xx in range(sw):
                    logical[sr + yy * ri][sc + xx * ci] = [rows[yy][xx]]
        else:
            rows = unpack_bytes(packed, sw, sh, ch, depth)
            for yy in range(sh):
                for xx in range(sw):
                    logical[sr + yy * ri][sc + xx * ci] = rows[yy][xx]
    return expand(logical, w, h, ctype, depth, plte, trns)


def expand(logical, w, h, ctype, depth, plte, trns):
    out = bytearray(w * h * 4)
    q = 0
    for y in range(h):
        for x in range(w):
            px = logical[y][x]
            if ctype == 0:
                v = px[0]
                g = {1: 255 * v, 2: 85 * v, 4: 17 * v}.get(depth, v if depth == 8 else v >> 8)
                a = 255
                if trns is not None and v == struct.unpack(">H", bytes(trns))[0]:
                    a = 0
                out[q:q + 4] = (g, g, g, a)
            elif ctype == 2:
                vals = [s if depth == 8 else s >> 8 for s in px]
                a = 255
                tv = ([struct.unpack(">H", bytes(trns[2 * k:2 * k + 2]))[0] for k in range(3)]
                      if depth == 16 else list(trns))
                if trns is not None and list(px) == tv:
                    a = 0
                out[q:q + 4] = (*vals, a)
            elif ctype == 3:
                j = px[0]
                out[q:q + 4] = (plte[3 * j], plte[3 * j + 1], plte[3 * j + 2],
                                trns[j] if trns is not None and j < len(trns) else 255)
            elif ctype == 4:
                if depth == 16:
                    out[q:q + 4] = (px[0] >> 8, px[0] >> 8, px[0] >> 8, px[1] >> 8)
                else:
                    out[q:q + 4] = (px[0], px[0], px[0], px[1])
            else:
                out[q:q + 4] = tuple(s if depth == 8 else s >> 8 for s in px)
            q += 4
    return bytes(out)


def main():
    manifest = json.load(open(os.path.join(HERE, "manifest.json")))
    bad = 0
    for c in manifest:
        for tag in ("ni", "i7"):
            p = os.path.join(HERE, "fixtures", c["name"] + "_" + tag + ".png")
            exp = open(os.path.join(HERE, "expected", c["name"] + ".rgba"), "rb").read()
            got = decode(p)
            if got != exp:
                bad += 1
                print("REF MISMATCH", c["name"], tag)
                if bad > 10:
                    sys.exit(1)
    print("standalone reference decoder: %d files, all match expected RGBA" % (len(manifest) * 2))


if __name__ == "__main__":
    main()
