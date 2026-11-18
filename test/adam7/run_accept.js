#!/usr/bin/env node
/*
 * Adam7 acceptance runner for UPNG.js.
 *
 * For every case in the fixed matrix (manifest.json) it decodes both the
 * interlaced (_i7.png) and non-interlaced (_ni.png) fixture with UPNG and
 * asserts:
 *
 *   1. interlaced RGBA8 == non-interlaced RGBA8   (Adam7 must reconstruct
 *      exactly the same logical image; this is the primary oracle)
 *   2. both == the reference expansion in expected/<name>.rgba   (pixel-exact
 *      against the pure-spec reference; 16-bit cases use UPNG's high-byte
 *      convention, which the reference mirrors)
 *
 * Exits non-zero and prints a full failure list on any mismatch.
 */
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const HERE = __dirname;
const ROOT = path.resolve(HERE, "..", "..");
const UPNG_PATH = process.argv[2] || path.join(ROOT, "UPNG.js");

const src = fs.readFileSync(UPNG_PATH, "utf8");
const sandbox = { Uint8Array, Uint16Array, Uint32Array, Int16Array, Math, Date };
sandbox.window = sandbox; // encoder references window; decoder never does
vm.createContext(sandbox);
vm.runInContext(src, sandbox, { filename: "UPNG.js" });
const UPNG = sandbox.UPNG;

const manifest = JSON.parse(fs.readFileSync(path.join(HERE, "manifest.json"), "utf8"));

function decodeRgba(pngPath) {
  const buf = fs.readFileSync(pngPath);
  const out = UPNG.decode(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.length));
  return new Uint8Array(UPNG.toRGBA8(out)[0]);
}

let failures = [];
let pass = 0;
const t0 = Date.now();

for (const c of manifest) {
  const i7Path = path.join(HERE, "fixtures", c.name + "_i7.png");
  const niPath = path.join(HERE, "fixtures", c.name + "_ni.png");
  const expPath = path.join(HERE, "expected", c.name + ".rgba");
  const expected = fs.readFileSync(expPath);
  let rgbaI7, rgbaNi;
  try { rgbaI7 = decodeRgba(i7Path); } catch (e) { failures.push({ name: c.name, kind: "i7-throw", detail: String(e) }); continue; }
  try { rgbaNi = decodeRgba(niPath); } catch (e) { failures.push({ name: c.name, kind: "ni-throw", detail: String(e) }); continue; }

  if (rgbaI7.length !== expected.length) {
    failures.push({ name: c.name, kind: "i7-length", detail: rgbaI7.length + " vs " + expected.length });
    continue;
  }
  let niMismatch = 0, i7Mismatch = 0, firstDiff = null;
  for (let i = 0; i < expected.length; i++) {
    if (rgbaNi[i] !== expected[i]) { niMismatch++; if (firstDiff === null) firstDiff = i; }
    if (rgbaI7[i] !== expected[i]) { i7Mismatch++; if (firstDiff === null) firstDiff = i; }
  }
  let pairMismatch = 0;
  for (let i = 0; i < rgbaI7.length; i++) if (rgbaI7[i] !== rgbaNi[i]) pairMismatch++;

  if (niMismatch || i7Mismatch || pairMismatch) {
    failures.push({
      name: c.name, ctype: c.ctype, depth: c.depth, w: c.w, h: c.h, mode: c.modeName,
      niMismatch, i7Mismatch, pairMismatch, firstDiff
    });
  } else pass++;
}

const ms = Date.now() - t0;
// bucket failures for triage
const byMode = {}, byCombo = {}, byKind = {};
for (const f of failures) {
  const k = f.kind || "pixel";
  byKind[k] = (byKind[k] || 0) + 1;
  if (f.mode) byMode[f.mode] = (byMode[f.mode] || 0) + 1;
  if (f.ctype !== undefined) {
    const key = "ctype" + f.ctype + " depth" + f.depth;
    byCombo[key] = (byCombo[key] || 0) + 1;
  }
}
console.log("UPNG:", UPNG_PATH);
console.log("cases: %d, pass: %d, fail: %d (%dms)", manifest.length, pass, failures.length, ms);
if (failures.length) {
  console.log("by kind:", JSON.stringify(byKind));
  console.log("by filter mode:", JSON.stringify(byMode));
  console.log("by color/depth:", JSON.stringify(byCombo, null, 0));
  console.log("first 25 failures:");
  for (const f of failures.slice(0, 25)) console.log("  ", JSON.stringify(f));
  process.exit(1);
}
console.log("ALL PIXEL-EXACT");
