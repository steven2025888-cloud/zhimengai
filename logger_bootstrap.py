import sys
import os
from datetime import datetime

LOG_DIR = os.path.join(os.getcwd(), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

today = datetime.now().strftime("%Y-%m-%d")
log_path = os.path.join(LOG_DIR, f"{today}.log")

# 只保留今天的日志
for f in os.listdir(LOG_DIR):
    if f != f"{today}.log":
        try:
            os.remove(os.path.join(LOG_DIR, f))
        except:
            pass

class SafeTee:
    def __init__(self, *streams):
        self.streams = [s for s in streams if s is not None]

    def write(self, data):
        for s in self.streams:
            try:
                s.write(data)
                s.flush()
            except:
                pass

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except:
                pass


log_fp = open(log_path, "a", encoding="utf-8", buffering=1)

# 先保存原始 stdout（exe 下有时是 None）
_real_stdout = sys.stdout
_real_stderr = sys.stderr

sys.stdout = SafeTee(_real_stdout, log_fp)
sys.stderr = SafeTee(_real_stderr, log_fp)

print("📝 日志系统初始化完成：", log_path)
