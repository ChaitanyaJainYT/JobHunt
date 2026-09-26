"""Tectonic compile + self-heal retry (max 2). Never touches main.tex."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class LatexCompileError(Exception):
    def __init__(self, message: str, log: str = ""):
        super().__init__(message)
        self.log = log


def bundled_tectonic() -> Path | None:
    """Project-local copy (tools/tectonic/tectonic[.exe]). Gitignored, zero setup."""
    from src.utils import PROJECT_ROOT
    for name in ("tectonic.exe", "tectonic"):
        p = PROJECT_ROOT / "tools" / "tectonic" / name
        if p.is_file():
            return p
    return None


def find_tectonic() -> str | None:
    """Bundled copy first, then system PATH. Returns executable path or None."""
    b = bundled_tectonic()
    if b is not None:
        return str(b)
    return shutil.which("tectonic")


def tectonic_install_hint() -> str:
    """Platform-appropriate manual install instructions (used when missing)."""
    import sys
    base = "https://github.com/tectonic-typesetting/tectonic/releases"
    if sys.platform == "darwin":
        import platform
        triple = ("aarch64-apple-darwin" if platform.machine() == "arm64"
                  else "x86_64-apple-darwin")
        return (f"Download tectonic-0.17.0-{triple}.tar.gz from {base}, unpack "
                "the tectonic binary to tools/tectonic/ (or run ./setup.sh), and retry. ")
    if sys.platform == "win32":
        return ("Download tectonic-*-x86_64-pc-windows-msvc.zip from "
                f"{base}, unpack tectonic.exe to tools/tectonic/ "
                "(or run .\\setup.ps1), and retry. ")
    if sys.platform.startswith("linux"):
        import platform
        machine = platform.machine()
        triple = ("aarch64-unknown-linux-musl" if machine in ("aarch64", "arm64")
                  else "x86_64-unknown-linux-musl")
        return (f"Download tectonic-0.17.0-{triple}.tar.gz from {base}, unpack "
                "the tectonic binary to tools/tectonic/ (or run ./setup.sh), and retry. ")
    return (f"Download the tectonic build for your platform from {base}, unpack "
            "the binary to tools/tectonic/, and retry. ")


def _tectonic_cmd(tex_path: Path, outdir: Path) -> list[str]:
    exe = find_tectonic() or "tectonic"
    return [exe, "--outdir", str(outdir), str(tex_path)]


def compile_tex(tex_path: Path, timeout: int = 600) -> Path:
    # NOTE: the very first tectonic run downloads the LaTeX bundle (~100 files)
    # and can take several minutes; later runs finish in seconds (cache warm).
    exe = find_tectonic()
    if not exe:
        raise LatexCompileError(
            "tectonic not found (no tools/tectonic/ copy, not in PATH). "
            + tectonic_install_hint() +
            f"Your .tex is preserved at {tex_path}."
        )
    outdir = tex_path.parent
    try:
        r = subprocess.run(_tectonic_cmd(tex_path, outdir),
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise LatexCompileError(f"tectonic timed out after {timeout}s on {tex_path.name}.") from e
    if r.returncode != 0:
        log = (r.stdout or "") + "\n" + (r.stderr or "")
        (tex_path.parent / (tex_path.stem + ".tectonic.log")).write_text(log, encoding="utf-8")
        raise LatexCompileError(
            f"tectonic failed on {tex_path.name} (exit {r.returncode}). "
            f"Log saved to {tex_path.stem}.tectonic.log.", log=log)
    pdf = tex_path.with_suffix(".pdf")
    if not pdf.exists():
        # tectonic may name output after \\jobname; fallback: any fresh pdf
        cands = sorted(outdir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        if cands:
            return cands[0]
        raise LatexCompileError(f"tectonic exit 0 but no PDF found for {tex_path.name}.")
    return pdf


def compile_with_heal(tex_path: Path, api_key: str = "", model: str = "gemini-3.6-flash",
                      groq_key: str = "", groq_model: str = "openai/gpt-oss-120b",
                      max_retries: int = 2,
                      timeout: int = 600) -> Path:
    """Try compile; on failure ask LLM to fix syntax, retry. Preserves .tex + .log."""
    from src import llm
    last: LatexCompileError | None = None
    for attempt in range(max_retries + 1):
        try:
            return compile_tex(tex_path, timeout=timeout)
        except LatexCompileError as e:
            last = e
            if "not found in PATH" in str(e) or attempt >= max_retries:
                raise
            broken = tex_path.read_text(encoding="utf-8")
            fixed = llm.fix_latex(broken, e.log or str(e),
                                  api_key=api_key, model=model,
                                  groq_key=groq_key, groq_model=groq_model)
            tex_path.write_text(fixed, encoding="utf-8")
    raise last  # pragma: no cover
