#!/usr/bin/env node
/* UPNG.js interop regression — Node side.
 *
 * For every reference sample in <refs-dir>/matrix.json:
 *   decode    UPNG.decode + UPNG.toRGBA8 must equal <name>.rgba (expected
 *             pixels produced by test/gen_refs.py from known source data)
 *   roundtrip UPNG.decode -> UPNG.encode -> UPNG.decode must be pixel-stable
 *   encode    the UPNG.encode output is written to <out-dir>/<name>.png for
 *             test/check_encode.py to verify with a standard decoder (Pillow)
 *
 * Additionally exercises UPNG.encodeLL (explicit color type / bit depth,
 * including 16-bit) and the quantizing encoder (ps > 0, smoke-checked).
 *
 * Usage: node test/interop.js <refs-dir> <out-dir>
 * Exit code 0 iff every decode and roundtrip check passes.
 */
'use strict';
const fs = require('fs');
const path = require('path');

const pako = require('pako');
const upngSrc = fs.readFileSync(path.join(__dirname, '..', 'UPNG.js'), 'utf8');
// UPNG.js is a browser-style script (no module.exports); evaluate it with
// its expected globals instead of modifying the library.
const UPNG = new Function('pako', 'window', upngSrc + '\n;return UPNG;')(pako, {});

const refsDir = process.argv[2];
const outDir = process.argv[3];
fs.mkdirSync(outDir, { recursive: true });

function readFileAsArrayBuffer(p) {
  const b = fs.readFileSync(p);
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
}

function decodeRGBA(pngPath) {
  const img = UPNG.decode(readFileAsArrayBuffer(pngPath));
  const frames = UPNG.toRGBA8(img);
  if (frames.length !== 1) throw new Error(`expected 1 frame, got ${frames.length}`);
  return { img, rgba: Buffer.from(frames[0]) };
}

const matrix = JSON.parse(fs.readFileSync(path.join(refsDir, 'matrix.json'), 'utf8'));
const results = [];
let failures = 0;

for (const [name, meta] of Object.entries(matrix)) {
  const row = { name, decode: 'FAIL', roundtrip: 'FAIL' };
  try {
    const expected = fs.readFileSync(path.join(refsDir, `${name}.rgba`));
    const { rgba } = decodeRGBA(path.join(refsDir, `${name}.png`));

    if (rgba.equals(expected)) row.decode = 'PASS';
    else {
      let i = 0;
      while (i < expected.length && expected[i] === rgba[i]) i++;
      row.decode = `FAIL(byte ${i}: got ${rgba[i]}, want ${expected[i]})`;
    }

    // roundtrip: re-encode the decoded RGBA losslessly, decode again
    const enc = UPNG.encode([rgba.buffer.slice(rgba.byteOffset, rgba.byteOffset + rgba.length)],
      meta.w, meta.h, 0);
    fs.writeFileSync(path.join(outDir, `${name}.png`), Buffer.from(enc));
    const { rgba: rgba2 } = decodeRGBA(path.join(outDir, `${name}.png`));
    if (rgba2.equals(rgba)) row.roundtrip = 'PASS';
  } catch (e) {
    row.decode = `FAIL(${e.message})`;
  }
  if (row.decode !== 'PASS' || row.roundtrip !== 'PASS') failures++;
  results.push(row);
  console.log(`${row.decode === 'PASS' ? 'PASS' : 'FAIL'} ${row.roundtrip === 'PASS' ? 'PASS' : 'FAIL'}  ${name}  [decode roundtrip]`);
}

// ---- encodeLL: explicit ctype/depth encodes (incl. 16-bit) ----------------
const llCases = [
  { name: 'll_gray8', cc: 1, ac: 0, depth: 8 },
  { name: 'll_gray16', cc: 1, ac: 0, depth: 16 },
  { name: 'll_ga8', cc: 1, ac: 1, depth: 8 },
  { name: 'll_ga16', cc: 1, ac: 1, depth: 16 },
  { name: 'll_rgb8', cc: 3, ac: 0, depth: 8 },
  { name: 'll_rgb16', cc: 3, ac: 0, depth: 16 },
  { name: 'll_rgba8', cc: 3, ac: 1, depth: 8 },
  { name: 'll_rgba16', cc: 3, ac: 1, depth: 16 },
];
const LW = 37, LH = 23;
const llMeta = {};
for (const c of llCases) {
  const n = LW * LH * (c.cc + c.ac) * (c.depth / 8);
  const src = new Uint8Array(n);
  for (let i = 0; i < n; i++) src[i] = (i * 37 + (i >> 3) * 11 + (i >> 7) * 5) & 255;
  try {
    const png = UPNG.encodeLL([src.buffer], LW, LH, c.cc, c.ac, c.depth);
    fs.writeFileSync(path.join(outDir, `${c.name}.png`), Buffer.from(png));
    fs.writeFileSync(path.join(outDir, `${c.name}.raw`), src);
    llMeta[c.name] = { w: LW, h: LH, cc: c.cc, ac: c.ac, depth: c.depth };
    results.push({ name: c.name, decode: 'n/a', roundtrip: 'n/a', encodeLL: 'written' });
    console.log(`PASS ----  ${c.name}  [encodeLL written]`);
  } catch (e) {
    failures++;
    results.push({ name: c.name, decode: 'n/a', roundtrip: 'n/a', encodeLL: `FAIL(${e.message})` });
    console.log(`FAIL ----  ${c.name}  [encodeLL: ${e.message}]`);
  }
}
fs.writeFileSync(path.join(outDir, 'll_meta.json'), JSON.stringify(llMeta, null, 2));

// ---- quantizing encoder (lossy by design): smoke check only ---------------
{
  const w = 41, h = 29;
  const rgba = new Uint8Array(w * h * 4);
  for (let i = 0; i < w * h; i++) {
    rgba[i * 4] = (i * 7) & 255; rgba[i * 4 + 1] = (i * 13) & 255;
    rgba[i * 4 + 2] = (i * 29) & 255; rgba[i * 4 + 3] = 255;
  }
  try {
    const png = UPNG.encode([rgba.buffer], w, h, 64);
    fs.writeFileSync(path.join(outDir, 'quantize64.png'), Buffer.from(png));
    const back = decodeRGBA(path.join(outDir, 'quantize64.png'));
    const ok = back.img.width === w && back.img.height === h;
    results.push({ name: 'quantize64', decode: ok ? 'PASS' : 'FAIL', roundtrip: 'n/a' });
    if (!ok) failures++;
    console.log(`${ok ? 'PASS' : 'FAIL'} ----  quantize64  [ps=64 smoke]`);
  } catch (e) {
    failures++;
    results.push({ name: 'quantize64', decode: `FAIL(${e.message})`, roundtrip: 'n/a' });
    console.log(`FAIL ----  quantize64  [${e.message}]`);
  }
}

fs.writeFileSync(path.join(outDir, 'decode_results.json'), JSON.stringify(results, null, 2));
console.log(`\n${results.length - failures}/${results.length} node-side checks passed`);
process.exit(failures ? 1 : 0);
