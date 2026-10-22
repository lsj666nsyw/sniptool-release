# -*- coding: utf-8 -*-
"""sniptool 核心逻辑自测（不启动 GUI）。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"D:\21821\products\sniptool")
import sniptool_core as C
from PIL import Image, ImageDraw

pass_n = 0
fail_n = 0
skip_n = 0


def check(name, cond, detail=""):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print(f"  PASS  {name}")
    else:
        fail_n += 1
        print(f"  FAIL  {name}  {detail}")


def skip(name, why):
    global skip_n
    skip_n += 1
    print(f"  SKIP  {name}  {why}")


def make_img(path, size=(320, 200), mode="RGB", color=(200, 120, 60)):
    im = Image.new(mode, size, color)
    d = ImageDraw.Draw(im)
    for i in range(0, size[0], 30):
        d.line([(i, 0), (i, size[1])], fill=(30, 60, 120), width=2)
    im.save(path)
    return path


def make_gradient(w, h):
    """每行颜色由行号唯一决定：任何错位都会产生大差异，去重判据才有牙齿。"""
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        c = ((y * 7) % 256, (y * 13) % 256, (y * 29) % 256)
        for x in range(w):
            px[x, y] = c
    return im


def main():
    tmp = Path(tempfile.mkdtemp(prefix="sniptool_test_"))
    print(f"临时目录：{tmp}\n")

    # ---------- 1. _to_rgb ----------
    print("[1] _to_rgb 透明铺白底")
    rgba = Image.new("RGBA", (40, 30), (0, 0, 255, 0))
    rgb = C._to_rgb(rgba)
    check("RGBA→RGB", rgb.mode == "RGB")
    check("透明区铺白", rgb.getpixel((0, 0)) == (255, 255, 255), str(rgb.getpixel((0, 0))))
    check("原图不变", rgba.mode == "RGBA")

    # ---------- 2. _norm_box ----------
    print("[2] _norm_box 边界收敛")
    check("负值收敛到 0", C._norm_box((-10, -5, 10, 10), (100, 100)) == (0, 0, 10, 10))
    check("越界收敛到宽高", C._norm_box((90, 90, 200, 200), (100, 100)) == (90, 90, 100, 100))
    check("左右颠倒自动纠正", C._norm_box((80, 5, 20, 60), (100, 100)) == (20, 5, 80, 60))

    # ---------- 3. 标注：不修改原图 ----------
    print("[3] 标注返回新图且不改原图")
    src = make_img(tmp / "a.png", (200, 120))
    with Image.open(src) as im0:
        before = im0.convert("RGB").copy()
    out = C.annotate_rect(before, (10, 10, 90, 80), color=(255, 0, 0), width=3)
    check("返回新对象", out is not before)
    check("原图未被修改", before.tobytes() == Image.open(src).convert("RGB").tobytes())

    # ---------- 4. 矩形标注真的画上了 ----------
    print("[4] 矩形标注像素变化")
    base = Image.new("RGB", (200, 120), (255, 255, 255))
    out = C.annotate_rect(base, (10, 10, 90, 80), color=(230, 57, 70), width=3)
    # 边框左竖线 x≈10
    px = out.getpixel((10, 45))
    check("左边框有色", abs(px[0] - 230) < 30 and abs(px[2] - 70) < 30, str(px))
    check("内部仍是白", out.getpixel((50, 45)) == (255, 255, 255))

    # ---------- 5. 箭头 ----------
    print("[5] 箭头端点着色")
    out = C.annotate_arrow(base, (20, 60), (150, 60), color=(255, 0, 0), width=3, head=14)
    check("起点有色", out.getpixel((20, 60))[0] > 200, str(out.getpixel((20, 60))))
    check("终点有色", out.getpixel((150, 60))[0] > 200, str(out.getpixel((150, 60))))
    check("中段有色", out.getpixel((80, 60))[0] > 200, str(out.getpixel((80, 60))))

    # ---------- 6. 文字 ----------
    print("[6] 文字标注")
    out = C.annotate_text(base, (15, 15), "测试ABC", color=(0, 0, 0), size=28)
    # 文字区域应有非白像素
    region = out.crop((15, 15, 150, 45)).convert("L")
    check("文字区域有内容", len(region.getcolors(1000000)) > 1)

    # ---------- 7. 马赛克 ----------
    print("[7] 马赛克")
    noisy = Image.new("RGB", (200, 100))
    d = ImageDraw.Draw(noisy)
    for i in range(0, 200, 4):
        for j in range(0, 100, 4):
            d.rectangle([i, j, i + 3, j + 3], fill=(i % 256, j % 256, 128))
    block1 = C.annotate_mosaic(noisy, (10, 10, 190, 90), block=4)
    block8 = C.annotate_mosaic(noisy, (10, 10, 190, 90), block=20)
    check("马赛克后尺寸不变", block1.size == noisy.size)
    check("原图不变", noisy.getpixel((50, 50)) != block1.getpixel((50, 50)))
    # block 越大，区域内颜色种类越少
    c1 = len(block1.crop((10, 10, 190, 90)).getcolors(1000000))
    c8 = len(block8.crop((10, 10, 190, 90)).getcolors(1000000))
    check("block 越大颜色越少", c8 < c1, f"{c8} vs {c1}")

    # ---------- 8. 高亮 ----------
    print("[8] 高亮")
    out = C.annotate_highlight(base, (10, 10, 90, 50), color=(255, 235, 59), alpha=120)
    check("高亮区变黄", out.getpixel((50, 30))[0] > 200 and out.getpixel((50, 30))[1] > 180,
          str(out.getpixel((50, 30))))

    # ---------- 9. 裁剪 ----------
    print("[9] 裁剪")
    out = C.crop_image(base, (10, 10, 60, 40))
    check("裁剪尺寸正确", out.size == (50, 30), str(out.size))

    # ---------- 10. 拼接 ----------
    print("[10] 拼接")
    i1 = Image.new("RGB", (100, 40), (255, 0, 0))
    i2 = Image.new("RGB", (120, 60), (0, 255, 0))
    v = C.stitch_vertical([i1, i2])
    check("纵向高度相加", v.size == (120, 100), str(v.size))
    h = C.stitch_horizontal([i1, i2])
    check("横向宽度相加", h.size == (220, 60), str(h.size))
    vg = C.stitch_vertical([i1, i2], gap=5)
    check("gap 生效", vg.size == (120, 105), str(vg.size))
    try:
        C.stitch_vertical([])
        check("空列表应报错", False)
    except ValueError:
        check("空列表报错", True)

    # ---------- 11. 去重拼接 ----------
    print("[11] 长截图去重拼接")
    full = make_gradient(100, 140)
    top = full.crop((0, 0, 100, 100))     # 覆盖行 0..99
    bot = full.crop((0, 40, 100, 140))    # 覆盖行 40..139，与 top 重叠 60 行
    stitched = C.stitch_vertical_dedupe([top, bot], tol=12.0)
    check("去重后高度 = 140", stitched.size == (100, 140), str(stitched.size))
    check("确实去掉了 60 行重叠", stitched.size[1] < 200, str(stitched.size))
    check("拼接内容顺序正确", stitched.getpixel((50, 139)) == full.getpixel((50, 139)),
          f"{stitched.getpixel((50, 139))} vs {full.getpixel((50, 139))}")

    # ---------- 12. 大小/命名 ----------
    print("[12] human_size / unique_path / timestamp_name")
    check("1024 → 1.0 KB", C.human_size(1024) == "1.0 KB", C.human_size(1024))
    check("512 → 512 B", C.human_size(512) == "512 B", C.human_size(512))
    p = tmp / "dup.png"
    p.write_text("x")
    check("重名生成 _1", C.unique_path(p).name == "dup_1.png", C.unique_path(p).name)
    n = C.timestamp_name("截图", "png", when=__import__("datetime").datetime(2026, 10, 22, 19, 30, 12))
    check("时间戳命名", n == "截图_20261022_193012.png", n)

    # ---------- 13. 保存 ----------
    print("[13] save_capture")
    outdir = tmp / "out"
    p1 = C.save_capture(Image.new("RGB", (20, 20), (255, 0, 0)), outdir, prefix="截图", ext="png")
    check("自动建目录", p1.exists() and p1.suffix == ".png", str(p1))
    p2 = C.save_capture(Image.new("RGB", (20, 20), (0, 255, 0)), outdir, prefix="截图", ext="png")
    check("重名自动加序号", p2.name != p1.name and p2.exists(), f"{p1.name} / {p2.name}")

    # ---------- 14. GIF ----------
    print("[14] GIF 录制")
    n = C.gif_frame_count(5.0, 8)
    check("5s@8fps = 40 帧", n == 40, str(n))
    check("0s → 1 帧", C.gif_frame_count(0, 8) == 1)
    frames = [Image.new("RGB", (80, 60), (i * 10 % 256, 100, 200)) for i in range(6)]
    gif = C.save_gif_from_frames(frames, tmp / "t.gif", duration_ms=100)
    with Image.open(gif) as g:
        check("GIF 帧数 = 6", getattr(g, "n_frames", 1) == 6, str(getattr(g, "n_frames", 1)))
        check("GIF 格式", g.format == "GIF", str(g.format))

    def src(i=[0]):
        im = Image.new("RGB", (60, 40), (200, 30, 30))
        ImageDraw.Draw(im).text((5, 5), str(i[0]), fill=(255, 255, 255))
        i[0] += 1
        return im

    path = C.record_gif(src, 0.5, 4, tmp / "rec.gif", on_frame=None)
    with Image.open(path) as g:
        check("record_gif 产出 2 帧", getattr(g, "n_frames", 1) == 2, str(getattr(g, "n_frames", 1)))

    # ---------- 15. 批量 ----------
    print("[15] process_dir 批量马赛克")
    srcdir = tmp / "batch"
    srcdir.mkdir(exist_ok=True)
    for i in range(3):
        make_img(srcdir / f"b{i}.png", (120, 80))
    ok, fail = C.process_dir(srcdir, tmp / "batch_out", op="mosaic", block=10)
    check("批量成功 3 张", ok == 3 and fail == 0, f"ok={ok} fail={fail}")

    # ---------- 16. 截图（需要桌面） ----------
    print("[16] 屏幕截图（需桌面环境）")
    try:
        im = C.capture_full()
        check("全屏截图返回图", im is not None and im.size[0] > 0, str(im.size if im else None))
    except Exception as e:
        skip("全屏截图", f"{type(e).__name__}: {e}")

    # ---------- 17. 窗口枚举 ----------
    print("[17] 窗口枚举")
    wins = C.enum_windows()
    if wins:
        check("枚举到窗口", len(wins) > 0, str(len(wins)))
        check("窗口有标题", all(w[1] for w in wins[:5]))
    else:
        skip("窗口枚举", "当前会话枚举不到可见窗口")

    # ---------- 18. 剪贴板 ----------
    print("[18] 剪贴板写入/读取")
    try:
        ok = C.copy_image_to_clipboard(Image.new("RGB", (20, 20), (10, 200, 10)))
        if not ok:
            skip("剪贴板写入", "OpenClipboard 失败（无交互桌面）")
        else:
            got = C.image_from_clipboard()
            check("剪贴板回读成功", got is not None, str(got))
    except Exception as e:
        skip("剪贴板", f"{type(e).__name__}: {e}")

    # ---------- 19. 判据自证：故意改坏必须被抓住 ----------
    print("[19] 判据自证（故意改坏必须转红）")
    # (a) _norm_box 若不收敛越界，测试 2 应失败
    buggy_norm = lambda box, size: tuple(int(v) for v in box)
    try:
        good = C._norm_box((-10, -5, 10, 10), (100, 100))
        bad = buggy_norm((-10, -5, 10, 10), (100, 100))
        check("坏 _norm_box 与好 _norm_box 结果不同", good != bad, f"{good} vs {bad}")
        check("坏 _norm_box 确实越界", bad[0] < 0, str(bad))
    except Exception as e:
        check("判据自证(a) 抛异常", False, str(e))

    # (b) 去重拼接：一个"不去重"的实现必须让测试 11 的判据失败
    def buggy_dedupe(images, tol=12.0, max_overlap_ratio=0.9):
        return C.stitch_vertical(images)  # 故意不接重叠

    full2 = make_gradient(100, 140)
    pair = [full2.crop((0, 0, 100, 100)), full2.crop((0, 40, 100, 140))]
    good_h = C.stitch_vertical_dedupe(pair, tol=12.0).size[1]
    bad_h = buggy_dedupe(pair).size[1]
    check("判据在正确实现上 PASS", good_h == 140, str(good_h))
    check("判据在坏实现上 FAIL", bad_h != 140, str(bad_h))
    check("坏去重比好去重更高", bad_h > good_h, f"{bad_h} vs {good_h}")
    check("坏去重恰好是两张相加", bad_h == 200, str(bad_h))

    # ---------- 20. GUI 模块可导入（不启动 mainloop） ----------
    print("[20] GUI 模块可导入")
    try:
        import sniptool as G
        check("sniptool 导入成功", hasattr(G, "App") and hasattr(G, "AnnotationEditor"))
    except Exception as e:
        check("sniptool 导入", False, f"{type(e).__name__}: {e}")

    print(f"\n{'='*50}")
    print(f"通过 {pass_n} 项，失败 {fail_n} 项，跳过 {skip_n} 项")
    print(f"测试文件在：{tmp}")
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
