"""Shared filesystem + logging helpers."""
from __future__ import annotations

import logging
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = PROJECT_ROOT / "output"


def sanitize_filename(name: str) -> str:
    """Make safe for Windows filenames, keep readable."""
    name = (name or "Unknown").strip()
    name = re.sub(r"[<>:\"/\\|?*]", "_", name)
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_.")
    return name[:60] or "Unknown"


def ensure_output_dir(company: str, job_id: str) -> Path:
    folder = OUTPUT_ROOT / f"{sanitize_filename(company)}_{sanitize_filename(job_id)}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def get_logger(name: str, log_file: Path | None = None) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger


def base_resume_path() -> Path:
    """Return main.tex if present else bundled sample (warn, don't crash)."""
    main = PROJECT_ROOT / "main.tex"
    if main.exists():
        return main
    return PROJECT_ROOT / "main.tex.sample"
