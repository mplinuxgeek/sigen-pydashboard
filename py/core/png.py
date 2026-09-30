"""PNG encoder for RGB565 framebuffers, fast enough to run on the board.

MicroPython's built-in zlib compressor is very slow on flat-colour UI rows, so this module has its
own deflate encoder written in viper: fixed Huffman codes plus two kinds of match - "same pixel as
the previous one" (distance 3) and "same as the pixel above" (distance = row length). That is
ideal for UI screenshots (large flat areas): a full 1024x600 frame becomes tens of KB.
"""
import asyncio
import binascii
import micropython
import struct

# ---- fixed-Huffman lookup tables (built once) ------------------------------------------------
_LBASE = (3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258)
_LEXTRA = (0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0)


def _rev(code, nbits):
    r = 0
    for _ in range(nbits):
        r = (r << 1) | (code & 1)
        code >>= 1
    return r


_tables = None


def _build_tables():
    import array
    lit = array.array("H", [0] * 256)           # reversed literal codes (8 or 9 bits, chosen by value)
    for v in range(256):
        lit[v] = _rev(0x30 + v, 8) if v < 144 else _rev(0x190 + v - 144, 9)
    lcode = array.array("H", [0] * 259)         # reversed length-symbol code
    lnbits = bytearray(259)                     # its bit count (7 or 8)
    lebits = bytearray(259)                     # number of extra bits
    leval = bytearray(259)                      # extra bits value
    for L in range(3, 259):
        i = len(_LBASE) - 1
        while _LBASE[i] > L:
            i -= 1
        sym = 257 + i
        if sym <= 279:
            lcode[L], lnbits[L] = _rev(sym - 256, 7), 7
        else:
            lcode[L], lnbits[L] = _rev(0xC0 + sym - 280, 8), 8
        lebits[L] = _LEXTRA[i]
        leval[L] = L - _LBASE[i]
    return lit, lcode, lnbits, lebits, leval


_DBASE = (1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073,
          4097, 6145, 8193, 12289, 16385, 24577)
_DEXTRA = (0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13)


def _dist_code(d):
    """(reversed 5-bit fixed-Huffman distance code, extra bit count, extra value) for match distance d."""
    c = len(_DBASE) - 1
    while _DBASE[c] > d:
        c -= 1
    return _rev(c, 5), _DEXTRA[c], d - _DBASE[c]


@micropython.viper
def _row565_to_rgb(src: ptr8, dst: ptr8, npx: int):
    # dst[0] is the PNG filter byte (left 0); pixels are written from dst[1]
    for i in range(npx):
        v = int(src[2 * i]) | (int(src[2 * i + 1]) << 8)
        r = (v >> 11) & 31
        g = (v >> 5) & 63
        b = v & 31
        dst[3 * i + 1] = (r << 3) | (r >> 2)
        dst[3 * i + 2] = (g << 2) | (g >> 4)
        dst[3 * i + 3] = (b << 3) | (b >> 2)


@micropython.viper
def _adler_update(src: ptr8, start: int, n: int, a0: int, b0: int) -> int:
    """Adler-32 running update over src[start:start+n]; state in/out as a (b << 16) | a int."""
    a = a0
    b = b0
    i = start
    stop = start + n
    while i < stop:
        end = i + 5552
        if end > stop:
            end = stop
        while i < end:
            a += int(src[i])
            b += a
            i += 1
        a %= 65521
        b %= 65521
    return (b << 16) | a


@micropython.viper
def _deflate_strip(src: ptr8, base: int, n: int, abs0: int, dst: ptr8, rowlen: int, rdrev: int, rdeb: int, rdev: int,
                   lit: ptr16, lcode: ptr16, lnbits: ptr8, lebits: ptr8, leval: ptr8, st: ptr32) -> int:
    """Fixed-Huffman deflate of src[base:base+n] (which sits at absolute stream offset abs0; for later strips the
    row before it is present at src[base-rowlen:base]). Bit-buffer state is carried in st[0] (bits), st[1] (count)."""
    o = 0
    bb = int(st[0])
    bc = int(st[1])
    i = base
    stop = base + n
    while i < stop:
        best = 0
        bd = 0
        ai = abs0 + i - base
        if ai >= 3:
            lim = stop - i
            if lim > 258:
                lim = 258
            k = 0
            while k < lim and src[i + k] == src[i + k - 3]:
                k += 1
            best = k
            bd = 3
            if ai >= rowlen:
                k2 = 0
                while k2 < lim and src[i + k2] == src[i + k2 - rowlen]:
                    k2 += 1
                if k2 > best:
                    best = k2
                    bd = rowlen
        if best >= 3:
            bb |= int(lcode[best]) << bc
            bc += int(lnbits[best])
            while bc >= 8:
                dst[o] = bb & 255
                o += 1
                bb >>= 8
                bc -= 8
            eb = int(lebits[best])
            if eb:
                bb |= int(leval[best]) << bc
                bc += eb
                while bc >= 8:
                    dst[o] = bb & 255
                    o += 1
                    bb >>= 8
                    bc -= 8
            if bd == 3:
                bb |= 8 << bc          # distance code 2 (= distance 3), 5 bits reversed
                bc += 5
            else:
                bb |= rdrev << bc      # distance code for the row-above distance (reversed 5 bits) ...
                bc += 5
                bb |= rdev << bc       # ... then its extra bits
                bc += rdeb
            while bc >= 8:
                dst[o] = bb & 255
                o += 1
                bb >>= 8
                bc -= 8
            i += best
        else:
            v = int(src[i])
            bb |= int(lit[v]) << bc
            if v < 144:
                bc += 8
            else:
                bc += 9
            while bc >= 8:
                dst[o] = bb & 255
                o += 1
                bb >>= 8
                bc -= 8
            i += 1
    st[0] = bb
    st[1] = bc
    return o


def _chunk(tag, data):
    crc = binascii.crc32(data, binascii.crc32(tag)) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


ROWS_PER_STRIP = 24


async def encode_rgb565(fb, w, h):
    """PNG bytes for an RGB565 little-endian framebuffer. Works in strips of ROWS_PER_STRIP rows (the previous
    row is kept for the row-above match), so it needs well under 200 KB of contiguous heap for any screen size."""
    import array
    global _tables
    if _tables is None:
        _tables = _build_tables()
    lit, lcode, lnbits, lebits, leval = _tables
    rowlen = 1 + 3 * w
    rdrev, rdeb, rdev = _dist_code(rowlen)
    buf = bytearray(rowlen * (ROWS_PER_STRIP + 1))
    mv = memoryview(buf)
    out = bytearray(rowlen * ROWS_PER_STRIP * 9 // 8 + 256)
    mvfb = memoryview(fb)
    stride = 2 * w
    st = array.array("i", [3, 3])              # bit buffer: block header BFINAL=1, BTYPE=01 (fixed Huffman)
    idat = bytearray(b"\x78\x01")
    adler = 1                                  # (b << 16) | a
    prev_rows = 0
    for y0 in range(0, h, ROWS_PER_STRIP):
        r = min(ROWS_PER_STRIP, h - y0)
        base = rowlen if y0 else 0
        if y0:
            buf[0:rowlen] = buf[base + (prev_rows - 1) * rowlen:base + prev_rows * rowlen]
        for k in range(r):
            y = y0 + k
            _row565_to_rgb(mvfb[y * stride:(y + 1) * stride], mv[base + k * rowlen:base + (k + 1) * rowlen], w)
        adler = _adler_update(buf, base, r * rowlen, adler & 0xFFFF, (adler >> 16) & 0xFFFF) & 0xFFFFFFFF
        m = _deflate_strip(buf, base, r * rowlen, y0 * rowlen, out, rowlen, rdrev, rdeb, rdev,
                           lit, lcode, lnbits, lebits, leval, st)
        idat += memoryview(out)[:m]
        prev_rows = r
        await asyncio.sleep_ms(0)
    bb, bc = st[0], st[1] + 7                  # end-of-block symbol (256): seven zero bits
    while bc >= 8:
        idat.append(bb & 255)
        bb >>= 8
        bc -= 8
    if bc > 0:
        idat.append(bb & 255)
    idat += struct.pack(">I", adler)
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", bytes(idat))
            + _chunk(b"IEND", b""))
