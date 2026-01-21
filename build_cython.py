# build_cython.py
import os
import shutil
import sys
from pathlib import Path

from setuptools import Extension, setup
from Cython.Build import cythonize

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "_cython_build"        # 临时编译输出（会删）
DIST = ROOT / "protected_src"       # 给 PyInstaller 的干净输入目录

# 除 app.py / main.py 外：你要求“其他全部编译”
COMPILE_DIRS = ["core", "audio", "api", "tts", "ui"]
COMPILE_FILES = ["config.py", "keywords.py", "zhuli_keywords.py", "logger_bootstrap.py"]

# 不希望复制到 protected_src 的目录（资源目录会保留：img/ffmpeg/ui/audio/zhubo_audio/zhuli_audio）
IGNORE_DIRS = {
    ".venv", "venv", ".idea",
    "__pycache__", ".pytest_cache",
    "dist", "build",
    "protected_src", "_cython_build",
    "logs", "audio_cache",
}

def rm(path: Path):
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)

def copytree(src: Path, dst: Path):
    def ignore_patterns(dirpath, names):
        ignore = set()
        for n in names:
            if n in IGNORE_DIRS:
                ignore.add(n)
            if n.endswith((".pyc", ".pyo")):
                ignore.add(n)
        return ignore
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst, ignore=ignore_patterns)

def main():
    rm(OUT)
    rm(DIST)
    OUT.mkdir(parents=True, exist_ok=True)

    # 收集要编译的 .py
    py_files = []
    for d in COMPILE_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        py_files.extend(base.rglob("*.py"))
    for f in COMPILE_FILES:
        p = ROOT / f
        if p.exists():
            py_files.append(p)

    if not py_files:
        print("❌ 没找到要编译的文件，请检查 COMPILE_DIRS/COMPILE_FILES")
        sys.exit(1)

    # 生成扩展模块列表
    exts = []
    for p in py_files:
        rel = p.relative_to(ROOT).with_suffix("")   # core/a.py -> core/a
        mod = ".".join(rel.parts)                   # core.a
        exts.append(Extension(mod, [str(p)]))

    # 编译
    setup(
        script_args=["build_ext", "--build-lib", str(OUT)],
        ext_modules=cythonize(
            exts,
            compiler_directives={"language_level": "3"},
            annotate=False,
        ),
        zip_safe=False,
    )

    # 复制项目到 protected_src（作为 PyInstaller 输入）
    copytree(ROOT, DIST)

    # 把编译好的 .pyd 覆盖到 protected_src，并删除对应 .py
    for compiled in OUT.rglob("*"):
        if compiled.suffix.lower() in {".pyd", ".so", ".dll"}:
            rel = compiled.relative_to(OUT)
            target = DIST / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(compiled, target)

            # 删除同名 .py
            maybe_py = target.with_suffix(".py")
            if maybe_py.exists():
                maybe_py.unlink()

    # 删除已编译目录下的 .py（保留 __init__.py）
    for d in COMPILE_DIRS:
        base = DIST / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if p.name == "__init__.py":
                continue
            p.unlink()

    # 删除已编译的根目录单文件
    for f in COMPILE_FILES:
        p = DIST / f
        if p.exists():
            p.unlink()

    # 保护：确保 app.py/main.py 还在（薄入口）
    if not (DIST / "app.py").exists():
        print("❌ protected_src 缺少 app.py（薄入口必须存在）")
        sys.exit(1)

    print("✅ Cython 编译完成")
    print(f"✅ PyInstaller 输入目录：{DIST}")

if __name__ == "__main__":
    main()
