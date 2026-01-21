# build_cython.py (NO .c in project)
import argparse
import shutil
import sys
from pathlib import Path

from setuptools import Extension, setup
from Cython.Build import cythonize

ROOT = Path(__file__).resolve().parent

COMPILE_DIRS = ["core", "audio", "api", "tts", "ui"]
COMPILE_FILES = ["config.py", "keywords.py", "zhuli_keywords.py", "logger_bootstrap.py"]

IGNORE_DIRS = {
    ".venv", "venv", ".idea",
    "__pycache__", ".pytest_cache",
    "dist", "build",
    "logs", "audio_cache",
}

def rm(p: Path):
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)

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
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    dist = Path(args.outdir).resolve()
    temp_root = dist.parent / "_cython_tmp"
    src_tmp = temp_root / "src"       # 放源码拷贝
    build_lib = temp_root / "buildlib"  # 放 .pyd
    build_tmp = temp_root / "buildtmp"  # 放编译中间文件
    gen_c_dir = temp_root / "gen_c"     # 放生成的 .c（只在 TEMP）

    rm(temp_root)
    rm(dist)

    # 1) 先把整个项目复制到 dist（资源都在这里，logo.ico/img/ffmpeg 都会带上）
    copytree(ROOT, dist)

    # 2) 再拷贝“要编译的源码”到 TEMP 的 src_tmp（避免在项目目录生成 .c）
    src_tmp.mkdir(parents=True, exist_ok=True)

    # 拷贝要编译的目录
    for d in COMPILE_DIRS:
        s = ROOT / d
        if s.exists():
            shutil.copytree(s, src_tmp / d, dirs_exist_ok=True)

    # 拷贝要编译的单文件
    for f in COMPILE_FILES:
        s = ROOT / f
        if s.exists():
            (src_tmp / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, src_tmp / f)

    # 3) 在 TEMP 里收集 .py（注意：这里全部用 src_tmp 下的路径）
    py_files = []
    for d in COMPILE_DIRS:
        base = src_tmp / d
        if base.exists():
            py_files.extend(base.rglob("*.py"))
    for f in COMPILE_FILES:
        p = src_tmp / f
        if p.exists():
            py_files.append(p)

    if not py_files:
        print("No python files to compile.")
        sys.exit(1)

    # 4) 生成 Extension（模块名仍以原项目结构为准）
    exts = []
    for p in py_files:
        rel = p.relative_to(src_tmp).with_suffix("")
        mod = ".".join(rel.parts)
        exts.append(Extension(mod, [str(p)]))

    # 5) 编译：生成的 .c 全进 gen_c_dir，.pyd 进 build_lib
    build_lib.mkdir(parents=True, exist_ok=True)
    build_tmp.mkdir(parents=True, exist_ok=True)
    gen_c_dir.mkdir(parents=True, exist_ok=True)

    setup(
        script_args=[
            "build_ext",
            "--build-lib", str(build_lib),
            "--build-temp", str(build_tmp),
        ],
        ext_modules=cythonize(
            exts,
            compiler_directives={"language_level": "3"},
            annotate=False,
            build_dir=str(gen_c_dir),  # ✅ 关键：.c 生成目录（TEMP）
        ),
        zip_safe=False,
    )

    # 6) 把 build_lib 里的 .pyd 覆盖到 dist 对应位置，并删除 dist 里的源码 .py（保留 __init__.py）
    for compiled in build_lib.rglob("*"):
        if compiled.suffix.lower() in {".pyd", ".so", ".dll"}:
            rel = compiled.relative_to(build_lib)
            target = dist / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(compiled, target)

            maybe_py = target.with_suffix(".py")
            if maybe_py.exists():
                maybe_py.unlink()

    # 删除 dist 里已编译目录下的 .py（保留 __init__.py）
    for d in COMPILE_DIRS:
        base = dist / d
        if base.exists():
            for p in base.rglob("*.py"):
                if p.name == "__init__.py":
                    continue
                p.unlink()

    for f in COMPILE_FILES:
        p = dist / f
        if p.exists():
            p.unlink()

    # 清理 TEMP（不留任何中间物）
    rm(temp_root)

    if not (dist / "app.py").exists():
        raise RuntimeError("protected src missing app.py (thin entry must exist)")

    print("OK protected src:", dist)

if __name__ == "__main__":
    main()
