import cv2
import argparse
import os

def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))

def main():
    parser = argparse.ArgumentParser(description="框选ROI并输出像素/归一化 bx/by/bw/bh（稳健版）")
    parser.add_argument("video", nargs="?", help="视频路径（可选，不传会弹窗选择）")
    parser.add_argument("--frame", type=int, default=0, help="从第几帧读取（默认0）")
    parser.add_argument("--maxw", type=int, default=1280, help="预览最大宽度（默认1280）")
    parser.add_argument("--maxh", type=int, default=720, help="预览最大高度（默认720）")
    parser.add_argument("--rotate", type=int, default=0, choices=[0, 90, 180, 270],
                        help="如视频显示方向不对，可指定旋转角度（0/90/180/270）")
    args = parser.parse_args()

    video_path = args.video
    if not video_path:
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            video_path = filedialog.askopenfilename(
                title="选择视频文件",
                filetypes=[("Video files", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All files", "*.*")]
            )
        except Exception as e:
            raise SystemExit(f"未提供视频路径，且无法弹窗选择文件：{e}")

    if not video_path or not os.path.exists(video_path):
        raise SystemExit(f"视频不存在：{video_path}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise SystemExit("无法打开视频，请检查路径/格式/解码器。")

    if args.frame > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, args.frame)

    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise SystemExit("读取视频帧失败。你可以换一个 --frame 再试。")

    # 可选：处理旋转（手机视频常见）
    if args.rotate == 90:
        frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    elif args.rotate == 180:
        frame = cv2.rotate(frame, cv2.ROTATE_180)
    elif args.rotate == 270:
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

    H, W = frame.shape[:2]
    print(f"\n原始视频帧尺寸：{W} x {H}")

    # 计算等比例缩放系数，让预览适配屏幕，不失真
    scale = min(args.maxw / W, args.maxh / H, 1.0)
    preview = frame
    if scale < 1.0:
        preview = cv2.resize(frame, (int(W * scale), int(H * scale)), interpolation=cv2.INTER_AREA)

    ph, pw = preview.shape[:2]
    print(f"预览尺寸：{pw} x {ph}（scale={scale:.6f}）")
    print("操作：鼠标拖动框选水印区域，回车/空格确认，ESC取消。\n")

    win = "Select ROI (ENTER/SPACE confirm, ESC cancel)"
    # 注意：这里不让你随意拉伸窗口（避免压扁），让预览图本身决定大小
    cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)

    x, y, rw, rh = cv2.selectROI(win, preview, showCrosshair=True, fromCenter=False)
    cv2.destroyAllWindows()

    if rw == 0 or rh == 0:
        print("已取消或未选择有效区域。")
        return

    # 把预览坐标映射回原图像素坐标
    inv = 1.0 / scale
    BX_px = int(round(x * inv))
    BY_px = int(round(y * inv))
    BW_px = int(round(rw * inv))
    BH_px = int(round(rh * inv))

    # 边界保护（避免越界）
    BX_px = max(0, min(BX_px, W - 1))
    BY_px = max(0, min(BY_px, H - 1))
    BW_px = max(1, min(BW_px, W - BX_px))
    BH_px = max(1, min(BH_px, H - BY_px))

    # 归一化
    BX = BX_px / W
    BY = BY_px / H
    BW = BW_px / W
    BH = BH_px / H

    # 归一化再做一次边界修正：保证 BX+BW<=1，BY+BH<=1
    BX_n = clamp(BX)
    BY_n = clamp(BY)
    BW_n = clamp(BW, 0.0, 1.0 - BX_n)
    BH_n = clamp(BH, 0.0, 1.0 - BY_n)

    print("==== 结果 ====")
    print(f"像素(px)：BX={BX_px}, BY={BY_px}, BW={BW_px}, BH={BH_px}")
    print(f"归一化(0~1)：BX={BX_n:.6f}, BY={BY_n:.6f}, BW={BW_n:.6f}, BH={BH_n:.6f}")
    print(f"校验：BX+BW={BX_n + BW_n:.6f}, BY+BH={BY_n + BH_n:.6f} (应 <= 1)\n")

    print("可直接用于第三方接口的 JSON：")
    print("{")
    print(f'  "BX": {BX_n:.6f},')
    print(f'  "BY": {BY_n:.6f},')
    print(f'  "BW": {BW_n:.6f},')
    print(f'  "BH": {BH_n:.6f}')
    print("}")

if __name__ == "__main__":
    main()
