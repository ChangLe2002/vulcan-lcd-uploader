"""JPEG 段顺序标准化：DQT → DHT → SOF → (可选 COM) → SOS。

动机：官方 ffmpeg 产物的顺序是 DQT、DHT、SOF0、SOS；
PIL 产物是 DQT、SOF0、DHT、SOS。设备若按固定顺序预解析，可能读错尺寸。
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, r"F:\shuchu\src")

from PIL import Image

# ---- 实现 ----


def _split_segments(data: bytes) -> tuple[bytes, list[tuple[int, bytes]], bytes]:
    """拆成 (SOI, [(marker, 段字节(含 marker 与长度))...], SOS 之后的数据)。"""
    assert data[:2] == b"\xff\xd8"
    soi = data[:2]
    segments: list[tuple[int, bytes]] = []
    index = 2
    while index < len(data) - 1:
        if data[index] != 0xFF:
            break
        marker = data[index + 1]
        if marker == 0xDA:  # SOS：之后是熵编码数据
            seglen = int.from_bytes(data[index + 2 : index + 4], "big")
            sos = data[index : index + 2 + seglen]
            rest = data[index + 2 + seglen :]
            return soi, segments, sos + rest
        if marker == 0xD9:
            return soi, segments, data[index:]
        seglen = int.from_bytes(data[index + 2 : index + 4], "big")
        segments.append((marker, data[index : index + 2 + seglen]))
        index += 2 + seglen
    return soi, segments, b""


def normalize_layout(data: bytes, *, keep_comment: bool = True) -> bytes:
    """把段顺序改为 DQT → DHT → SOF → COM → SOS，与官方一致。"""
    soi, segments, tail = _split_segments(data)
    buckets: dict[str, list[bytes]] = {
        "app": [], "dqt": [], "dht": [], "sof": [], "com": [], "other": []
    }
    for marker, seg in segments:
        if 0xE0 <= marker <= 0xEF:
            buckets["app"].append(seg)       # 保留但不放前面（官方无 APP0）
        elif marker == 0xDB:
            buckets["dqt"].append(seg)
        elif marker == 0xC4:
            buckets["dht"].append(seg)
        elif marker in (0xC0, 0xC1, 0xC2):
            buckets["sof"].append(seg)
        elif marker == 0xFE:
            buckets["com"].append(seg)
        else:
            buckets["other"].append(seg)

    out = bytearray(soi)
    for group in ("dqt", "dht", "sof"):
        for seg in buckets[group]:
            out += seg
    if keep_comment:
        for seg in buckets["com"]:
            out += seg
    for seg in buckets["other"]:
        out += seg
    out += tail
    return bytes(out)


def describe(data: bytes) -> list[str]:
    names = {0xE0: "APP0", 0xDB: "DQT", 0xC4: "DHT", 0xC0: "SOF0", 0xC2: "SOF2",
             0xDA: "SOS", 0xFE: "COM", 0xDD: "DRI"}
    out = []
    index = 2
    while index < len(data) - 3:
        if data[index] != 0xFF:
            break
        marker = data[index + 1]
        out.append(names.get(marker, hex(marker)))
        if marker == 0xDA:
            break
        index += 2 + int.from_bytes(data[index + 2 : index + 4], "big")
    return out


if __name__ == "__main__":
    from vulcan_lcd.media.encode import encode_jpeg_official
    from vulcan_lcd.media.pak import build_pak

    img = Image.new("RGB", (1024, 240), (255, 255, 255))
    from PIL import ImageDraw, ImageFont

    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 1023, 239], outline=(255, 0, 0), width=5)
    try:
        font = ImageFont.load_default(size=48)
    except TypeError:
        font = ImageFont.load_default()
    draw.text((10, 8), "LEFT", fill=(0, 0, 0), font=font)
    draw.text((884, 8), "RIGHT", fill=(0, 0, 0), font=font)
    draw.text((442, 8), "MID", fill=(0, 0, 0), font=font)

    raw = encode_jpeg_official(img, quality=85)
    print("原始顺序:", describe(raw))
    fixed = normalize_layout(raw)
    print("标准化后:", describe(fixed))
    print("尺寸变化:", len(raw), "->", len(fixed))

    pak = build_pak([fixed], interval_ms=0)
    Path(r"F:\shuchu\test_sym_order.pak").write_bytes(pak)
    print("已生成 test_sym_order.pak:", len(pak), "字节")
