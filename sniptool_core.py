# -*- coding: utf-8 -*-
"""
截图录屏助手 —— 核心逻辑（不依赖 GUI，可独立测试）

功能域：
  · 截图：全屏 / 区域 / 窗口 / 延时
  · 标注：矩形、箭头、直线、文字、马赛克、高亮、裁剪
  · 拼接：纵向 / 横向 / 自动去重（长截图）
  · 录屏：GIF（区域 + 时长 + 帧率）
  · 剪贴板：图片写入 / 读取
  · 长截图：窗口自动滚动 + 拼接

设计约定：
  · 所有 annotate_* / crop_image / stitch_* 都**不修改入参**，返回新图，
    方便 GUI 做撤销/重做栈。
  · 所有 Windows 专有调用（ctypes user32/gdi32）都包在 try 里，
    非 Windows 环境 import 本模块不报错，只是截图函数不可用。
"""
import ctypes
import datetime as _dt
import os
import time
from ctypes import POINTER, byref, c_long, c_void_p, create_string_buffer, create_unicode_buffer
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageGrab

try:  # Pillow >= 9.1 推荐写法，老版本回退
    _LANCZOS = Image.Resampling.LANCZOS
    _NEAREST = Image.Resampling.NEAREST
except AttributeError:  # pragma: no cover
    _LANCZOS = Image.LANCZOS
    _NEAREST = Image.NEAREST

APP_NAME = "截图录屏助手"
APP_VERSION = "1.0.0"

# 输出格式（截图默认 PNG 无损）
OUT_FORMATS = [("PNG", "png"), ("JPG", "jpg"), ("BMP", "bmp"), ("GIF", "gif")]
OUT_EXT = {v: k for k, v in OUT_FORMATS}

# 标注预设颜色（RGB）
COLORS = [
    ("红", (230, 57, 70)),
    ("黄", (255, 196, 0)),
    ("蓝", (33, 147, 255)),
    ("绿", (32, 191, 107)),
    ("白", (255, 255, 255)),
    ("黑", (23, 23, 23)),
]
COLOR_NAMES = [c[0] for c in COLORS]

# 录屏帧率档位
FPS_PRESETS = [("4 帧/秒", 4), ("8 帧/秒", 8), ("12 帧/秒", 12), ("15 帧/秒", 15)]


# ============================================================================
# 通用小工具
# ============================================================================
def human_size(n):
    """字节数转可读大小（与本工作区其它产品保持同一口径）。"""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            if unit == "B":
                return f"{int(n)} {unit}" if float(n).is_integer() else f"{n} {unit}"
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def unique_path(path: Path) -> Path:
    """避免覆盖同名文件：name.png → name_1.png"""
    path = Path(path)
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(1, 10000):
        cand = path.with_name(f"{stem}_{i}{suffix}")
        if not cand.exists():
            return cand
    return path


def ensure_dir(path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_font(size):
    """找一个可用的中文字体；找不到就退回默认字体。"""
    candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def timestamp_name(prefix="截图", ext="png", when=None):
    """生成带时间戳的文件名：截图_20261022_193012.png"""
    ts = (when or _dt.datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{ts}.{ext.lstrip('.')}"


def save_capture(im, out_dir, name=None, ext="png", prefix="截图"):
    """保存截图，自动建目录、自动避免重名。返回最终路径。"""
    ensure_dir(out_dir)
    if name is None:
        name = timestamp_name(prefix, ext)
    elif not Path(name).suffix:
        name = f"{name}.{ext.lstrip('.')}"
    path = unique_path(Path(out_dir) / name)
    im.save(path)
    return path


def _to_rgb(im):
    """把任意模式转成 RGB（透明区域铺白底），保证 JPG/标注一致。"""
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        return bg
    if im.mode != "RGB":
        return im.convert("RGB")
    return im


def _norm_box(box, size):
    """把 box 规范成 (left, top, right, bottom) 且落在图内。"""
    w, h = size
    left, top, right, bottom = box
    left = max(0, min(w, int(round(left))))
    top = max(0, min(h, int(round(top))))
    right = max(0, min(w, int(round(right))))
    bottom = max(0, min(h, int(round(bottom))))
    if right < left:
        left, right = right, left
    if bottom < top:
        top, bottom = bottom, top
    return (left, top, right, bottom)


# ============================================================================
# 标注（全部返回新图）
# ============================================================================
def annotate_rect(im, box, color=(230, 57, 70), width=3, fill=None):
    out = im.copy()
    d = ImageDraw.Draw(out)
    left, top, right, bottom = _norm_box(box, im.size)
    if fill is not None:
        d.rectangle([left, top, right, bottom], fill=fill, outline=color, width=max(1, width))
    else:
        d.rectangle([left, top, right, bottom], outline=color, width=max(1, width))
    return out


def annotate_line(im, p1, p2, color=(230, 57, 70), width=3):
    out = im.copy()
    d = ImageDraw.Draw(out)
    d.line([p1, p2], fill=color, width=max(1, width))
    # 端点画小圆，避免细线看不清
    r = max(2, width // 2)
    d.ellipse([p1[0] - r, p1[1] - r, p1[0] + r, p1[1] + r], fill=color)
    d.ellipse([p2[0] - r, p2[1] - r, p2[0] + r, p2[1] + r], fill=color)
    return out


def annotate_arrow(im, p1, p2, color=(230, 57, 70), width=3, head=14):
    """带箭头头的直线。"""
    out = im.copy()
    d = ImageDraw.Draw(out)
    d.line([p1, p2], fill=color, width=max(1, width))
    # 计算箭头两翼
    import math
    x1, y1 = p1
    x2, y2 = p2
    ang = math.atan2(y2 - y1, x2 - x1)
    h = max(6.0, float(head))
    span = math.radians(28)
    for sign in (1, -1):
        a = ang + math.pi + sign * span
        d.line([(x2, y2), (x2 + h * math.cos(a), y2 + h * math.sin(a))],
               fill=color, width=max(1, width))
    r = max(2, width // 2)
    d.ellipse([x1 - r, y1 - r, x1 + r, y1 + r], fill=color)
    return out


def annotate_text(im, pos, text, color=(230, 57, 70), font=None, size=24,
                  bg=True, padding=6):
    """在 pos（左上角）画文字；bg=True 时画半透明底，保证深底浅字可读。"""
    out = im.convert("RGBA")
    if font is None:
        font = load_font(size)
    d = ImageDraw.Draw(out)
    x, y = pos
    bbox = d.textbbox((x, y), text, font=font)
    if bg:
        d.rectangle([bbox[0] - padding, bbox[1] - padding,
                     bbox[2] + padding, bbox[3] + padding], fill=(0, 0, 0, 110))
    d.text((x, y), text, font=font, fill=color + (255,))
    return out.convert(im.mode) if im.mode != "RGBA" else out


def annotate_mosaic(im, box, block=10):
    """马赛克（像素化）。block 越大越糊。"""
    out = im.copy()
    left, top, right, bottom = _norm_box(box, im.size)
    if right - left < 2 or bottom - top < 2:
        return out
    w = right - left
    h = bottom - top
    bw = max(1, int(w / max(1, block)))
    bh = max(1, int(h / max(1, block)))
    region = out.crop((left, top, right, bottom))
    small = region.resize((bw, bh), _NEAREST)
    out.paste(small.resize((w, h), _NEAREST), (left, top))
    return out


def annotate_blur(im, box, radius=8):
    """高斯模糊遮挡。"""
    out = im.copy()
    left, top, right, bottom = _norm_box(box, im.size)
    if right - left < 2 or bottom - top < 2:
        return out
    region = out.crop((left, top, right, bottom)).filter(ImageFilter_gaussian(radius))
    out.paste(region, (left, top))
    return out


def ImageFilter_gaussian(radius):
    from PIL import ImageFilter
    return ImageFilter.GaussianBlur(radius)


def annotate_highlight(im, box, color=(255, 235, 59), alpha=90):
    """半透明高亮（记号笔）。"""
    out = im.convert("RGBA")
    left, top, right, bottom = _norm_box(box, im.size)
    overlay = Image.new("RGBA", out.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rectangle([left, top, right, bottom], fill=color + (alpha,))
    out = Image.alpha_composite(out, overlay)
    return out.convert(im.mode) if im.mode != "RGBA" else out


def crop_image(im, box):
    """按 box 裁剪，返回新图。box 越界自动收敛到图内。"""
    left, top, right, bottom = _norm_box(box, im.size)
    if right - left < 1 or bottom - top < 1:
        return im.copy()
    return im.crop((left, top, right, bottom))


# ============================================================================
# 拼接
# ============================================================================
def stitch_vertical(images, gap=0, background=(255, 255, 255)):
    """把多张图纵向拼成一张长图。"""
    imgs = [_to_rgb(im) for im in images if im is not None]
    if not imgs:
        raise ValueError("stitch_vertical: 没有可拼接的图片")
    w = max(im.size[0] for im in imgs)
    total_h = sum(im.size[1] for im in imgs) + gap * (len(imgs) - 1)
    canvas = Image.new("RGB", (w, total_h), background)
    y = 0
    for im in imgs:
        canvas.paste(im, (0, y))
        y += im.size[1] + gap
    return canvas


def stitch_horizontal(images, gap=0, background=(255, 255, 255)):
    """把多张图横向拼成一张宽图。"""
    imgs = [_to_rgb(im) for im in images if im is not None]
    if not imgs:
        raise ValueError("stitch_horizontal: 没有可拼接的图片")
    h = max(im.size[1] for im in imgs)
    total_w = sum(im.size[0] for im in imgs) + gap * (len(imgs) - 1)
    canvas = Image.new("RGB", (total_w, h), background)
    x = 0
    for im in imgs:
        canvas.paste(im, (x, 0))
        x += im.size[0] + gap
    return canvas


def stitch_vertical_dedupe(images, tol=12.0, max_overlap_ratio=0.9):
    """纵向拼接并自动去掉相邻图的重复行（长截图滚动拼接）。

    原理：连续两次截屏有重叠区域。从最大可能重叠开始往下试，
    找到「重叠行平均差 < tol」的最大重叠量，把后一张图裁掉重叠部分再拼。
    """
    import numpy as np
    imgs = [_to_rgb(im) for im in images if im is not None]
    if not imgs:
        raise ValueError("stitch_vertical_dedupe: 没有可拼接的图片")
    if len(imgs) == 1:
        return imgs[0]

    out = [imgs[0]]
    for prev, cur in zip(imgs, imgs[1:]):
        ph = prev.size[1]
        ch = cur.size[1]
        max_ov = min(ph, ch)
        max_ov = min(max_ov, int(max(ch, 1) * max_overlap_ratio))
        best = 0
        a = np.asarray(prev.convert("L"), dtype=np.int16)
        b = np.asarray(cur.convert("L"), dtype=np.int16)
        for ov in range(max_ov, 0, -1):
            top = a[ph - ov:]
            bottom = b[:ov]
            if top.shape != bottom.shape:
                continue
            diff = float(np.abs(top.astype(np.int32) - bottom.astype(np.int32)).mean())
            if diff <= tol:
                best = ov
                break
        if best > 0:
            cur = cur.crop((0, best, cur.size[0], ch))
        out.append(cur)
    return stitch_vertical(out)


# ============================================================================
# 截图（Windows）
# ============================================================================
class CaptureStopped(Exception):
    """长截图被用户主动停止；必须穿透 capture_window_scrolled 的宽 except。"""


def _user32():
    return ctypes.windll.user32


def virtual_screen_rect():
    """虚拟桌面（所有显示器）矩形 (x, y, w, h)。"""
    u = _user32()
    x = u.GetSystemMetrics(78)   # SM_XVIRTUALSCREEN
    y = u.GetSystemMetrics(79)   # SM_YVIRTUALSCREEN
    w = u.GetSystemMetrics(80)   # SM_CXVIRTUALSCREEN
    h = u.GetSystemMetrics(81)   # SM_CYVIRTUALSCREEN
    return (x, y, w, h)


def _monitor_enum_proc():
    return ctypes.WINFUNCTYPE(ctypes.c_bool, c_void_p, c_void_p)


def monitor_rects():
    """所有显示器矩形列表（屏幕坐标）。非 Windows 返回空列表。"""
    try:
        u = _user32()
        rects = []

        @_monitor_enum_proc()
        def _cb(hmonitor, hdc, lprc, lparam):
            rc = lprc.contents
            rects.append((rc.left, rc.top, rc.right, rc.bottom))
            return True

        u.EnumDisplayMonitors(None, None, _cb, 0)
        return rects
    except Exception:
        return []


def primary_monitor_rect():
    """主显示器矩形；EnumDisplayMonitors 失败时退回虚拟桌面左上。"""
    rects = monitor_rects()
    if rects:
        # GetMonitorInfoW 能给出 IsPrimary，但这里简化：返回第一个（通常即主屏）
        return rects[0]
    x, y, w, h = virtual_screen_rect()
    return (x, y, x + w, y + h)


def capture_full(monitor=None):
    """截全屏。monitor=None 截整个虚拟桌面；传矩形则只截该显示器。"""
    vx, vy, vw, vh = virtual_screen_rect()
    if vw <= 0 or vh <= 0:
        # 某些会话 GetSystemMetrics 返回退化值；退回让 ImageGrab 自己取
        im = ImageGrab.grab(all_screens=True)
    else:
        im = ImageGrab.grab(bbox=(vx, vy, vx + vw, vy + vh), all_screens=True)
    if monitor is None:
        return im
    l, t, r, b = monitor
    # 设备像素比：ImageGrab 返回物理像素，显示器矩形通常是物理像素
    return im.crop((l - vx, t - vy, r - vx, b - vy))


def capture_region(box):
    """截指定屏幕区域。box = (left, top, right, bottom)。"""
    l, t, r, b = box
    return ImageGrab.grab(bbox=(l, t, r, b), all_screens=True)


def cursor_pos():
    pt = POINTER(c_long * 2)()
    # 用 POINT 结构
    class _POINT(ctypes.Structure):
        _fields_ = [("x", c_long), ("y", c_long)]
    p = _POINT()
    _user32().GetCursorPos(byref(p))
    return (p.x, p.y)


def _rect_of(hwnd):
    """GetWindowRect 返回的是 4 个 LONG，必须用 RECT 结构接收（不能直接解包 int）。"""
    class _RECT(ctypes.Structure):
        _fields_ = [("left", c_long), ("top", c_long),
                    ("right", c_long), ("bottom", c_long)]
    rc = _RECT()
    if _user32().GetWindowRect(hwnd, byref(rc)):
        return (rc.left, rc.top, rc.right, rc.bottom)
    return None


def enum_windows():
    """枚举可见顶层窗口：[(hwnd, title, (l,t,r,b)), ...]"""
    try:
        u = _user32()
        out = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, c_void_p, c_void_p)
        def _cb(hwnd, lparam):
            if not u.IsWindowVisible(hwnd):
                return True
            n = u.GetWindowTextLengthW(hwnd)
            if n == 0:
                return True
            buf = create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, buf, n + 1)
            title = buf.value
            rect = _rect_of(hwnd)
            if rect is None:
                return True
            l, t, r, b = rect
            if r - l < 20 or b - t < 20:
                return True
            out.append((hwnd, title, (l, t, r, b)))
            return True

        u.EnumWindows(_cb, 0)
        return out
    except Exception:
        return []


def window_by_title(substr, exact=False):
    """按标题查找窗口，返回 (hwnd, title, rect) 或 None。"""
    if not substr:
        return None
    cands = [w for w in enum_windows() if substr.lower() in (w[1] or "").lower()]
    if not cands:
        return None
    if exact:
        cands = [w for w in cands if w[1] == substr]
        if not cands:
            return None
    # 标题越短越可能是目标窗口（排除 "... - 记事本" 这类父串）
    cands.sort(key=lambda w: len(w[1]))
    return cands[0]


def capture_window(hwnd, client=True):
    """截指定窗口。client=True 只截客户区（不含标题栏）。"""
    try:
        u = _user32()

        class _RECT(ctypes.Structure):
            _fields_ = [("left", c_long), ("top", c_long),
                        ("right", c_long), ("bottom", c_long)]

        rc = _RECT()
        if client and u.GetClientRect(hwnd, byref(rc)):
            class _POINT(ctypes.Structure):
                _fields_ = [("x", c_long), ("y", c_long)]
            p = _POINT(rc.left, rc.top)
            u.ClientToScreen(hwnd, byref(p))
            box = (p.x, p.y, p.x + (rc.right - rc.left), p.y + (rc.bottom - rc.top))
        else:
            rect = _rect_of(hwnd)
            if rect is None:
                return None
            box = rect
        box = tuple(int(v) for v in box)
        if box[2] - box[0] < 1 or box[3] - box[1] < 1:
            return None
        return capture_region(box)
    except Exception:
        return None


def delayed_capture(delay, box=None, monitor=None):
    """延时截图：等 delay 秒后截。delay<=0 立即。"""
    if delay and delay > 0:
        time.sleep(delay)
    if box is not None:
        return capture_region(box)
    return capture_full(monitor)


# ============================================================================
# 录屏（GIF）
# ============================================================================
def gif_frame_count(duration_sec, fps):
    """时长(秒) + 帧率 → 帧数（至少 1 帧）。"""
    if duration_sec is None or duration_sec <= 0:
        return 1
    if fps is None or fps <= 0:
        fps = 8
    return max(1, int(round(duration_sec * fps)))


def save_gif_from_frames(frames, out_path, duration_ms=125, loop=0, size=None,
                         max_colors=256):
    """把一列 PIL 图存成 GIF。"""
    frames = [f for f in frames if f is not None]
    if not frames:
        raise ValueError("save_gif_from_frames: 没有帧")
    prepared = []
    for f in frames:
        if size and f.size != size:
            f = f.resize(size, _LANCZOS)
        if f.mode != "P":
            f = f.convert("RGB").quantize(colors=max_colors, method=Image.MEDIANCUT)
        prepared.append(f)
    out_path = Path(out_path)
    ensure_dir(out_path.parent)
    prepared[0].save(
        out_path, save_all=True, append_images=prepared[1:],
        duration=duration_ms, loop=loop, optimize=True,
        transparency=None,
    )
    return out_path


def record_gif(frame_source, duration_sec, fps, out_path, size=None,
               max_colors=256, loop=0, on_frame=None):
    """录制 GIF。

    frame_source: 可调用，无参，返回当前帧 PIL 图（由调用方决定截哪个区域）。
    返回输出路径。
    """
    n = gif_frame_count(duration_sec, fps)
    interval = 1.0 / fps if fps else 0.125
    frames = []
    for i in range(n):
        if on_frame:
            on_frame(i, n)
        im = frame_source()
        if im is None:
            continue
        if size and im.size != size:
            im = im.resize(size, _LANCZOS)
        frames.append(im)
        if i < n - 1:
            time.sleep(interval)
    if not frames:
        raise ValueError("record_gif: 没有采集到任何帧")
    duration_ms = int(round(interval * 1000))
    return save_gif_from_frames(frames, out_path, duration_ms=duration_ms,
                                loop=loop, size=None, max_colors=max_colors)


# ============================================================================
# 剪贴板
# ============================================================================
def copy_image_to_clipboard(im):
    """把 PIL 图写入 Windows 剪贴板（CF_DIB）。成功返回 True。"""
    try:
        u = ctypes.windll.user32
        g = ctypes.windll.gdi32
        k = ctypes.windll.kernel32
        im = _to_rgb(im)
        w, h = im.size
        buf = im.tobytes()  # RGB
        # CF_DIB 需要 BGRA 且自上而下
        rgb = bytearray(im.tobytes())
        bgra = bytearray(len(rgb) // 3 * 4)
        for i in range(0, len(rgb), 3):
            bgra[i * 4 // 3] = rgb[i + 2]
            bgra[i * 4 // 3 + 1] = rgb[i + 1]
            bgra[i * 4 // 3 + 2] = rgb[i]
            bgra[i * 4 // 3 + 3] = 255
        header_size = 40
        total = header_size + len(bgra)
        hglobal = k.GlobalAlloc(0x2002, total)  # GMEM_MOVEABLE | GMEM_ZEROINIT
        if not hglobal:
            return False
        ptr = k.GlobalLock(hglobal)
        ctypes.memmove(ptr, create_string_buffer(
            ctypes.c_uint32(header_size).to_bytes(4, "little") +
            ctypes.c_int32(w).to_bytes(4, "little") +
            ctypes.c_int32(-h).to_bytes(4, "little") +
            ctypes.c_uint16(1).to_bytes(2, "little") +
            ctypes.c_uint16(32).to_bytes(2, "little") +
            ctypes.c_uint32(0).to_bytes(4, "little") +
            ctypes.c_uint32(len(bgra)).to_bytes(4, "little") +
            b'\x00' * 20
        ), header_size)
        ctypes.memmove(ptr + header_size, bytes(bgra), len(bgra))
        k.GlobalUnlock(hglobal)
        if not u.OpenClipboard(None):
            return False
        try:
            u.EmptyClipboard()
            handle = u.SetClipboardData(8, hglobal, None)  # CF_DIB = 8
        finally:
            u.CloseClipboard()
        return bool(handle)
    except Exception:
        return False


def image_from_clipboard():
    """从剪贴板读取图片；没有图片返回 None。"""
    try:
        data = ImageGrab.grabclipboard()
        if isinstance(data, list) and data:
            return Image.open(data[0])
        if isinstance(data, Image.Image):
            return data
    except Exception:
        pass
    return None


# ============================================================================
# 长截图：窗口自动滚动 + 拼接
# ============================================================================
def scroll_window_px(hwnd, delta_px):
    """让窗口内容向下滚动 delta_px 像素（发 WM_MOUSEWHEEL）。

    返回是否发送成功。WHEEL_UNIT=120 对应一个鼠标轮齿（约 30-40 像素）。
    """
    try:
        u = _user32()
        # 找到鼠标位置上的窗口（把窗口设到前台后，发给它的父）
        WM_MOUSEWHEEL = 0x020A
        WHEEL_DELTA = 120
        notches = int(round(delta_px / 30.0))
        if notches == 0:
            notches = 1 if delta_px > 0 else -1
        u.SetForegroundWindow(hwnd)
        pt = cursor_pos()
        # PostMessageW 到窗口（含子控件）
        sent = 0
        for _ in range(abs(notches)):
            wparam = (WHEEL_DELTA * (1 if delta_px > 0 else -1)) & 0xFFFF
            wparam |= (0xFFFF << 16)  # high word = mouse keys state
            u.SendMessageW(hwnd, WM_MOUSEWHEEL, wparam, 0)
            sent += 1
        return sent > 0
    except Exception:
        return False


def capture_window_scrolled(hwnd, out_dir, prefix="长截图", ext="png",
                            step_px=600, max_steps=30, settle=0.5,
                            on_progress=None):
    """窗口自动滚动长截图：反复截客户区并去重拼接。

    返回 (最终图片, 路径) 或 (None, None)。
    """
    captures = []
    try:
        im = capture_window(hwnd, client=True)
        if im is None:
            return None, None
        captures.append(im)
        for i in range(max_steps):
            scroll_window_px(hwnd, step_px)
            time.sleep(settle)
            nxt = capture_window(hwnd, client=True)
            if nxt is None:
                break
            # 判断是否已经到底部：与上一帧几乎相同 → 停止
            if _frames_similar(captures[-1], nxt, tol=3.0):
                break
            captures.append(nxt)
            if on_progress:
                on_progress(len(captures), max_steps)
    except CaptureStopped:
        raise
    except Exception:
        pass

    if not captures:
        return None, None
    if len(captures) == 1:
        stitched = captures[0]
    else:
        stitched = stitch_vertical_dedupe(captures)
    path = save_capture(stitched, out_dir, prefix=prefix, ext=ext)
    return stitched, path


def _frames_similar(a, b, tol=3.0):
    """两张图平均灰度差 < tol 视为相同（用于判断滚到底）。"""
    import numpy as np
    if a.size != b.size:
        return False
    try:
        diff = float(np.abs(np.asarray(a.convert("L"), dtype=np.int16) -
                            np.asarray(b.convert("L"), dtype=np.int16)).mean())
        return diff < tol
    except Exception:
        return False


# ============================================================================
# 批处理：对一个目录里已有的图片做标注/裁剪（让工具也能处理存量图）
# ============================================================================
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp")


def list_images(folder):
    return [p for p in Path(folder).iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS]


def process_dir(src_dir, out_dir, op="mosaic", box=None, color=(230, 57, 70),
                width=3, block=10, text="", prefix="处理", ext=None):
    """对目录内图片批量执行一种标注操作，返回 (成功数, 失败数)。"""
    ensure_dir(out_dir)
    ok = fail = 0
    for p in list_images(src_dir):
        try:
            with Image.open(p) as im:
                im = _to_rgb(im)
                if op == "mosaic":
                    out = annotate_mosaic(im, box or (10, 10, max(20, im.size[0] // 3),
                                                      max(20, im.size[1] // 3)), block=block)
                elif op == "rect":
                    out = annotate_rect(im, box or (10, 10, im.size[0] - 10, im.size[1] - 10),
                                        color=color, width=width)
                elif op == "text":
                    out = annotate_text(im, (20, 20), text or "示例文字")
                elif op == "crop":
                    out = crop_image(im, box or (0, 0, im.size[0], im.size[1]))
                else:
                    raise ValueError(f"未知操作: {op}")
                out_ext = ext or p.suffix.lower().lstrip(".")
                if out_ext == "jpeg":
                    out_ext = "jpg"
                save_capture(out, out_dir, name=p.stem, ext=out_ext, prefix=prefix)
            ok += 1
        except Exception:
            fail += 1
    return ok, fail


if __name__ == "__main__":
    # 极简自检：import 不炸 + 拼接正确
    im1 = Image.new("RGB", (100, 50), (255, 0, 0))
    im2 = Image.new("RGB", (100, 40), (0, 255, 0))
    s = stitch_vertical([im1, im2])
    print("stitch size:", s.size)
    print("OK", APP_NAME, APP_VERSION)
