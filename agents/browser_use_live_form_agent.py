"""browser-use repo-native job form agent wrapper."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from agents.env_loader import load_env_files
from agents.form_filler_agent import load_cv_from_markdown
from agents.form_agent_assets import (
    DEFAULT_COVER_LETTER_PDF,
    DEFAULT_COVER_LETTER_TEXT,
    DEFAULT_CV_MD,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_LLM_MODEL,
    ensure_placeholder_cover_letter_pdf,
)


def _load_project_env_once() -> None:
    load_env_files(project_root=Path(__file__).resolve().parents[1])


def _bootstrap_provider_env(llm_model: str, embedding_model: str) -> None:
    _load_project_env_once()
    llm_api_key = (os.getenv("LLM_API_KEY") or "").strip()
    llm_api_base = (os.getenv("LLM_API_BASE_URL") or "").strip()
    if llm_api_key:
        os.environ.setdefault("OPENAI_API_KEY", llm_api_key)
    if llm_api_base:
        os.environ.setdefault("OPENAI_BASE_URL", llm_api_base.rstrip("/"))
    os.environ.setdefault("OPENAI_MODEL", llm_model)
    os.environ.setdefault("OPENAI_EMBEDDING_MODEL", embedding_model)


class BrowserUseLiveFormAgent:
    """Thin integration over browser-use SDK for your CV-based form filling workflow."""

    def __init__(
        self,
        cv_md_path: Path = DEFAULT_CV_MD,
        cover_letter_pdf: Path = DEFAULT_COVER_LETTER_PDF,
        llm_model: str = DEFAULT_LLM_MODEL,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        cdp_url: Optional[str] = None,
    ) -> None:
        self.cv_md_path = Path(cv_md_path)
        self.cover_letter_pdf = ensure_placeholder_cover_letter_pdf(cover_letter_pdf)
        self.llm_model = (llm_model or DEFAULT_LLM_MODEL).strip()
        self.embedding_model = (embedding_model or DEFAULT_EMBEDDING_MODEL).strip()
        self.cdp_url = (cdp_url or os.getenv("BROWSER_USE_CDP_URL") or os.getenv("FORM_AGENT_CDP_URL") or "").strip()

        self.project_root = Path(__file__).resolve().parents[1]
        self.output_dir = self.project_root / "output"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.memory_path = self.output_dir / "browser_use_form_memory.json"
        self.context_path = self.project_root / "memory" / "website_context.md"
        self.run_root = self.output_dir / "learning_runs" / "browser_use"
        self.run_root.mkdir(parents=True, exist_ok=True)

        _bootstrap_provider_env(self.llm_model, self.embedding_model)
        self.profile = load_cv_from_markdown(self.cv_md_path)
        self.memory = self._load_memory()

    def _load_memory(self) -> Dict[str, Any]:
        if self.memory_path.exists():
            try:
                obj = json.loads(self.memory_path.read_text(encoding="utf-8"))
                if isinstance(obj, dict):
                    obj.setdefault("runs", [])
                    return obj
            except Exception:
                pass
        return {"runs": []}

    def _save_memory(self) -> None:
        self.memory_path.write_text(json.dumps(self.memory, ensure_ascii=False, indent=2), encoding="utf-8")

    def _build_cv_payload(self) -> Dict[str, Any]:
        full_name = (self.profile.full_name or "").strip()
        parts = [p for p in full_name.split() if p]
        return {
            "first_name": parts[0] if parts else "",
            "last_name": " ".join(parts[1:]) if len(parts) > 1 else "",
            "full_name": full_name,
            "email": self.profile.email or "",
            "phone": self.profile.phone or "",
            "location": self.profile.location or "Paderborn, Germany",
            "linkedin": self.profile.linkedin_url or "",
            "github": self.profile.github_url or "",
            "summary": self.profile.summary or "",
            "cover_letter_placeholder": DEFAULT_COVER_LETTER_TEXT,
            "cv_text": (self.profile.raw_text or "")[:9000],
            "cover_letter_pdf": str(self.cover_letter_pdf),
        }

    def _build_task(self, url: str) -> str:
        host = urlparse(url).netloc or "target site"
        payload = self._build_cv_payload()
        context = ""
        if self.context_path.exists():
            try:
                context = self.context_path.read_text(encoding="utf-8").strip()
            except Exception:
                context = ""
        return f"""
You are filling a real job application form.

Target URL: {url}
Allowed domain: {host}
Source of truth profile JSON:
{json.dumps(payload, ensure_ascii=False, indent=2)}
Additional website context/instructions:
{context or "(none)"}

Mandatory behavior:
1) Open the target URL and fill as many fields as possible from the profile.
2) Never submit the application.
3) Respect user-entered values: if a field already has meaningful data, keep it.
4) For date pickers, complex dropdowns, file uploads, captcha, 2FA, or blocked fields: do not invent values.
5) If blocked on a manual step, continue with other fields and leave a suggestion.
6) For repeated sections (experience/education), use the next relevant item, avoid duplicate reuse.
7) If UI drawers/sections appear after edits, continue filling newly revealed fields.
8) Final answer must be JSON only with this schema:
{{
  "status": "ok" | "partial",
  "summary": "<short summary>",
  "unresolved": [
    {{"field":"<field label>", "reason":"<why unresolved>", "suggestion":"<suggested value>"}}
  ]
}}
"""

    def _build_llm(self) -> Any:
        try:
            from browser_use import ChatBrowserUse  # type: ignore

            if (os.getenv("BROWSER_USE_API_KEY") or "").strip():
                try:
                    return ChatBrowserUse(model=self.llm_model)
                except TypeError:
                    return ChatBrowserUse()
        except Exception:
            pass

        from browser_use import ChatOpenAI  # type: ignore

        kwargs: Dict[str, Any] = {"model": self.llm_model}
        api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        if api_key:
            kwargs["api_key"] = api_key
        base_url = (os.getenv("OPENAI_BASE_URL") or "").strip()
        if base_url:
            kwargs["base_url"] = base_url
        return ChatOpenAI(**kwargs)

    def _build_browser(self, url: str) -> Any:
        from browser_use import Browser  # type: ignore

        kwargs: Dict[str, Any] = {
            "headless": False,
            "keep_alive": True,
            "allowed_domains": [urlparse(url).netloc],
            "window_size": {"width": 1280, "height": 900},
        }
        if self.cdp_url:
            kwargs["cdp_url"] = self.cdp_url
        return Browser(**kwargs)

    async def run(self, url: str) -> Dict[str, Any]:
        from browser_use import Agent  # type: ignore

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        host = re.sub(r"[^a-zA-Z0-9_.-]+", "_", ((re.sub(r"^https?://", "", url)).split("/")[0] or "site"))
        run_dir = self.run_root / f"{ts}_{host}"
        run_dir.mkdir(parents=True, exist_ok=True)
        conversation_path = run_dir / "conversation.md"
        use_vision = (os.getenv("BROWSER_USE_VISION") or "auto").strip()
        vision_detail = (os.getenv("BROWSER_USE_VISION_DETAIL") or "auto").strip()

        llm = self._build_llm()
        browser = self._build_browser(url)
        task = self._build_task(url)
        history: Any = None
        final_result = ""
        success: Optional[bool] = None
        urls = []
        screenshots = []
        unresolved = []
        parsed = None
        action_names = []
        model_actions = []
        model_outputs = []
        errors = []
        fatal_error = ""

        try:
            history = await Agent(
                task=task,
                llm=llm,
                browser=browser,
                save_conversation_path=str(conversation_path),
                available_file_paths=[str(self.cv_md_path), str(self.cover_letter_pdf), str(self.context_path)],
                use_vision=use_vision,  # allows VLM-assisted perception when available.
                vision_detail_level=vision_detail,
            ).run()

            if hasattr(history, "final_result"):
                try:
                    final_result = str(history.final_result() or "").strip()
                except Exception:
                    final_result = ""
            if hasattr(history, "is_successful"):
                try:
                    success = history.is_successful()
                except Exception:
                    success = None
            if hasattr(history, "urls"):
                try:
                    urls = list(history.urls() or [])
                except Exception:
                    urls = []
            if hasattr(history, "screenshot_paths"):
                try:
                    screenshots = list(history.screenshot_paths() or [])
                except Exception:
                    screenshots = []
            try:
                parsed = json.loads(final_result)
                unresolved = parsed.get("unresolved", []) if isinstance(parsed, dict) else []
            except Exception:
                parsed = None

            try:
                action_names = list(history.action_names() or [])
            except Exception:
                pass
            try:
                model_actions = history.model_actions() or []
            except Exception:
                pass
            try:
                model_outputs = history.model_outputs() or []
            except Exception:
                pass
            try:
                errors = history.errors() or []
            except Exception:
                pass
        except Exception as exc:
            fatal_error = str(exc)
            errors.append(f"fatal: {fatal_error}")

        actions_jsonl = run_dir / "model_actions.jsonl"
        with actions_jsonl.open("w", encoding="utf-8") as f:
            for a in model_actions if isinstance(model_actions, list) else []:
                f.write(json.dumps(a, ensure_ascii=False, default=str) + "\n")

        outputs_jsonl = run_dir / "model_outputs.jsonl"
        with outputs_jsonl.open("w", encoding="utf-8") as f:
            for o in model_outputs if isinstance(model_outputs, list) else []:
                f.write(json.dumps(o, ensure_ascii=False, default=str) + "\n")

        copied_screenshots = []
        if screenshots:
            shot_dir = run_dir / "screenshots"
            shot_dir.mkdir(parents=True, exist_ok=True)
            for idx, src in enumerate(screenshots, start=1):
                try:
                    src_path = Path(str(src))
                    if not src_path.exists():
                        continue
                    target = shot_dir / f"shot_{idx:03d}{src_path.suffix or '.png'}"
                    shutil.copy2(src_path, target)
                    copied_screenshots.append(str(target))
                except Exception:
                    continue

        elements_md = run_dir / "website_elements.md"
        element_lines = [
            "# Website Elements & Decisions",
            "",
            f"- URL: {url}",
            f"- Timestamp: {datetime.now().isoformat()}",
            "",
            "## Decision Trace",
            "",
        ]
        if action_names:
            for i, n in enumerate(action_names[:300], start=1):
                element_lines.append(f"{i}. `{n}`")
        else:
            element_lines.append("- none")
        element_lines += [
            "",
            "## Selectors / Targets",
            "",
        ]
        selectors = []
        for row in model_actions if isinstance(model_actions, list) else []:
            if isinstance(row, dict):
                sel = row.get("selector") or row.get("element") or row.get("target") or ""
                if sel:
                    selectors.append(str(sel))
        if selectors:
            dedup = []
            seen = set()
            for s in selectors:
                key = s.strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    dedup.append(s.strip())
            for s in dedup[:300]:
                element_lines.append(f"- `{s}`")
        else:
            element_lines.append("- none")
        element_lines += [
            "",
            "## Unresolved",
            "",
        ]
        if unresolved:
            for item in unresolved:
                if isinstance(item, dict):
                    element_lines.append(
                        f"- field=`{item.get('field','')}` reason=`{item.get('reason','')}` suggestion=`{item.get('suggestion','')}`"
                    )
        else:
            element_lines.append("- none")
        elements_md.write_text("\n".join(element_lines), encoding="utf-8")

        run_record = {
            "timestamp": datetime.now().isoformat(),
            "url": url,
            "success": success,
            "fatal_error": fatal_error or None,
            "final_result": final_result,
            "unresolved": unresolved,
            "copied_screenshots": copied_screenshots,
        }
        self.memory["runs"] = ([run_record] + self.memory.get("runs", []))[:50]
        self._save_memory()

        md_path = run_dir / "run_log.md"
        md_lines = [
            "# Browser-Use Run Log",
            "",
            f"- Timestamp: {datetime.now().isoformat()}",
            f"- URL: {url}",
            f"- CV: {self.cv_md_path}",
            f"- Cover letter PDF: {self.cover_letter_pdf}",
            f"- Context file: {self.context_path}",
            f"- Model: {self.llm_model}",
            f"- Embedding model: {self.embedding_model}",
            f"- CDP URL: {self.cdp_url or '(none)'}",
            "",
            "## Outcome",
            "",
            f"- Success: {success}",
            f"- Fatal error: `{fatal_error or ''}`",
            f"- Final result raw: `{(final_result or '')[:1200]}`",
            f"- Unresolved fields: {len(unresolved)}",
            "",
            "## Actions",
            "",
        ]
        if action_names:
            for i, n in enumerate(action_names[:200], start=1):
                md_lines.append(f"{i}. `{n}`")
        else:
            md_lines.append("- none")
        md_lines += [
            "",
            "## Errors",
            "",
        ]
        if errors:
            for e in errors[:120]:
                if e:
                    md_lines.append(f"- `{str(e)[:500]}`")
        else:
            md_lines.append("- none")
        md_lines += [
            "",
            "## Artifact Files",
            "",
            f"- conversation: `{conversation_path}`",
            f"- actions jsonl: `{actions_jsonl}`",
            f"- outputs jsonl: `{outputs_jsonl}`",
            f"- website elements: `{elements_md}`",
        ]
        if copied_screenshots:
            md_lines.append("- copied screenshots:")
            for p in copied_screenshots:
                md_lines.append(f"  - `{p}`")
        md_path.write_text("\n".join(md_lines), encoding="utf-8")

        return {
            "engine": "browser-use",
            "url": url,
            "task_status": "ok" if success else "partial",
            "final_result_json": parsed,
            "final_result_raw": final_result,
            "unresolved": unresolved,
            "visited_urls": urls,
            "screenshots": screenshots,
            "cv_md_path": str(self.cv_md_path),
            "cover_letter_pdf": str(self.cover_letter_pdf),
            "context_path": str(self.context_path),
            "llm_model": self.llm_model,
            "embedding_model": self.embedding_model,
            "cdp_url": self.cdp_url or None,
            "memory_file": str(self.memory_path),
            "use_vision": use_vision,
            "vision_detail_level": vision_detail,
            "run_dir": str(run_dir),
            "run_log_md": str(md_path),
            "conversation_md": str(conversation_path),
            "actions_jsonl": str(actions_jsonl),
            "outputs_jsonl": str(outputs_jsonl),
            "website_elements_md": str(elements_md),
            "copied_screenshots": copied_screenshots,
            "fatal_error": fatal_error or None,
        }


async def run_browser_use_live_form_agent(
    url: str,
    cv_md_path: Path = DEFAULT_CV_MD,
    cover_letter_pdf: Path = DEFAULT_COVER_LETTER_PDF,
    llm_model: str = DEFAULT_LLM_MODEL,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    cdp_url: Optional[str] = None,
) -> Dict[str, Any]:
    agent = BrowserUseLiveFormAgent(
        cv_md_path=cv_md_path,
        cover_letter_pdf=cover_letter_pdf,
        llm_model=llm_model,
        embedding_model=embedding_model,
        cdp_url=cdp_url,
    )
    return await agent.run(url=url)


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="browser-use job application assistant",
        add_help=False,
    )
    parser.add_argument("url", nargs="?", default="")
    parser.add_argument("-h", "--help", action="store_true")
    args, _unknown = parser.parse_known_args()

    if args.help:
        print("Usage: python -m agents.browser_use_live_form_agent <job-url>")
        print("If <job-url> is omitted, you will be prompted.")
        print(f"Static CV: {DEFAULT_CV_MD}")
        print(f"Static cover letter PDF: {DEFAULT_COVER_LETTER_PDF}")
        print(f"Static llm model: {DEFAULT_LLM_MODEL}")
        print(f"Static embedding model: {DEFAULT_EMBEDDING_MODEL}")
        print("Optional env: BROWSER_USE_CDP_URL (connect existing browser via CDP)")
        return

    url = (args.url or "").strip()
    if not url:
        url = input("Job application URL (paste from your browser tab): ").strip()
    if not url:
        raise SystemExit("URL is required.")

    result = asyncio.run(run_browser_use_live_form_agent(url=url))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
