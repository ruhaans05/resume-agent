"""Thin wrapper around the Tectonic LaTeX engine."""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


def tectonic_path() -> str | None:
    """Return the path to the tectonic binary, or None if not installed."""
    return shutil.which("tectonic")


@dataclass
class CompileResult:
    ok: bool
    pdf_path: Path | None
    log: str


def compile_tex(tex_file: Path, timeout: int = 180) -> CompileResult:
    """Compile a .tex file to PDF with Tectonic.

    The PDF is written next to the source file. Returns a CompileResult with the
    captured Tectonic output (Tectonic prints diagnostics to stderr).
    """
    tex_file = Path(tex_file).resolve()
    binary = tectonic_path()
    if binary is None:
        return CompileResult(
            ok=False,
            pdf_path=None,
            log=(
                "Tectonic is not installed. Install it with `brew install tectonic` "
                "(macOS) or see https://tectonic-typesetting.github.io/install.html"
            ),
        )
    if not tex_file.exists():
        return CompileResult(ok=False, pdf_path=None, log=f"File not found: {tex_file}")

    try:
        proc = subprocess.run(
            [binary, str(tex_file)],
            cwd=str(tex_file.parent),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return CompileResult(ok=False, pdf_path=None, log=f"Compilation timed out after {timeout}s.")

    log = (proc.stdout or "") + (proc.stderr or "")
    pdf_path = tex_file.with_suffix(".pdf")
    ok = proc.returncode == 0 and pdf_path.exists()
    if not pdf_path.exists():
        pdf_path = None
    return CompileResult(ok=ok, pdf_path=pdf_path, log=log.strip())


def open_file(path: Path) -> bool:
    """Open a file with the OS default application. Returns True on success."""
    path = Path(path)
    if not path.exists():
        return False
    try:
        system = platform.system()
        if system == "Darwin":
            subprocess.run(["open", str(path)], check=False)
        elif system == "Windows":
            import os

            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
        return True
    except Exception:
        return False
