// Acceptance tests for the malformed-PNG protection chain in UPNG.js
// Run:  node test/malformed-protection.js
"use strict";
const fs = require("fs");
const path = require("path");
const zlib = require("zlib");

const UPNG_PATH = path.join(__dirname, "..", "UPNG.js");
const SAMPLES = path.join(__dirname, "samples");
fs.mkdirSync(SAMPLES, { recursive: true });

// Load UPNG.js (browser-style script, no module exports) in an isolated function scope.
const UPNG = new Function(fs.readFileSync(UPNG_PATH, "utf8") + "\n;return UPNG;")();

// ---------- PNG sample builder ----------
const crcTab = (() => {
	const t = new Uint32Array(256);
	for (let n = 0; n < 256; n++) {
		let c = n;
		for (let k = 0; k < 8; k++) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
		t[n] = c;
	}
	return t;
})();
function crc32(buf, off, len) {
	let c = 0xffffffff;
	for (let i = 0; i < len; i++) c = crcTab[(c ^ buf[off + i]) & 255] ^ (c >>> 8);
	return (c ^ 0xffffffff) >>> 0;
}
function chunk(type, data, opts = {}) {
	const out = Buffer.alloc(12 + data.length);
	out.writeUInt32BE(opts.declaredLength != null ? opts.declaredLength : data.length, 0);
	out.write(type, 4, "ascii");
	data.copy(out, 8);
	let crc = crc32(out, 4, 4 + data.length);
	if (opts.badCRC) crc ^= 0xff;                       // corrupt the stored CRC
	out.writeUInt32BE(crc >>> 0, 8 + data.length);
	return out;
}
function ihdr(w, h) {
	const b = Buffer.alloc(13);
	b.writeUInt32BE(w, 0); b.writeUInt32BE(h, 4);
	b[8] = 8; b[9] = 2;                                 // depth 8, color type 2 (RGB)
	return b;
}
const SIG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

// valid 2x2 RGB image
const W = 2, H = 2;
const raw = Buffer.alloc(H * (1 + W * 3));
for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
	const o = y * (1 + W * 3) + 1 + x * 3;
	raw[o] = 10 + x; raw[o + 1] = 20 + y; raw[o + 2] = 30;
}
const idatData = zlib.deflateSync(raw);

const validPNG     = Buffer.concat([SIG, chunk("IHDR", ihdr(W, H)), chunk("IDAT", idatData), chunk("IEND", Buffer.alloc(0))]);
const hugeDimPNG   = Buffer.concat([SIG, chunk("IHDR", ihdr(70000, 70000)), chunk("IDAT", idatData), chunk("IEND", Buffer.alloc(0))]);
const hugeWidthPNG = Buffer.concat([SIG, chunk("IHDR", ihdr(20000000, 4)), chunk("IDAT", idatData), chunk("IEND", Buffer.alloc(0))]);
const badCRCPNG    = Buffer.concat([SIG, chunk("IHDR", ihdr(W, H)), chunk("IDAT", idatData, { badCRC: true }), chunk("IEND", Buffer.alloc(0))]);
const badLenPNG    = Buffer.concat([SIG, chunk("IHDR", ihdr(W, H)), chunk("IDAT", idatData, { declaredLength: idatData.length + 1000 }), chunk("IEND", Buffer.alloc(0))]);

for (const [name, buf] of Object.entries({ valid: validPNG, "huge-dims": hugeDimPNG, "huge-width": hugeWidthPNG, "bad-crc": badCRCPNG, "bad-chunk-length": badLenPNG }))
	fs.writeFileSync(path.join(SAMPLES, name + ".png"), buf);

// ---------- assertions ----------
let passed = 0, failed = 0;
function ok(cond, name) {
	if (cond) { passed++; console.log("  PASS  " + name); }
	else { failed++; console.log("  FAIL  " + name); }
}
function throwsWith(fn, re, name) {
	try { fn(); ok(false, name + "  (no error thrown)"); }
	catch (e) { ok(e instanceof Error && re.test(e.message), name + "  ->  " + e.message); }
}
const ab = (buf) => buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.length);

console.log("\n[1] normal file: behavior unchanged");
const base = UPNG.decode(ab(validPNG));
const rgba = UPNG.toRGBA8(base);
ok(base.width === W && base.height === H, "decodes with default options (2x2)");
ok(rgba.length === 1 && rgba[0].byteLength === W * H * 4, "toRGBA8 output size correct");
const strict = UPNG.decode(ab(validPNG), { checkChunkLength: true, checkCRC: true });
ok(Buffer.from(strict.data).equals(Buffer.from(base.data)), "all checks enabled: identical pixel data");
const strictRgba = UPNG.toRGBA8(strict);
ok(Buffer.from(strictRgba[0]).equals(Buffer.from(rgba[0])), "all checks enabled: identical RGBA output");

console.log("\n[2] oversized dimension declarations rejected before allocation");
throwsWith(() => UPNG.decode(ab(hugeDimPNG)), /area 70000 x 70000 .* exceeds the limit/, "70000x70000 area bomb rejected");
throwsWith(() => UPNG.decode(ab(hugeWidthPNG)), /width 20000000 exceeds the limit/, "20000000px width rejected");
throwsWith(() => UPNG.decode(ab(validPNG), { maxPixels: 3 }), /exceeds the limit of 3 pixels/, "custom maxPixels=3 rejects 2x2 image");
ok(UPNG.decode(ab(validPNG), { maxPixels: 0, maxWidth: 0, maxHeight: 0 }).width === W, "limits can be disabled (0)");
throwsWith(() => UPNG.decode(ab(hugeWidthPNG), { maxPixels: 0 }), /width 20000000 exceeds/, "disabling maxPixels still enforces maxWidth");

console.log("\n[3] bad CRC sample");
const lax = UPNG.decode(ab(badCRCPNG));               // default: CRC not checked, legacy behavior
ok(lax.width === W && lax.height === H, "default options: decodes as before (CRC ignored)");
throwsWith(() => UPNG.decode(ab(badCRCPNG), { checkCRC: true }), /CRC check failed for chunk "IDAT"/, "checkCRC:true rejects bad IDAT CRC");

console.log("\n[4] chunk length beyond end of file");
throwsWith(() => UPNG.decode(ab(badLenPNG), { checkChunkLength: true }), /declares a length of .* but only .* data bytes remain/, "checkChunkLength:true rejects oversized declared length");
throwsWith(() => UPNG.decode(ab(badLenPNG), { checkCRC: true }), /declares a length of/, "checkCRC implies the length sanity check");

console.log("\n[5] global configuration via UPNG.decodeLimits");
ok(UPNG.decodeLimits && UPNG.decodeLimits.maxPixels === (1 << 28), "UPNG.decodeLimits exposed with defaults");
UPNG.decodeLimits.maxPixels = 3;
throwsWith(() => UPNG.decode(ab(validPNG)), /exceeds the limit of 3 pixels/, "global limit applies");
UPNG.decodeLimits.maxPixels = 1 << 28;                // restore
ok(UPNG.decode(ab(validPNG)).width === W, "restored default decodes again");

console.log("\n" + passed + " passed, " + failed + " failed");
process.exit(failed ? 1 : 0);
