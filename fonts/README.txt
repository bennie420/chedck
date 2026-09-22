Place your E-13B MICR font file here. Recommended: GnuMICR (free, open source).

Download from: https://sandeen.net/GnuMICR/

After downloading, rename the font file to one of:
  - e13b.otf    (preferred)
  - e13b.ttf
  - GnuMICR.otf
  - GnuMICR.ttf

The renderer (src/renderer.py) will auto-detect and register it.

Do NOT print live check stock without this font. The fallback (Courier)
does not have the correct magnetic character shapes required for MICR reading.

MICR character shapes are defined in ANSI X9.100-20.
