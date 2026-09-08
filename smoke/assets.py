"""
Ассеты живого смоука: PNG и TXT генерируются на лету (без зависимостей),
mp4/mp3/jpg лежат файлами в smoke/assets/ (нет файла — шаг уйдёт в SKIP,
а не упадёт).
"""
import os
import struct
import zlib

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# картинка по URL для send_photo(url) — из этого же репозитория
PHOTO_URL_DEFAULT = (
    "https://raw.githubusercontent.com/mrProduktivnyy/maxibot/main/"
    "maxibot/docs/tg_to_max.png"
)

# фон квадрата по номеру шага — человек глазами отличает «фото шага 12»
# от «фото шага 14»
_PALETTE = [
    (41, 128, 185), (192, 57, 43), (39, 174, 96), (142, 68, 173),
    (243, 156, 18), (22, 160, 133), (52, 73, 94), (211, 84, 0),
]

# 7-сегментный «шрифт»: какие сегменты горят у цифры
_DIGIT_SEGMENTS = {
    "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc",
    "5": "afgcd", "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abfgcd",
}
# сегмент -> прямоугольник (x, y, w, h) в боксе цифры 60x100, толщина 12
_SEGMENT_RECTS = {
    "a": (0, 0, 60, 12),
    "b": (48, 6, 12, 44),
    "c": (48, 50, 12, 44),
    "d": (0, 88, 60, 12),
    "e": (0, 50, 12, 44),
    "f": (0, 6, 12, 44),
    "g": (0, 44, 60, 12),
}


def png(step_no: int, size: int = 240) -> bytes:
    """Квадрат сплошного цвета с крупным номером шага. Чистый Python."""
    bg = _PALETTE[step_no % len(_PALETTE)]
    white = (255, 255, 255)
    rows = [[bg] * size for _ in range(size)]

    digits = str(step_no)
    digit_w, digit_h, gap = 60, 100, 16
    total_w = len(digits) * digit_w + (len(digits) - 1) * gap
    x0 = max(0, (size - total_w) // 2)
    y0 = max(0, (size - digit_h) // 2)
    for i, digit in enumerate(digits):
        dx = x0 + i * (digit_w + gap)
        for seg in _DIGIT_SEGMENTS.get(digit, "abcdefg"):
            rx, ry, rw, rh = _SEGMENT_RECTS[seg]
            for y in range(y0 + ry, min(size, y0 + ry + rh)):
                row = rows[y]
                for x in range(dx + rx, min(size, dx + rx + rw)):
                    row[x] = white

    raw = b"".join(
        b"\x00" + b"".join(struct.pack("BBB", *px) for px in row)
        for row in rows
    )

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(
            ">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def txt(run_id: str) -> bytes:
    """Детерминированный txt — на нём строится побайтовая проверка download_file."""
    line = f"maxibot smoke {run_id}: строка для побайтовой сверки\n"
    return (line * 20).encode("utf-8")


def _file(name: str):
    path = os.path.join(ASSETS_DIR, name)
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as fh:
        return fh.read()


def mp4():
    return _file("clip.mp4")


def mp3():
    return _file("sound.mp3")


def jpg():
    return _file("photo.jpg")
