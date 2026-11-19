# UPNG.js interop regression — sample matrix results

| sample | decode (UPNG vs reference pixels) | roundtrip (decode→encode→decode) | encode (UPNG → Pillow) |
|---|---|---|---|
| gray1 | PASS | PASS | PASS |
| gray2 | PASS | PASS | PASS |
| gray4 | PASS | PASS | PASS |
| gray8 | PASS | PASS | PASS |
| gray16 | PASS | PASS | PASS |
| gray4_trns | PASS | PASS | PASS |
| gray8_trns | PASS | PASS | PASS |
| gray16_trns | PASS | PASS | PASS |
| gray1_w8 | PASS | PASS | PASS |
| gray1_w7 | PASS | PASS | PASS |
| rgb8 | PASS | PASS | PASS |
| rgb16 | PASS | PASS | PASS |
| rgb8_trns | PASS | PASS | PASS |
| rgb16_trns | PASS | PASS | PASS |
| rgb8_filters | PASS | PASS | PASS |
| pal1 | PASS | PASS | PASS |
| pal2 | PASS | PASS | PASS |
| pal4 | PASS | PASS | PASS |
| pal8 | PASS | PASS | PASS |
| pal4_trns | PASS | PASS | PASS |
| pal8_trns | PASS | PASS | PASS |
| ga8 | PASS | PASS | PASS |
| ga16 | PASS | PASS | PASS |
| rgba8 | PASS | PASS | PASS |
| rgba16 | PASS | PASS | PASS |
| rgba8_1x1 | PASS | PASS | PASS |
| pil_l | PASS | PASS | PASS |
| pil_i16 | PASS | PASS | PASS |
| pil_rgb | PASS | PASS | PASS |
| pil_rgba | PASS | PASS | PASS |
| pil_p | PASS | PASS | PASS |
| ll_gray8 | - | - | PASS |
| ll_gray16 | - | - | PASS |
| ll_ga8 | - | - | PASS |
| ll_ga16 | - | - | PASS |
| ll_rgb8 | - | - | PASS |
| ll_rgb16 | - | - | PASS |
| ll_rgba8 | - | - | PASS |
| ll_rgba16 | - | - | PASS |
| quantize64 | PASS | - | PASS |

**40/40 samples fully green**
