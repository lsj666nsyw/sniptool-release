# 截图录屏助手

Windows 桌面工具，截图、标注、录屏、长截图一站搞定。

## 功能

- **截图** — 全屏 / 区域拖拽 / 窗口 / 延时
- **长截图** — 选窗口自动滚动 + 去重拼接
- **录屏** — GIF，可选范围/时长/帧率
- **标注** — 矩形 / 箭头 / 直线 / 文字 / 马赛克 / 高亮 / 裁剪，支持撤销重做
- **批量** — 对整个文件夹的图片统一打码
- **全局热键** — F1~F12 一键开始区域截图

## 使用方法

1. 下载 `截图录屏助手_v1.0.zip`
2. 解压到文件夹
3. 双击 `截图录屏助手.exe`

## 依赖

- Python 3.10+
- Pillow 10.0+
- tkinter（Python 自带）
- 窗口/截图用 ctypes 直接调 Windows API，**不需要 pywin32**

## 打包

```bash
pyinstaller --clean --noconfirm --distpath dist2 截图录屏助手.spec
```

## 测试

```bash
python test_core.py          # 核心逻辑，48 项
python sniptool.py --selftest  # 冻结版端到端自检
```

## 许可证

MIT License
