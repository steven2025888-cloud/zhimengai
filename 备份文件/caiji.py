import time
import threading
from pynput.keyboard import Key, Controller, Listener
import pygetwindow as gw

keyboard_controller = Controller()
running = False  # 用于控制脚本是否在运行
target_window = None  # 用于存储目标窗口


def repeat_key_actions():
    global running, target_window
    print("脚本开始执行...")
    count = 0  # 初始化计数器

    while running:
        # 激活目标窗口
        if target_window is not None:
            target_window.activate()  # 激活目标窗口
            time.sleep(0.1)  # 等待窗口激活

            # 按下键 '3'
            keyboard_controller.press('3')
            keyboard_controller.release('3')
            time.sleep(4)  # 延迟2秒

            # 按住空格键2秒
            keyboard_controller.press(Key.space)
            time.sleep(2)
            keyboard_controller.release(Key.space)  # 释放空格键

            # 按下空格键
            keyboard_controller.press(Key.space)
            time.sleep(0.5)
            keyboard_controller.release(Key.space)
            time.sleep(0.5)

            # 按下空格键
            keyboard_controller.press(Key.space)
            time.sleep(0.5)
            keyboard_controller.release(Key.space)
            time.sleep(0.5)  # 延迟500毫秒

            # 按下键 'Q'
            keyboard_controller.press('q')
            keyboard_controller.release('q')
            time.sleep(2)  # 延迟2秒

            count += 1  # 增加计数器
            if count >= 5:  # 如果已经执行5次
                keyboard_controller.press('e')  # 按下 'e'
                keyboard_controller.release('e')  # 释放 'e'
                time.sleep(1)  # 延迟1秒
                count = 0  # 重置计数器
        else:
            print("目标窗口未设置，停止脚本。")
            break

def start_script():
    global running, target_window
    if not running:
        running = True  # 设置为运行状态
        target_window = gw.getActiveWindow()  # 获取当前活动窗口
        if target_window is not None:
            print(f"目标窗口: {target_window.title}")
            # 启动一个新线程来执行按键操作
            threading.Thread(target=repeat_key_actions, daemon=True).start()
        else:
            print("未找到活动窗口，无法开始脚本。")

def stop_script():
    global running
    running = False
    print("脚本已停止。")

# 监听 F3 键以开始和停止执行
def on_press(key):
    if key == Key.f3:
        if running:
            stop_script()  # 如果正在运行，则停止
        else:
            start_script()  # 如果没有运行，则开始

# 启动监听器
with Listener(on_press=on_press) as listener:
    print("按 F3 开始或停止脚本。")
    listener.join()