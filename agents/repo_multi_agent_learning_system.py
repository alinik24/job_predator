"""Multi-agent orchestrator for run collection and memory curation."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from agents.agent_browser_live_form_agent import run_agent_browser_live_form_agent
from agents.browser_use_live_form_agent import run_browser_use_live_form_agent
from agents.form_agent_assets import (
    DEFAULT_COVER_LETTER_PDF,
    DEFAULT_CV_MD,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_LLM_MODEL,
)


@dataclass
class SystemConfig:
    cv_md: Path = DEFAULT_CV_MD
    cover_letter_pdf: Path = DEFAULT_COVER_LETTER_PDF
    llm_model: str = DEFAULT_LLM_MODEL
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    context_path: Path = Path(__file__).resolve().parents[1] / "memory" / "website_context.md"
    learning_runs_root: Path = Path(__file__).resolve().parents[1] / "output" / "learning_runs"
    curated_memory_path: Path = Path(__file__).resolve().parents[1] / "memory" / "learning_memory.md"


class LearningMemoryCurator:
    def __init__(self, cfg: SystemConfig) -> None:
        self.cfg = cfg

    def _iter_run_logs(self) -> List[Path]:
        root = self.cfg.learning_runs_root
        if not root.exists():
            return []
        return sorted(root.rglob("run_log.md"), reverse=True)

    @staticmethod
    def _extract_unresolved(md: str) -> List[str]:
        out: List[str] = []
        for line in md.splitlines():
            if line.strip().startswith("- `") and "reason:" in line:
                out.append(line.strip())
        return out

    @staticmethod
    def _extract_human_events(md: str) -> List[str]:
        out: List[str] = []
        in_section = False
        for line in md.splitlines():
            s = line.strip()
            if s.lower().startswith("## human events"):
                in_section = True
                continue
            if in_section and s.startswith("## "):
                break
            if in_section and s.startswith("- "):
                out.append(s)
        return out

    @staticmethod
    def _domain_from_path(path: Path) -> str:
        m = re.search(r"\d{8}_\d{6}_(.+)$", path.parent.name)
        if m:
            return m.group(1)
        return "unknown"

    def curate(self, max_runs: int = 80) -> Dict[str, Any]:
        runs = self._iter_run_logs()[:max_runs]
        domain_map: Dict[str, Dict[str, Any]] = {}
        for run_md in runs:
            text = run_md.read_text(encoding="utf-8", errors="ignore")
            domain = self._domain_from_path(run_md)
            rec = domain_map.setdefault(domain, {"unresolved": [], "human_events": [], "runs": 0})
            rec["runs"] += 1
            rec["unresolved"].extend(self._extract_unresolved(text))
            rec["human_events"].extend(self._extract_human_events(text))

        lines: List[str] = []
        lines.append("# Learning Memory")
        lines.append("")
        lines.append(f"- Updated: {datetime.now().isoformat()}")
        lines.append(f"- Source runs scanned: {len(runs)}")
        lines.append("")
        lines.append("## Global Playbook")
        lines.append("")
        lines.append("- Respect existing field values before writing.")
        lines.append("- Re-snapshot after any navigation/drawer/modal change.")
        lines.append("- For captcha/date/file upload/manual blockers: record unresolved + suggestion, continue other fields.")
        lines.append("- Preserve session and do not close browser after completion.")
        lines.append("")
        lines.append("## Domain Knowledge")
        lines.append("")

        for domain, rec in sorted(domain_map.items(), key=lambda x: x[0]):
            lines.append(f"### {domain}")
            lines.append("")
            lines.append(f"- Runs: {rec['runs']}")
            unresolved = rec["unresolved"][:40]
            human_events = rec["human_events"][:40]
            lines.append("- Recurrent unresolved patterns:")
            if unresolved:
                for u in unresolved:
                    lines.append(f"  - {u}")
            else:
                lines.append("  - none")
            lines.append("- Frequent human interventions:")
            if human_events:
                for e in human_events:
                    lines.append(f"  - {e}")
            else:
                lines.append("  - none")
            lines.append("")

        self.cfg.curated_memory_path.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.curated_memory_path.write_text("\n".join(lines), encoding="utf-8")
        return {
            "curated_memory_path": str(self.cfg.curated_memory_path),
            "runs_scanned": len(runs),
            "domains": sorted(domain_map.keys()),
        }


class RepoMultiAgentLearningSystem:
    def __init__(self, cfg: SystemConfig | None = None) -> None:
        self.cfg = cfg or SystemConfig()
        self.curator = LearningMemoryCurator(self.cfg)

    async def run_browser_use(self, url: str) -> Dict[str, Any]:
        return await run_browser_use_live_form_agent(
            url=url,
            cv_md_path=self.cfg.cv_md,
            cover_letter_pdf=self.cfg.cover_letter_pdf,
            llm_model=self.cfg.llm_model,
            embedding_model=self.cfg.embedding_model,
        )

    def run_agent_browser(self, url: str) -> Dict[str, Any]:
        return run_agent_browser_live_form_agent(
            url=url,
            cv_md_path=self.cfg.cv_md,
            cover_letter_pdf=self.cfg.cover_letter_pdf,
            llm_model=self.cfg.llm_model,
            embedding_model=self.cfg.embedding_model,
            follow=True,
            follow_interval=1.5,
            session_name="job_form_assistant",
            profile_path=None,
            headed=True,
        )

    def run(self, engine: str, url: str) -> Dict[str, Any]:
        normalized = (engine or "").strip().lower()
        if normalized in {"browser-use", "browser_use", "bu"}:
            return asyncio.run(self.run_browser_use(url))
        if normalized in {"agent-browser", "agent_browser", "ab"}:
            return self.run_agent_browser(url)
        raise ValueError("Unsupported engine. Use 'browser-use' or 'agent-browser'.")


def _main() -> None:
    parser = argparse.ArgumentParser(description="Repo multi-agent learning system", add_help=False)
    parser.add_argument("engine", nargs="?", default="")
    parser.add_argument("url", nargs="?", default="")
    parser.add_argument("--curate", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    args, _unknown = parser.parse_known_args()

    system = RepoMultiAgentLearningSystem()
    if args.help:
        print("Usage:")
        print("  python -m agents.repo_multi_agent_learning_system <engine> <job-url>")
        print("  python -m agents.repo_multi_agent_learning_system --curate")
        print("Engine values: browser-use | agent-browser")
        return

    if args.curate:
        result = system.curator.curate()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    engine = (args.engine or "").strip()
    if not engine:
        engine = input("Engine [browser-use/agent-browser]: ").strip()
    url = (args.url or "").strip()
    if not url:
        url = input("Job application URL: ").strip()
    if not url:
        raise SystemExit("URL is required.")
    result = system.run(engine=engine, url=url)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()

