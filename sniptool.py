# -*- coding: utf-8 -*-
"""
截图录屏助手 —— 图形界面

页面：截图 / 录屏 / 长截图 / 标注 / 设置
"""
import json
import os
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from PIL import Image, ImageTk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sniptool_core as core

APP_NAME = core.APP_NAME
APP_VERSION = core.APP_VERSION


# ============================================================================
# 全局热键（可选）
# ============================================================================
class Hotkey:
    """用 GetAsyncKeyState 轮询实现全局热键（不依赖消息循环）。"""

    def __init__(self, root, key_vk, callback):
        self.root = root
        self.key_vk = key_vk
        self.callback = callback
        self.enabled = False
        self._vk = None
        self._poll_id = None

    def set_key(self, name):
        self.stop()
        self._vk = _VK_NAMES.get(name)
        if self._vk is None:
            return False
        self.enabled = True
        self._poll()
        return True

    def stop(self):
        self.enabled = False
        if self._poll_id is not None:
            try:
                self.root.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None

    def _poll(self):
        if not self.enabled:
            return
        try:
            u = core._user32()
            if u.GetAsyncKeyState(self._vk) & 0x8000:
                # 去抖动：等按键抬起
                self.enabled = False
                self.root.after(60, self._resume)
                self.callback()
        except Exception:
            pass
        if self.enabled:
            self._poll_id = self.root.after(90, self._poll)

    def _resume(self):
        if self._vk is not None:
            self.enabled = True
            self._poll()


_VK_NAMES = {
    "F1": 0x70,
    "F2": 0x71,
    "F3": 0x72,
    "F4": 0x73,
    "F5": 0x74,
    "F6": 0x75,
    "F7": 0x76,
    "F8": 0x77,
    "F9": 0x78,
    "F10": 0x79,
    "F11": 0x7A,
    "F12": 0x7B,
}


# ============================================================================
# 区域选择器（全屏半透明，拖拽选区）
# ============================================================================
class RegionSelector(tk.Toplevel):
    """全屏半透明窗口，鼠标拖拽选择矩形区域。

    返回 (left, top, right, bottom)；取消返回 None。
    """

    def __init__(self, master, title="拖动鼠标选择区域，回车确认 / Esc 取消"):
        super().__init__(master)
        self.title(title)
        self.overrideredirect(True)
        self.result = None
        self._start = None
        self._cur = None

        vx, vy, vw, vh = core.virtual_screen_rect()
        self._vx, self._vy = vx, vy
        self.geometry(f"{vw}x{vh}+{vx}+{vy}")
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.28)

        self.canvas = tk.Canvas(self, highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.bind("<Escape>", self._cancel)
        self.bind("<Return>", self._confirm)
        self.bind("<Double-Button-1>", self._confirm)
        self.bind("<Configure>", self._on_configure)

        self._draw_hint()
        self._cross_lines = []
        self.after(120, self._init_crosshair)

    # ------------------------------------------------------------------
    def _draw_hint(self):
        c = self.canvas
        c.create_text(20, 24, text="拖动鼠标选择区域  ·  回车确认  ·  Esc 取消",
                      anchor="nw", fill="#ffffff", font=("Microsoft YaHei", 13, "bold"))

    def _init_crosshair(self):
        # 十字线帮助对准
        w = self.winfo_width()
        h = self.winfo_height()
        if w > 0 and h > 0:
            self.canvas.create_line(w // 2, 0, w // 2, h, fill="#ff4d4f", dash=(6, 6))
            self.canvas.create_line(0, h // 2, w, h // 2, fill="#ff4d4f", dash=(6, 6))

    def _on_configure(self, event):
        # 尺寸变化时清掉旧十字线
        for item in self._cross_lines:
            try:
                self.canvas.delete(item)
            except Exception:
                pass
        self._cross_lines = []
        w, h = event.width, event.height
        if w > 0 and h > 0:
            self._cross_lines.append(self.canvas.create_line(w // 2, 0, w // 2, h, fill="#ff4d4f", dash=(6, 6)))
            self._cross_lines.append(self.canvas.create_line(0, h // 2, w, h // 2, fill="#ff4d4f", dash=(6, 6)))

    def _press(self, event):
        self._start = (event.x, event.y)
        self._cur = (event.x, event.y)

    def _move(self, event):
        if self._start is None:
            return
        self._cur = (event.x, event.y)
        self.canvas.delete("sel")
        x1, y1 = self._start
        x2, y2 = self._cur
        self.canvas.create_rectangle(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2),
                                     outline="#ff4d4f", width=3, tags="sel")
        self.canvas.create_text(max(x1, x2) + 8, min(y1, y2), text=self._size_text(),
                                anchor="nw", fill="#ffd666", font=("Microsoft YaHei", 11))

    def _size_text(self):
        if not self._cur or not self._start:
            return ""
        w = abs(self._cur[0] - self._start[0])
        h = abs(self._cur[1] - self._start[1])
        return f"{w} × {h}"

    def _release(self, event):
        if self._start is None:
            return
        x1, y1 = self._start
        x2, y2 = (event.x, event.y)
        left = min(x1, x2) + self._vx
        top = min(y1, y2) + self._vy
        right = max(x1, x2) + self._vx
        bottom = max(y1, y2) + self._vy
        self.result = (left, top, right, bottom)
        self._confirm()

    def _confirm(self, event=None):
        self.destroy()

    def _cancel(self, event=None):
        self.result = None
        self.destroy()


# ============================================================================
# 标注编辑器
# ============================================================================
class AnnotationEditor(tk.Toplevel):
    TOOLS = [
        ("选择", "select", "选择"),
        ("矩形", "rect", "矩形"),
        ("箭头", "arrow", "箭头"),
        ("直线", "line", "直线"),
        ("文字", "text", "文字"),
        ("马赛克", "mosaic", "马赛克"),
        ("高亮", "highlight", "高亮"),
        ("裁剪", "crop", "裁剪"),
    ]

    def __init__(self, master, image, on_save=None):
        super().__init__(master)
        self.title("标注编辑器")
        self.on_save = on_save
        self.base = core._to_rgb(image)
        self.stack = [self.base.copy()]
        self.index = 0
        self.tool = "select"
        self.color = core.COLORS[0][1]
        self.width = 3
        self.block = 14
        self._drawing = False
        self._start = None
        self._photo = None

        self.minsize(820, 560)
        self._build()
        self._fit()
        self._render()

    # ------------------------------------------------------------------
    def _build(self):
        bar = ttk.Frame(self)
        bar.pack(side="top", fill="x", padx=6, pady=6)

        self._tool_buttons = {}
        for label, key, text in self.TOOLS:
            b = ttk.Button(bar, text=text, command=lambda k=key: self.set_tool(k))
            b.pack(side="left", padx=2)
            b._tool_key = key
            b._tool_label = text
            self._tool_buttons[key] = b
        self.set_tool("select")

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Label(bar, text="颜色").pack(side="left")
        self.color_var = tk.StringVar(value="红")
        cb = ttk.Combobox(bar, textvariable=self.color_var, values=core.COLOR_NAMES,
                          width=6, state="readonly")
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_color())

        ttk.Label(bar, text="线宽").pack(side="left", padx=(8, 0))
        self.width_var = tk.IntVar(value=3)
        ttk.Spinbox(bar, from_=1, to=20, width=4, textvariable=self.width_var,
                    command=lambda: self._render()).pack(side="left")

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Button(bar, text="撤销", command=self.undo).pack(side="left")
        ttk.Button(bar, text="重做", command=self.redo).pack(side="left", padx=4)
        ttk.Button(bar, text="重置", command=self.reset).pack(side="left")
        ttk.Button(bar, text="另存为…", command=self.save_as).pack(side="left", padx=4)
        ttk.Button(bar, text="保存并关闭", command=self.save_close).pack(side="left")

        self.status = tk.StringVar(value="就绪")
        ttk.Label(bar, textvariable=self.status).pack(side="right")

        # 画布
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=6, pady=6)
        self.canvas = tk.Canvas(wrap, highlightthickness=1, relief="solid")
        self.canvas.pack(fill="both", expand=True)
        scroll_y = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        scroll_x = ttk.Scrollbar(wrap, orient="horizontal", command=self.canvas.xview)
        scroll_y.pack(side="right", fill="y")
        scroll_x.pack(side="bottom", fill="x")
        self.canvas.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Configure>", lambda e: self._fit())

    # ------------------------------------------------------------------
    def set_tool(self, key):
        self.tool = key
        for k, b in getattr(self, "_tool_buttons", {}).items():
            try:
                label = "● " + b._tool_label if k == key else b._tool_label
                b.configure(text=label)
            except Exception:
                pass
        self.status.set(self.tool)
        cursor = {"select": "arrow", "text": "text", "crop": "crosshair"}.get(key, "crosshair")
        self.canvas.configure(cursor=cursor)

    def _on_color(self):
        for name, rgb in core.COLORS:
            if name == self.color_var.get():
                self.color = rgb

    # ------------------------------------------------------------------
    def _fit(self):
        # 画布可见区
        canv_w = max(1, self.canvas.winfo_width())
        canv_h = max(1, self.canvas.winfo_height())
        iw, ih = self.base.size
        scale = min(canv_w / iw, canv_h / ih, 1.0)
        if scale <= 0:
            scale = 1.0
        dw, dh = max(1, int(iw * scale)), max(1, int(ih * scale))
        self._scale = scale
        self._disp = (dw, dh)
        self.canvas.configure(scrollregion=(0, 0, dw, dh))
        self._render()

    def _render(self, extra=None):
        img = self.stack[self.index]
        if extra:
            img = extra
        dw, dh = self._disp if hasattr(self, "_disp") else img.size
        if dw <= 0 or dh <= 0:
            return
        show = img if img.size == (dw, dh) else img.resize((dw, dh), core._LANCZOS)
        if self._photo is not None:
            try:
                self._photo.close()
            except Exception:
                pass
        self._photo = ImageTk.PhotoImage(show)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo)

    def _to_img(self, cx, cy):
        scale = getattr(self, "_scale", 1.0) or 1.0
        x = cx / scale
        y = cy / scale
        return (x, y)

    # ------------------------------------------------------------------
    def _press(self, event):
        self._start = self._to_img(event.x, event.y)
        self._cur = self._start
        if self.tool == "text":
            txt = simpledialog.askstring("输入文字", "要标注的文字：", parent=self)
            if txt:
                self._apply_text(self._start, txt)
            self._start = None

    def _move(self, event):
        if self._start is None or self.tool == "select":
            return
        self._cur = self._to_img(event.x, event.y)
        if self.tool in ("rect", "line", "arrow", "highlight"):
            self._render(self._preview())

    def _preview(self):
        a = (min(self._start[0], self._cur[0]), min(self._start[1], self._cur[1]),
             max(self._start[0], self._cur[0]), max(self._start[1], self._cur[1]))
        im = self.stack[self.index].copy()
        if self.tool == "rect":
            return core.annotate_rect(im, a, color=self.color, width=self.width)
        if self.tool == "highlight":
            return core.annotate_highlight(im, a, color=self.color)
        if self.tool == "line":
            return core.annotate_line(im, self._start, self._cur, color=self.color, width=self.width)
        if self.tool == "arrow":
            return core.annotate_arrow(im, self._start, self._cur, color=self.color,
                                       width=self.width)
        return im

    def _release(self, event):
        if self._start is None:
            return
        self._cur = self._to_img(event.x, event.y)
        try:
            if self.tool == "rect":
                self._commit(core.annotate_rect(
                    self.stack[self.index], self._box(), color=self.color, width=self.width))
            elif self.tool == "highlight":
                self._commit(core.annotate_highlight(self.stack[self.index], self._box(),
                                                     color=self.color))
            elif self.tool == "line":
                self._commit(core.annotate_line(self.stack[self.index], self._start, self._cur,
                                                color=self.color, width=self.width))
            elif self.tool == "arrow":
                self._commit(core.annotate_arrow(self.stack[self.index], self._start, self._cur,
                                                 color=self.color, width=self.width))
            elif self.tool == "mosaic":
                self._commit(core.annotate_mosaic(self.stack[self.index], self._box(), block=self.block))
            elif self.tool == "crop":
                self._commit(core.crop_image(self.stack[self.index], self._box()))
        except Exception as e:
            messagebox.showerror("标注失败", str(e))
        self._start = None
        self._cur = None
        self._render()

    def _box(self):
        return (min(self._start[0], self._cur[0]), min(self._start[1], self._cur[1]),
                max(self._start[0], self._cur[0]), max(self._start[1], self._cur[1]))

    def _apply_text(self, pos, txt):
        font = core.load_font(26)
        self._commit(core.annotate_text(self.stack[self.index], pos, txt,
                                        color=self.color, font=font, size=26))

    def _commit(self, im):
        # 丢弃 redo 分支
        self.stack = self.stack[:self.index + 1]
        self.stack.append(im)
        self.index += 1

    def undo(self):
        if self.index > 0:
            self.index -= 1
            self._render()

    def redo(self):
        if self.index < len(self.stack) - 1:
            self.index += 1
            self._render()

    def reset(self):
        self.stack = [self.base.copy()]
        self.index = 0
        self._render()

    def current(self):
        return self.stack[self.index]

    def save_as(self):
        path = filedialog.asksaveasfilename(
            title="保存标注结果", defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("JPG", "*.jpg"), ("BMP", "*.bmp")])
        if not path:
            return
        self.current().save(path)
        self.status.set("已保存")

    def save_close(self):
        if self.on_save:
            self.on_save(self.current())
        self.destroy()


# ============================================================================
# 主窗口
# ============================================================================
class App:
    def __init__(self, root):
        self.root = root
        root.title(f"{APP_NAME} v{APP_VERSION}")
        root.geometry("860x600")
        root.minsize(760, 520)

        self.output_dir = str(Path.home() / "Pictures" / "截图录屏助手")
        self.out_format = "png"
        self.auto_open = True
        self.history = []
        self.hotkey = Hotkey(root, 0x70, self.quick_capture)

        self._load_settings()
        self._load_history()
        self._build()
        self._poll_hotkey_ui()

    # ------------------------------------------------------------------
    def _build(self):
        outer = ttk.Frame(self.root)
        outer.pack(fill="both", expand=True, padx=8, pady=8)

        nb = ttk.Notebook(outer)
        nb.pack(fill="both", expand=True)

        self.tab_cap = CaptureTab(nb, self)
        self.tab_rec = RecordTab(nb, self)
        self.tab_long = LongTab(nb, self)
        self.tab_anno = AnnotateTab(nb, self)
        self.tab_set = SettingsTab(nb, self)

        nb.add(self.tab_cap, text="  截图  ")
        nb.add(self.tab_rec, text="  录屏  ")
        nb.add(self.tab_long, text="  长截图  ")
        nb.add(self.tab_anno, text="  标注  ")
        nb.add(self.tab_set, text="  设置  ")

        # 底部状态条
        bar = ttk.Frame(self.root)
        bar.pack(side="bottom", fill="x")
        self.status = tk.StringVar(value="就绪")
        ttk.Label(bar, textvariable=self.status).pack(side="left", padx=8, pady=4)
        ttk.Button(bar, text="打开输出目录", command=self.open_output).pack(side="right", padx=8)

    # ------------------------------------------------------------------
    def set_status(self, msg):
        self.status.set(msg)

    def pick_dir(self):
        d = filedialog.askdirectory(title="选择输出目录", initialdir=self.output_dir)
        if d:
            self.output_dir = d
            self._save_settings()
        return d

    def open_output(self):
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        os.startfile(self.output_dir)

    def quick_capture(self):
        """全局热键 → 区域截图。"""
        try:
            self.set_status("全局热键：请拖动选择区域…")
            self.root.after(80, self._do_region_capture)
        except Exception:
            pass

    def _do_region_capture(self):
        sel = RegionSelector(self.root)
        self.root.wait_window(sel)
        if sel.result is None:
            self.set_status("已取消")
            return
        left, top, right, bottom = sel.result
        if right - left < 5 or bottom - top < 5:
            self.set_status("区域太小，已忽略")
            return
        try:
            im = core.capture_region((left, top, right, bottom))
            self._save_and_record(im, "截图", prefix="截图")
        except Exception as e:
            messagebox.showerror("截图失败", str(e))

    # ------------------------------------------------------------------
    def _save_and_record(self, im, kind, prefix):
        try:
            path = core.save_capture(im, self.output_dir, prefix=prefix, ext=self.out_format)
            self._add_history(kind, str(path))
            if self.auto_open:
                os.startfile(str(path))
            self.set_status(f"已保存：{path.name}")
            return path
        except Exception as e:
            self.set_status("保存失败")
            messagebox.showerror("保存失败", str(e))
            return None

    def _add_history(self, kind, path):
        self.history.insert(0, {"time": core._dt.datetime.now().strftime("%H:%M:%S"),
                                "kind": kind, "path": path})
        self.history = self.history[:30]
        self._save_history()
        self._refresh_history()

    def _refresh_history(self):
        for tab in (getattr(self, "tab_cap", None),):
            if tab:
                tab.refresh()

    def _run_async(self, fn, done=None):
        def worker():
            try:
                fn()
            except Exception:
                traceback.print_exc()
                self.root.after(0, lambda: messagebox.showerror("出错了", traceback.format_exc().splitlines()[-1]))
            if done:
                self.root.after(0, done)
        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    def _load_settings(self):
        p = Path(self.output_dir) / ".settings.json"
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig"))
            self.output_dir = d.get("output_dir", self.output_dir)
            self.out_format = d.get("out_format", self.out_format)
            self.auto_open = d.get("auto_open", self.auto_open)
        except Exception:
            pass

    def _save_settings(self):
        try:
            p = Path(self.output_dir) / ".settings.json"
            p.write_text(json.dumps({
                "output_dir": self.output_dir,
                "out_format": self.out_format,
                "auto_open": self.auto_open,
            }, ensure_ascii=False, indent=2), encoding="utf-8-sig")
        except Exception:
            pass

    def _load_history(self):
        try:
            p = Path(self.output_dir) / "历史记录.json"
            if p.exists():
                self.history = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:
            self.history = []

    def _save_history(self):
        try:
            p = Path(self.output_dir) / "历史记录.json"
            p.write_text(json.dumps(self.history, ensure_ascii=False, indent=2),
                         encoding="utf-8-sig")
        except Exception:
            pass

    def _poll_hotkey_ui(self):
        # 设置页会创建 Hotkey 控件；这里只是保持循环
        self.root.after(500, self._poll_hotkey_ui)


# ============================================================================
# 截图页
# ============================================================================
class CaptureTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app

        row = ttk.Frame(self)
        row.pack(fill="x", padx=10, pady=10)
        ttk.Button(row, text="全屏截图", command=self.full).pack(side="left", padx=3)
        ttk.Button(row, text="区域截图（拖拽）", command=self.region).pack(side="left", padx=3)
        ttk.Button(row, text="窗口截图", command=self.window).pack(side="left", padx=3)
        ttk.Button(row, text="延时截图", command=self.delayed).pack(side="left", padx=3)

        row2 = ttk.Frame(self)
        row2.pack(fill="x", padx=10, pady=(0, 6))
        ttk.Label(row2, text="输出格式").pack(side="left")
        self.fmt = tk.StringVar(value=self.app.out_format)
        cb = ttk.Combobox(row2, textvariable=self.fmt, values=[k for k, _ in core.OUT_FORMATS],
                          width=6, state="readonly")
        cb.pack(side="left", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_fmt())
        ttk.Button(row2, text="选择输出目录…", command=self.app.pick_dir).pack(side="left", padx=6)
        self.dir_lbl = tk.StringVar(value=self.app.output_dir)
        ttk.Label(row2, textvariable=self.dir_lbl, width=40).pack(side="left", padx=6)

        self.list = ttk.Treeview(self, columns=("time", "kind", "name"), show="headings", height=12)
        self.list.heading("time", text="时间")
        self.list.heading("kind", text="类型")
        self.list.heading("name", text="文件")
        self.list.column("time", width=70)
        self.list.column("kind", width=60)
        self.list.column("name", width=380)
        self.list.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.list.bind("<Double-1>", self._open_item)
        self.refresh()

    def _on_fmt(self):
        self.app.out_format = self.fmt.get().lower()
        self.app._save_settings()

    def refresh(self):
        self.list.delete(*self.list.get_children())
        for i, h in enumerate(self.app.history):
            self.list.insert("", "end", iid=str(i),
                             values=(h["time"], h["kind"], Path(h["path"]).name))

    def _open_item(self, event):
        sel = self.list.selection()
        if not sel:
            return
        try:
            h = self.app.history[int(sel[0])]
            os.startfile(h["path"])
        except Exception:
            pass

    def full(self):
        self.app.set_status("正在截取全屏…")
        self.app._run_async(lambda: self._do_full())

    def _do_full(self):
        im = core.capture_full()
        self.app._save_and_record(im, "截图", "全屏")

    def region(self):
        self.app.set_status("请拖动选择区域…")
        sel = RegionSelector(self.app.root)
        self.app.root.wait_window(sel)
        if sel.result is None:
            self.app.set_status("已取消")
            return
        left, top, right, bottom = sel.result
        if right - left < 5 or bottom - top < 5:
            self.app.set_status("区域太小，已忽略")
            return
        im = core.capture_region((left, top, right, bottom))
        self.app._save_and_record(im, "截图", "区域")

    def window(self):
        w = WindowPicker(self.app.root, self._on_window)
        self.app.root.wait_window(w)

    def _on_window(self, hwnd, title):
        self.app.set_status(f"正在截取窗口：{title}")
        self.app._run_async(lambda: self._do_window(hwnd))

    def _do_window(self, hwnd):
        im = core.capture_window(hwnd)
        if im is None:
            self.app.set_status("没有截到该窗口")
            return
        self.app._save_and_record(im, "截图", "窗口")

    def delayed(self):
        sec = simpledialog.askfloat("延时截图", "延时秒数（0~30）：", parent=self,
                                    initialvalue=3.0)
        if sec is None:
            return
        sec = max(0.0, min(30.0, sec))
        self.app.set_status(f"{sec} 秒后自动截图…")
        self.app._run_async(lambda: self._do_delayed(sec))

    def _do_delayed(self, sec):
        im = core.delayed_capture(sec)
        self.app._save_and_record(im, "截图", "延时")


# ============================================================================
# 窗口选择器
# ============================================================================
class WindowPicker(tk.Toplevel):
    def __init__(self, master, on_pick):
        super().__init__(master)
        self.title("选择窗口")
        self.on_pick = on_pick
        self.geometry("520x420")
        self.transient(master)
        self.grab_set()

        ttk.Label(self, text="点选要截取的窗口：").pack(anchor="w", padx=10, pady=(8, 4))
        self.box = tk.Listbox(self, height=18)
        self.box.pack(fill="both", expand=True, padx=10, pady=4)
        for hwnd, title, rect in core.enum_windows():
            if title and title.strip():
                self.box.insert("end", f"{title}    {rect[2]-rect[0]}×{rect[3]-rect[1]}")
                self.box._items = getattr(self.box, "_items", [])
                self.box._items.append((hwnd, title, rect))
        ttk.Button(self, text="取消", command=self.destroy).pack(side="right", padx=10, pady=8)
        ttk.Button(self, text="确定", command=self._ok).pack(side="right")
        self.box.bind("<Double-1>", lambda e: self._ok())

    def _ok(self):
        sel = self.box.curselection()
        if not sel:
            return
        items = getattr(self.box, "_items", [])
        idx = sel[0]
        if idx < len(items):
            hwnd, title, rect = items[idx]
            self.on_pick(hwnd, title)
        self.destroy()


# ============================================================================
# 录屏页
# ============================================================================
class RecordTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app

        f = ttk.LabelFrame(self, text="录制设置")
        f.pack(fill="x", padx=10, pady=10)

        ttk.Label(f, text="录制范围").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.scope = tk.StringVar(value="全屏")
        ttk.Combobox(f, textvariable=self.scope, values=["全屏", "区域"],
                     state="readonly", width=10).grid(row=0, column=1, sticky="w")

        ttk.Label(f, text="时长(秒)").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        self.dur = tk.DoubleVar(value=5.0)
        ttk.Spinbox(f, from_=1, to=120, increment=1, textvariable=self.dur,
                    width=8).grid(row=1, column=1, sticky="w")

        ttk.Label(f, text="帧率").grid(row=2, column=0, sticky="w", padx=8, pady=6)
        self.fps = tk.IntVar(value=8)
        ttk.Combobox(f, textvariable=self.fps,
                     values=[str(v) for _, v in core.FPS_PRESETS],
                     state="readonly", width=8).grid(row=2, column=1, sticky="w")
        self.fps.set(8)

        ttk.Label(f, text="输出").grid(row=3, column=0, sticky="w", padx=8, pady=6)
        self.path_var = tk.StringVar(value=str(Path(app.output_dir) / "录屏.gif"))
        ttk.Entry(f, textvariable=self.path_var, width=40).grid(row=3, column=1, columnspan=3, sticky="we")
        ttk.Button(f, text="选择…", command=self._pick).grid(row=3, column=4, padx=6)

        ttk.Button(f, text="开始录屏", command=self.start).grid(row=4, column=1, columnspan=2,
                                                                sticky="w", padx=8, pady=10)
        self.stop_btn = ttk.Button(f, text="停止", command=self.stop, state="disabled")
        self.stop_btn.grid(row=4, column=3, columnspan=2, sticky="e", padx=8, pady=10)

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", padx=10, pady=(0, 10))

        self.preview = tk.Label(self, text="", width=60, relief="sunken")
        self.preview.pack(fill="x", padx=10, pady=(0, 10))
        self._preview_photo = None

        self._thread = None
        self._stop = False

    def _pick(self):
        p = filedialog.asksaveasfilename(title="保存 GIF", defaultextension=".gif",
                                         initialfile="录屏.gif",
                                         initialdir=self.app.output_dir,
                                         filetypes=[("GIF", "*.gif")])
        if p:
            self.path_var.set(p)

    def start(self):
        dur = float(self.dur.get())
        fps = int(self.fps.get())
        scope = self.scope.get()
        out = self.path_var.get().strip()
        if not out:
            messagebox.showwarning("提示", "请选择输出文件")
            return
        if scope == "区域":
            self.app.set_status("请拖动选择录屏区域…")
            sel = RegionSelector(self.app.root, title="拖动选择录屏区域，回车确认")
            self.app.root.wait_window(sel)
            if sel.result is None:
                return
            box = sel.result
        else:
            box = None

        self._stop = False
        self.stop_btn.configure(state="normal")
        self.progress.configure(value=0, maximum=100)
        self.app._run_async(lambda: self._run(box, dur, fps, out))

    def _run(self, box, dur, fps, out):
        def frame_source():
            if box is None:
                return core.capture_full()
            return core.capture_region(box)

        def on_frame(i, n):
            # 录屏跑在后台线程，UI 更新必须回到主线程
            try:
                self.app.root.after(0, lambda: self.progress.configure(
                    value=int(i / max(1, n) * 100)))
                self.app.root.after(0, lambda: self.app.set_status(f"录屏中… {i+1}/{n}"))
                if i == 0:
                    try:
                        self.app.root.after(0, lambda: self.root_preview(frame_source()))
                    except Exception:
                        pass
            except Exception:
                pass
            if self._stop:
                raise _StopRecording()

        try:
            path = core.record_gif(frame_source, dur, fps, out, on_frame=on_frame)
            self.app.root.after(0, lambda: self.app._add_history("录屏", str(path)))
            self.app.root.after(0, lambda: self.app.set_status(f"录屏已保存：{Path(path).name}"))
            self.app.root.after(0, lambda: messagebox.showinfo("录屏完成", f"已保存到：\n{path}"))
        except _StopRecording:
            self.app.root.after(0, lambda: self.app.set_status("录屏已停止"))
        except Exception as e:
            self.app.root.after(0, lambda: messagebox.showerror("录屏失败", str(e)))
        finally:
            self.app.root.after(0, lambda: self.stop_btn.configure(state="disabled"))
            self.app.root.after(0, lambda: self.progress.configure(value=0))

    def stop(self):
        self._stop = True

    def root_preview(self, im):
        try:
            im = im.copy()
            im.thumbnail((560, 200), core._LANCZOS)
            self._preview_photo = ImageTk.PhotoImage(im)
            self.preview.configure(image=self._preview_photo, text="")
        except Exception:
            pass


class _StopRecording(core.CaptureStopped):
    """录屏/长截图停止信号。必须和 core 里的 CaptureStopped 是同一个类，
    否则会被 core 的宽 except 吞掉。"""


# ============================================================================
# 长截图页
# ============================================================================
class LongTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app

        f = ttk.LabelFrame(self, text="长截图（窗口自动滚动拼接）")
        f.pack(fill="x", padx=10, pady=10)

        ttk.Label(f, text="目标窗口").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.win_var = tk.StringVar()
        ttk.Combobox(f, textvariable=self.win_var, width=50, state="readonly").grid(
            row=0, column=1, columnspan=3, sticky="we")
        ttk.Button(f, text="刷新窗口", command=self.refresh).grid(row=0, column=4, padx=6)
        self._items = []

        ttk.Label(f, text="每次滚动(px)").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        self.step = tk.IntVar(value=600)
        ttk.Spinbox(f, from_=100, to=3000, increment=100, textvariable=self.step,
                    width=8).grid(row=1, column=1, sticky="w")

        ttk.Label(f, text="最多步数").grid(row=2, column=0, sticky="w", padx=8, pady=6)
        self.maxsteps = tk.IntVar(value=30)
        ttk.Spinbox(f, from_=1, to=100, textvariable=self.maxsteps,
                    width=8).grid(row=2, column=1, sticky="w")

        ttk.Label(f, text="每步等待(秒)").grid(row=3, column=0, sticky="w", padx=8, pady=6)
        self.settle = tk.DoubleVar(value=0.5)
        ttk.Spinbox(f, from_=0.1, to=3.0, increment=0.1, textvariable=self.settle,
                    width=8).grid(row=3, column=1, sticky="w")

        ttk.Label(f, text="输出").grid(row=4, column=0, sticky="w", padx=8, pady=6)
        self.path_var = tk.StringVar(value=str(Path(app.output_dir) / "长截图.png"))
        ttk.Entry(f, textvariable=self.path_var, width=40).grid(row=4, column=1, columnspan=3, sticky="we")
        ttk.Button(f, text="选择…", command=self._pick).grid(row=4, column=4, padx=6)

        ttk.Button(f, text="开始长截图", command=self.start).grid(
            row=5, column=1, columnspan=2, sticky="w", padx=8, pady=10)
        self.stop_btn = ttk.Button(f, text="停止", command=self.stop, state="disabled")
        self.stop_btn.grid(row=5, column=3, columnspan=2, sticky="e", padx=8, pady=10)

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", padx=10, pady=(0, 10))
        self._stop = False

    def refresh(self):
        items = []
        for hwnd, title, rect in core.enum_windows():
            if title and title.strip():
                items.append(f"{title}    {rect[2]-rect[0]}×{rect[3]-rect[1]}")
        self._items = items
        self.win_var.set(items[0] if items else "")

    def _pick(self):
        p = filedialog.asksaveasfilename(title="保存长截图", defaultextension=".png",
                                         initialfile="长截图.png",
                                         initialdir=self.app.output_dir)
        if p:
            self.path_var.set(p)

    def start(self):
        sel = self.win_var.get()
        if not sel or not self._items:
            messagebox.showwarning("提示", "请先选择一个窗口")
            return
        # 匹配
        match = None
        for hwnd, title, rect in core.enum_windows():
            if title and sel.startswith(title):
                match = (hwnd, title, rect)
                break
        if match is None:
            messagebox.showwarning("提示", "窗口已不存在，请刷新后重试")
            return
        hwnd = match[0]
        out = self.path_var.get().strip() or str(Path(self.app.output_dir) / "长截图.png")

        self._stop = False
        self.stop_btn.configure(state="normal")
        self.progress.configure(value=0, maximum=100)
        self.app.set_status("正在长截图…")
        # 后台线程不能碰 Tk 变量，先把参数取出来
        step = int(self.step.get())
        maxsteps = int(self.maxsteps.get())
        settle = float(self.settle.get())

        def job():
            def on_progress(i, n):
                if self._stop:
                    raise _StopRecording()
                self.app.root.after(0, lambda: self.progress.configure(
                    value=int(i / max(1, n) * 100)))
                self.app.root.after(0, lambda: self.app.set_status(f"长截图中… {i}/{n}"))
            try:
                im, path = core.capture_window_scrolled(
                    hwnd, str(Path(out).parent), prefix=Path(out).stem,
                    ext=Path(out).suffix.lstrip("."), step_px=step,
                    max_steps=maxsteps, settle=settle,
                    on_progress=on_progress)
                if path:
                    self.app.root.after(0, lambda: self.app._add_history("长截图", str(path)))
                    self.app.root.after(0, lambda: self.app.set_status(
                        f"长截图已保存：{Path(path).name}"))
                    self.app.root.after(0, lambda: messagebox.showinfo("完成", f"已保存到：\n{path}"))
                else:
                    self.app.root.after(0, lambda: self.app.set_status("没有截到内容"))
            except _StopRecording:
                self.app.root.after(0, lambda: self.app.set_status("已停止"))
            except Exception as e:
                self.app.root.after(0, lambda: messagebox.showerror("长截图失败", str(e)))
            finally:
                self.app.root.after(0, lambda: self.stop_btn.configure(state="disabled"))
                self.app.root.after(0, lambda: self.progress.configure(value=0))
        self.app._run_async(job)

    def stop(self):
        self._stop = True


# ============================================================================
# 标注页
# ============================================================================
class AnnotateTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app

        f = ttk.LabelFrame(self, text="标注现有图片")
        f.pack(fill="x", padx=10, pady=10)

        ttk.Button(f, text="打开图片…", command=self.open_file).pack(side="left", padx=6, pady=8)
        ttk.Button(f, text="从历史选择", command=self.open_history).pack(side="left", padx=6)
        ttk.Button(f, text="批量马赛克…", command=self.batch).pack(side="left", padx=6)

        self.preview = tk.Label(self, text="（尚未打开图片）", width=60, height=6,
                                relief="sunken", anchor="center")
        self.preview.pack(fill="both", expand=True, padx=10, pady=10)
        self._photo = None
        self._path = None

    def open_file(self):
        p = filedialog.askopenfilename(
            title="选择图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp"),
                       ("所有文件", "*.*")])
        if p:
            self._load(p)

    def open_history(self):
        if not self.app.history:
            messagebox.showinfo("提示", "还没有截图历史")
            return
        sel = simpledialog.askstring("从历史选择", "输入序号（1 开始）：", parent=self)
        try:
            idx = int(sel) - 1
            self._load(self.app.history[idx]["path"])
        except Exception:
            pass

    def _load(self, path):
        try:
            with Image.open(path) as im:
                im = core._to_rgb(im)
                self._path = path
                self._open(im)
        except Exception as e:
            messagebox.showerror("打开失败", str(e))

    def _open(self, im):
        def on_save(saved):
            stem = Path(self._path).stem if self._path else "标注"
            self._path = str(core.save_capture(
                saved, self.app.output_dir, prefix=stem, ext="png"))
            self._load(self._path)
        editor = AnnotationEditor(self.app.root, im, on_save=on_save)
        self.app.root.wait_window(editor)

    def batch(self):
        folder = filedialog.askdirectory(title="选择要批量打码的图片文件夹")
        if not folder:
            return
        out = filedialog.askdirectory(title="输出文件夹", initialdir=folder)
        if not out:
            return
        self.app.set_status("正在批量打码…")
        self.app._run_async(
            lambda: self._batch(folder, out),
            done=lambda: None)

    def _batch(self, folder, out):
        ok, fail = core.process_dir(folder, out, op="mosaic", block=14)
        msg = f"成功 {ok} 张，失败 {fail} 张"
        self.app.root.after(0, lambda: (
            self.app.set_status("批量完成"),
            messagebox.showinfo("批量完成", msg)))


# ============================================================================
# 设置页
# ============================================================================
class SettingsTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app

        f = ttk.LabelFrame(self, text="通用设置")
        f.pack(fill="x", padx=10, pady=10)

        ttk.Label(f, text="输出目录").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.dir_var = tk.StringVar(value=app.output_dir)
        ttk.Entry(f, textvariable=self.dir_var, width=44).grid(row=0, column=1, columnspan=3, sticky="we")
        ttk.Button(f, text="更改…", command=self._change_dir).grid(row=0, column=4, padx=6)

        ttk.Label(f, text="默认格式").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        self.fmt = tk.StringVar(value=app.out_format)
        ttk.Combobox(f, textvariable=self.fmt, values=[k for k, _ in core.OUT_FORMATS],
                     state="readonly", width=8).grid(row=1, column=1, sticky="w")

        self.auto = tk.BooleanVar(value=app.auto_open)
        ttk.Checkbutton(f, text="截图后自动打开结果", variable=self.auto).grid(
            row=1, column=2, columnspan=2, sticky="w", padx=10)

        ttk.Label(f, text="全局热键").grid(row=2, column=0, sticky="w", padx=8, pady=6)
        self.hk = tk.StringVar(value="未启用")
        ttk.Combobox(f, textvariable=self.hk, values=["未启用"] + list(_VK_NAMES.keys()),
                     state="readonly", width=8).grid(row=2, column=1, sticky="w")
        ttk.Button(f, text="应用", command=self._apply_hotkey).grid(row=2, column=2, sticky="w", padx=6)

        ttk.Button(f, text="保存设置", command=self._save).grid(row=3, column=1, columnspan=2,
                                                                sticky="w", padx=8, pady=10)

        info = ttk.LabelFrame(self, text="关于")
        info.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Label(info, text=f"{APP_NAME} v{APP_VERSION}", foreground="#333").pack(anchor="w", padx=10, pady=6)
        ttk.Label(info, text="纯本地运行 · 不联网 · 截图不外传", foreground="#666").pack(anchor="w", padx=10)

    def _change_dir(self):
        d = filedialog.askdirectory(title="选择输出目录", initialdir=self.dir_var.get())
        if d:
            self.dir_var.set(d)

    def _apply_hotkey(self):
        name = self.hk.get()
        if name == "未启用":
            self.app.hotkey.stop()
            return
        if self.app.hotkey.set_key(name):
            self.app.set_status(f"全局热键已启用：{name}")
        else:
            messagebox.showwarning("提示", "该热键不可用")

    def _save(self):
        self.app.output_dir = self.dir_var.get().strip() or self.app.output_dir
        self.app.out_format = self.fmt.get().lower()
        self.app.auto_open = bool(self.auto.get())
        self.app._save_settings()
        self.app.set_status("设置已保存")


# ============================================================================
def run_selftest():
    """--selftest：不启动 GUI，跑一遍核心链路并写结果文件。

    用于验证**打包后**的依赖（PIL / ctypes / tkinter）真的可用，
    而不只是源码能跑。结果写到环境变量 SNIPTOOL_SELFTEST_OUT 指定的文件。
    """
    import json
    import os as _os
    import tempfile
    from pathlib import Path as _Path

    results = {"pass": [], "fail": [], "skip": []}

    def ok(name, cond, detail=""):
        (results["pass"] if cond else results["fail"]).append(
            f"{name} {detail}".strip())

    try:
        tmp = _Path(tempfile.mkdtemp(prefix="snip_selftest_"))
        # 1. 截图
        im = core.capture_full()
        ok("全屏截图", im is not None and im.size[0] > 0, str(im.size if im else None))
        # 2. 区域截图
        try:
            r = core.capture_region((0, 0, 120, 90))
            ok("区域截图", r is not None and r.size == (120, 90), str(r.size if r else None))
        except Exception as e:
            results["skip"].append(f"区域截图 {type(e).__name__}")
        # 3. 标注
        base = core._to_rgb(im) if im is not None else Image.new("RGB", (200, 120), (255, 255, 255))
        out = core.annotate_rect(base, (10, 10, 90, 80), color=(230, 57, 70), width=3)
        ok("矩形标注", out is not None and out.size == base.size)
        mos = core.annotate_mosaic(base, (10, 10, 120, 90), block=12)
        ok("马赛克", mos is not None and mos.size == base.size)
        # 4. 去重拼接
        def grad(w, h):
            g = Image.new("RGB", (w, h))
            px = g.load()
            for y in range(h):
                c = ((y * 7) % 256, (y * 13) % 256, (y * 29) % 256)
                for x in range(w):
                    px[x, y] = c
            return g
        full = grad(100, 140)
        ded = core.stitch_vertical_dedupe(
            [full.crop((0, 0, 100, 100)), full.crop((0, 40, 100, 140))], tol=12.0)
        ok("去重拼接高度=140", ded.size == (100, 140), str(ded.size))
        # 5. GIF
        frames = [Image.new("RGB", (60, 40), (i * 20 % 256, 100, 200)) for i in range(5)]
        gif = core.save_gif_from_frames(frames, tmp / "t.gif", duration_ms=100)
        with Image.open(gif) as g:
            ok("GIF 5 帧", getattr(g, "n_frames", 1) == 5, str(getattr(g, "n_frames", 1)))
        # 6. 保存
        p = core.save_capture(base, tmp, prefix="自检", ext="png")
        ok("保存截图", p.exists() and p.suffix == ".png", str(p.name))
        # 7. 窗口枚举
        wins = core.enum_windows()
        ok("枚举窗口", len(wins) > 0, f"{len(wins)} 个")
        # 8. 剪贴板
        if core.copy_image_to_clipboard(Image.new("RGB", (16, 16), (10, 200, 10))):
            ok("剪贴板写入", core.image_from_clipboard() is not None)
        else:
            results["skip"].append("剪贴板写入（无交互桌面）")
    except Exception as e:
        import traceback as _tb
        results["fail"].append(f"自检异常 {type(e).__name__}: {e}\n{_tb.format_exc()}")

    summary = {"app": APP_NAME, "version": APP_VERSION,
               "pass_n": len(results["pass"]), "fail_n": len(results["fail"]),
               "skip_n": len(results["skip"]),
               "pass": results["pass"], "fail": results["fail"], "skip": results["skip"]}
    out_path = _os.environ.get("SNIPTOOL_SELFTEST_OUT")
    if out_path:
        _Path(out_path).write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                   encoding="utf-8-sig")
    for line in results["pass"]:
        print("PASS", line)
    for line in results["fail"]:
        print("FAIL", line)
    for line in results["skip"]:
        print("SKIP", line)
    print(f"SUMMARY pass={summary['pass_n']} fail={summary['fail_n']} skip={summary['skip_n']}")
    return 1 if results["fail"] else 0


def main():
    if "--selftest" in sys.argv:
        sys.exit(run_selftest())
    root = tk.Tk()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
