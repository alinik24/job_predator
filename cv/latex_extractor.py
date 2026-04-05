"""
LaTeX / Overleaf CV text extractor.

Supports:
  - moderncv (most popular LaTeX CV class)
  - altacv
  - europasscv
  - Generic LaTeX with \section, \subsection, environments

Strategy:
  1. Parse LaTeX source using pylatexenc to strip markup
  2. Extract structured sections using regex patterns
  3. Return clean text for LLM parsing
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger


def extract_text_from_latex(path: str | Path) -> str:
    """
    Extract readable text from a LaTeX CV source file.
    Returns text formatted to preserve structure (sections, entries).
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"LaTeX file not found: {path}")

    source = path.read_text(encoding="utf-8", errors="replace")

    # Remove comments
    source = re.sub(r"%[^\n]*", "", source)

    # Try pylatexenc for clean text extraction
    text = _try_pylatexenc(source)
    if not text:
        # Fallback: manual regex stripping
        text = _manual_latex_strip(source)

    logger.info(f"[LaTeX] Extracted {len(text)} chars from {path.name}")
    return text


def extract_structured_sections(path: str | Path) -> Dict[str, str]:
    """
    Extract structured sections from a moderncv-style LaTeX CV.
    Returns dict: section_name -> content_text
    """
    path = Path(path)
    source = path.read_text(encoding="utf-8", errors="replace")
    source = re.sub(r"%[^\n]*", "", source)

    sections: Dict[str, str] = {}

    # Match \section{...} blocks
    pattern = re.compile(
        r"\\section\{([^}]+)\}(.*?)(?=\\section\{|\Z)",
        re.DOTALL,
    )
    for match in pattern.finditer(source):
        name = match.group(1).strip()
        content = match.group(2).strip()
        sections[name] = _manual_latex_strip(content)

    return sections


def extract_personal_info_moderncv(source: str) -> Dict[str, str]:
    """
    Extract personal info from moderncv preamble.
    Handles: \name, \title, \address, \phone, \email, \homepage, \social
    """
    info: Dict[str, str] = {}

    def _get(cmd: str) -> Optional[str]:
        m = re.search(rf"\\{cmd}\{{([^}}]*)\}}", source)
        return m.group(1).strip() if m else None

    def _get_two(cmd: str) -> Optional[str]:
        m = re.search(rf"\\{cmd}\{{([^}}]*)\}}\{{([^}}]*)\}}", source)
        return f"{m.group(1)} {m.group(2)}".strip() if m else None

    name = _get_two("name") or _get("name")
    if name:
        info["name"] = name

    for field in ["email", "phone", "homepage", "title", "address"]:
        val = _get(field)
        if val:
            info[field] = val

    # \social[linkedin]{handle} or \social[github]{handle}
    for social in re.finditer(r"\\social\[(\w+)\]\{([^}]+)\}", source):
        info[social.group(1)] = social.group(2)

    return info


def _try_pylatexenc(source: str) -> str:
    try:
        from pylatexenc.latex2text import LatexNodes2Text

        converter = LatexNodes2Text(
            math_mode="with-delimiters",
            strict_latex_spaces=False,
        )
        text = converter.latex_to_text(source)
        # Remove blank lines from stripped environments
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    except Exception as e:
        logger.debug(f"[LaTeX] pylatexenc failed: {e}")
        return ""


def _manual_latex_strip(source: str) -> str:
    """
    Manual LaTeX markup removal for when pylatexenc is unavailable.
    Preserves text content while removing commands.
    """
    # Remove environments (keep content)
    text = re.sub(r"\\begin\{[^}]+\}", "", source)
    text = re.sub(r"\\end\{[^}]+\}", "", text)

    # Extract text from common content commands
    # \cventry{dates}{title}{org}{location}{grade}{description}
    text = re.sub(
        r"\\cventry\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}",
        lambda m: f"{m.group(2)} at {m.group(3)} ({m.group(1)}) - {m.group(6)}",
        text,
    )

    # \cvitem{label}{content}
    text = re.sub(
        r"\\cvitem\{([^}]*)\}\{([^}]*)\}",
        lambda m: f"{m.group(1)}: {m.group(2)}",
        text,
    )

    # \cvlistitem{text}
    text = re.sub(r"\\cvlistitem\{([^}]*)\}", r"• \1", text)

    # \section{title}
    text = re.sub(r"\\section\{([^}]+)\}", r"\n## \1\n", text)
    text = re.sub(r"\\subsection\{([^}]+)\}", r"\n### \1\n", text)

    # Remove remaining commands with arguments
    text = re.sub(r"\\[a-zA-Z]+\*?\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+\*?\[[^\]]*\]\{([^}]*)\}", r"\1", text)

    # Remove standalone commands
    text = re.sub(r"\\[a-zA-Z]+\*?", " ", text)

    # Remove braces
    text = text.replace("{", "").replace("}", "")

    # Clean whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)

    return text.strip()


def find_overleaf_main_file(directory: str | Path) -> Optional[Path]:
    """
    In an Overleaf project directory, find the main .tex file.
    Looks for main.tex, cv.tex, resume.tex, or any .tex with \documentclass.
    """
    directory = Path(directory)
    candidates = []

    for tex_file in directory.rglob("*.tex"):
        content = tex_file.read_text(encoding="utf-8", errors="replace")
        if r"\documentclass" in content:
            candidates.append(tex_file)

    # Prefer common names
    for name in ["main.tex", "cv.tex", "resume.tex", "lebenslauf.tex"]:
        for c in candidates:
            if c.name.lower() == name:
                return c

    return candidates[0] if candidates else None
