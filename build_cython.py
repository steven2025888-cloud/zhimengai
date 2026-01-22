import argparse
import shutil
import sys
from pathlib import Path

from setuptools import Extension, setup
from Cython.Build import cythonize

ROOT = Path(__file__).resolve().parent

# 需要编译成 pyd 的目录/文件
COMPILE_DIRS = ["core", "audio", "api", "tts", "ui"]
COMPILE_FILES = ["config.py", "keywords.py", "zhuli_keywords.py", "logger_bootstrap.py"]

# 必须保留成 .py 的入口模块（否则 PyInstaller 分析不到依赖，UI/Playwright 容易丢）
EXCLUDE_FILES = {
    "core/entry_gui.py",
    "core/entry_service.py",
}

# 不复制到 protected_src 的目录
IGNORE_DIRS = {
    ".venv", "venv", ".idea",
    "__pycache__", ".pytest_cache",
    "dist", "build",
    "logs", "audio_cache",
    "_cython_tmp",
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

def rel_posix(p: Path, base: Path) -> str:
    return p.relative_to(base).as_posix()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", required=True, help="protected_src output directory (usually TEMP)")
    args = ap.parse_args()

    dist = Path(args.outdir).resolve()

    # TEMP 目录（所有 .c / build 中间文件都在这里，最后会删）
    temp_root = dist.parent / "_cython_tmp"
    src_tmp = temp_root / "src"
    build_lib = temp_root / "buildlib"
    build_tmp = temp_root / "buildtmp"
    gen_c_dir = temp_root / "gen_c"

    rm(temp_root)
    rm(dist)

    # 1) 复制整个项目到 dist（把资源也带上：img/ffmpeg/ui/style.qss/logo.ico 等）
    copytree(ROOT, dist)

    # 2) 拷贝要编译的源码到 TEMP/src（避免在项目目录生成 .c）
    src_tmp.mkdir(parents=True, exist_ok=True)

    for d in COMPILE_DIRS:
        s = ROOT / d
        if s.exists():
            shutil.copytree(s, src_tmp / d, dirs_exist_ok=True)

    for f in COMPILE_FILES:
        s = ROOT / f
        if s.exists():
            (src_tmp / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, src_tmp / f)

    # 3) 收集要编译的 py（排除入口模块）
    py_files = []
    for d in COMPILE_DIRS:
        base = src_tmp / d
        if base.exists():
            for p in base.rglob("*.py"):
                if rel_posix(p, src_tmp) in EXCLUDE_FILES:
                    continue
                py_files.append(p)

    for f in COMPILE_FILES:
        p = src_tmp / f
        if p.exists():
            py_files.append(p)

    if not py_files:
        raise RuntimeError("No python files to compile. Check COMPILE_DIRS/COMPILE_FILES.")

    # 4) 生成 Extension（模块名必须匹配包结构）
    exts = []
    for p in py_files:
        rel = p.relative_to(src_tmp).with_suffix("")
        mod = ".".join(rel.parts)
        exts.append(Extension(mod, [str(p)]))

    build_lib.mkdir(parents=True, exist_ok=True)
    build_tmp.mkdir(parents=True, exist_ok=True)
    gen_c_dir.mkdir(parents=True, exist_ok=True)

    # 5) 编译：.c -> gen_c_dir（TEMP），.pyd -> build_lib（TEMP）
    setup(
        script_args=["build_ext", "--build-lib", str(build_lib), "--build-temp", str(build_tmp)],
        ext_modules=cythonize(
            exts,
            compiler_directives={"language_level": "3"},
            annotate=False,
            build_dir=str(gen_c_dir),
        ),
        zip_safe=False,
    )

    # 6) 把 .pyd 覆盖到 dist 对应路径
    for compiled in build_lib.rglob("*"):
        if compiled.suffix.lower() in {".pyd", ".so", ".dll"}:
            rel = compiled.relative_to(build_lib)
            target = dist / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(compiled, target)

    # 7) 强制删除 dist 里“已编译目录”的 .py（保留 __init__.py 和入口模块）
    keep = set(EXCLUDE_FILES)
    for d in COMPILE_DIRS:
        base = dist / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            rp = p.relative_to(dist).as_posix()
            if p.name == "__init__.py":
                continue
            if rp in keep:
                continue
            p.unlink()

    # 8) 删除已编译的根目录单文件源码
    for f in COMPILE_FILES:
        p = dist / f
        if p.exists():
            p.unlink()

    # 9) 编译验证：必须有足够多的 .pyd，否则直接失败（避免“看似成功实际没加密”）
    pyd_count = len(list(dist.rglob("*.pyd")))
    if pyd_count < 10:
        raise RuntimeError(f"Encryption failed: only {pyd_count} .pyd found in protected_src.")

    # 10) 删除 TEMP（不留任何 .c 垃圾）
    rm(temp_root)

    # 11) 校验入口存在
    must = [
        dist / "app.py",
        dist / "main.py",
        dist / "core" / "entry_gui.py",
        dist / "core" / "entry_service.py",
    ]
    for x in must:
        if not x.exists():
            raise RuntimeError(f"protected src missing required file: {x}")

    print(f"OK protected src: {dist}")
    print(f".pyd count: {pyd_count}")

if __name__ == "__main__":
    main()
