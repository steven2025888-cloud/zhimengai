# main.py  （薄入口）
# 说明：
# - 作为 CLI/调试入口：python main.py -> 走 core.entry_service.run()
# - 作为 UI “启动系统”入口：from main import main -> 走 core.entry_service.run_engine(license_key)
#
# 关键点：这里不要在模块顶层 import core.entry_service，避免 UI 侧运行时触发循环导入。

def main(license_key: str):
    """给 UI/工作台调用：传入 license_key 直接启动引擎（不弹窗）"""
    from core.entry_service import run_engine
    return run_engine(license_key)


def run():
    """给命令行调用：带授权弹窗的服务入口"""
    from core.entry_service import run
    return run()


if __name__ == "__main__":
    run()
