# -*- coding: utf-8 -*-
"""生成截图录屏助手的图标（16/32/48/256）。"""
from PIL import Image, ImageDraw

SZ = [16, 32, 48, 256]
OUT = r"D:\21821\products\sniptool\icon.ico"


def draw(size):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # 圆角方形底
    r = max(2, size // 5)
    d.rounded_rectangle([1, 1, size - 2, size - 2], radius=r, fill=(33, 147, 255, 255))
    # 相机取景框四角
    t = max(2, size // 8)      # 角的臂长
    w = max(2, size // 10)     # 角的线宽
    m = max(3, size // 6)      # 边距
    for (sx, sy) in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        x0 = size // 2 if sx < 0 else m
        y0 = size // 2 if sy < 0 else m
        x1 = m if sx < 0 else size - m
        y1 = m if sy < 0 else size - m
        d.line([(x0, y0), (x0, y0 + sy * t)], fill=(255, 255, 255, 255), width=w)
        d.line([(x0, y0), (x0 + sx * t, y0)], fill=(255, 255, 255, 255), width=w)
    return im


def main():
    ims = [draw(s) for s in SZ]
    ims[0].save(OUT, sizes=[(s, s) for s in SZ])
    print("written", OUT)


if __name__ == "__main__":
    main()
