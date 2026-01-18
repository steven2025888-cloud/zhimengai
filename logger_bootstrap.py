import sys
import os
from datetime import datetime

LOG_DIR = os.path.join(os.getcwd(), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

today = datetime.now().strftime("%Y-%m-%d")
log_file = os.path.join(LOG_DIR, f"{today}.log")

# 启动时自动清理旧日志（只保留今天）
for f in os.listdir(LOG_DIR):
    if not f.startswith(today):
        try:
            os.remove(os.path.join(LOG_DIR, f))
        except:
            pass

class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            s.write(data)
            s.flush()

    def flush(self):
        for s in self.streams:
            s.flush()

log_fp = open(log_file, "a", encoding="utf-8", buffering=1)

sys.stdout = Tee(sys.stdout, log_fp)
sys.stderr = Tee(sys.stderr, log_fp)

print("📝 日志系统已启动，日志文件：", log_file)
