"""Memory-enhanced runner that executes engines and feeds vector memory."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from agents.repo_multi_agent_learning_system import RepoMultiAgentLearningSystem
from memory.vector_memory import VectorMemoryStore


class MemoryEnhancedAgent:
    def __init__(self, memory_db_path: Path | str = Path("memory") / "vector_memory.sqlite3") -> None:
        self.system = RepoMultiAgentLearningSystem()
        self.memory = VectorMemoryStore(db_path=memory_db_path)

    def _ingest_agent_browser_artifacts(self, result: Dict[str, Any], domain: str) -> int:
        count = 0
        commands_path = Path(str(result.get("commands_jsonl") or ""))
        if commands_path.exists():
            for line in commands_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                cmd = row.get("cmd", [])
                rc = int(row.get("returncode", 0))
                self.memory.add_interaction(
                    url=result.get("url", ""),
                    domain=domain,
                    action_type="cli_command",
                    element_selector=" ".join(cmd[:4]) if isinstance(cmd, list) else str(cmd)[:120],
                    element_type="command",
                    success=(rc == 0),
                    error_message=(row.get("stderr") or "")[:300] if rc != 0 else None,
                    solution=(row.get("stdout") or "")[:300],
                )
                count += 1

        decisions_path = Path(str(result.get("decisions_jsonl") or ""))
        if decisions_path.exists():
            for line in decisions_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                decision = str(row.get("decision") or "decision")
                label = str(row.get("field_label") or "")
                value = str(row.get("value") or "")
                self.memory.add_interaction(
                    url=result.get("url", ""),
                    domain=domain,
                    action_type=decision,
                    element_selector=label,
                    element_type="form_field",
                    success=decision not in {"required-unresolved", "manual-required"},
                    error_message=(row.get("reason") or "")[:240] or None,
                    solution=value[:300],
                    extra=row if isinstance(row, dict) else {},
                )
                count += 1

        events_path = Path(str(result.get("human_events_jsonl") or ""))
        if events_path.exists():
            for line in events_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                try:
                    evt = json.loads(line)
                except Exception:
                    continue
                event_type = str(evt.get("type") or "manual")
                label = str(evt.get("label") or evt.get("name") or evt.get("id") or "")
                value = str(evt.get("value") or "")
                self.memory.add_intervention(
                    url=result.get("url", ""),
                    domain=domain,
                    intervention_type=event_type,
                    description=f"Human event on {label}",
                    user_action=f"{event_type} value={value}",
                    solution_strategy="User manually interacted and agent continued.",
                    success=True,
                    element_info=evt,
                )
                count += 1

        states_path = Path(str(result.get("state_snapshots_jsonl") or ""))
        if states_path.exists():
            for line in states_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                try:
                    st = json.loads(line)
                except Exception:
                    continue
                self.memory.add_interaction(
                    url=result.get("url", ""),
                    domain=domain,
                    action_type="state_snapshot",
                    element_selector=f"cycle={st.get('cycle','')}",
                    element_type="snapshot",
                    success=True,
                    error_message=None,
                    solution=f"fields_seen={st.get('fields_seen',0)} unresolved={st.get('unresolved',0)} changed={st.get('changed',False)}",
                    extra=st if isinstance(st, dict) else {},
                )
                count += 1
        return count

    def _ingest_browser_use_artifacts(self, result: Dict[str, Any], domain: str) -> int:
        count = 0
        actions_path = Path(str(result.get("actions_jsonl") or ""))
        if actions_path.exists():
            for line in actions_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                self.memory.add_interaction(
                    url=result.get("url", ""),
                    domain=domain,
                    action_type=str(row.get("action") or row.get("type") or "action"),
                    element_selector=str(row.get("selector") or row.get("element") or ""),
                    element_type=str(row.get("element_type") or "unknown"),
                    success=bool(row.get("success", True)),
                    error_message=str(row.get("error") or "")[:300] or None,
                    solution=str(row.get("result") or row.get("output") or "")[:300],
                    extra=row if isinstance(row, dict) else {},
                )
                count += 1
        website_elements = Path(str(result.get("website_elements_md") or ""))
        if website_elements.exists():
            text = website_elements.read_text(encoding="utf-8", errors="ignore")
            self.memory.add_element_strategy(
                domain=domain,
                element_type="website_elements",
                element_attributes={"source": str(website_elements)},
                strategy=text[:2000],
                success_rate=0.7,
                variations=[],
            )
            count += 1
        unresolved = result.get("unresolved", [])
        if isinstance(unresolved, list):
            for u in unresolved:
                if not isinstance(u, dict):
                    continue
                self.memory.add_intervention(
                    url=result.get("url", ""),
                    domain=domain,
                    intervention_type="unresolved_field",
                    description=str(u.get("field") or "unknown"),
                    user_action="pending human/manual handling",
                    solution_strategy=str(u.get("suggestion") or ""),
                    success=False,
                    element_info=u,
                )
                count += 1
        return count

    def run(self, engine: str, url: str) -> Dict[str, Any]:
        result = self.system.run(engine=engine, url=url)
        domain = (urlparse(result.get("url", url)).netloc or "unknown").lower()

        if (result.get("engine") or "").strip().lower() == "agent-browser":
            inserted = self._ingest_agent_browser_artifacts(result, domain)
        else:
            inserted = self._ingest_browser_use_artifacts(result, domain)

        # Build quick strategy memory for unresolved entries.
        unresolved = result.get("unresolved", [])
        if isinstance(unresolved, list):
            for u in unresolved:
                if not isinstance(u, dict):
                    continue
                field = str(u.get("field") or "")
                suggestion = str(u.get("suggestion") or "")
                if field:
                    self.memory.add_element_strategy(
                        domain=domain,
                        element_type="form_field",
                        element_attributes={"label": field},
                        strategy=f"Suggested value: {suggestion}",
                        success_rate=0.6,
                        variations=[],
                    )

        retrieved = self.memory.search_similar(
            query=f"form filling strategy for {domain}",
            top_k=8,
            domain=domain,
        )
        result["vector_memory_inserted"] = inserted
        result["retrieved_memory_examples"] = retrieved
        result["vector_memory_db"] = str(Path("memory") / "vector_memory.sqlite3")
        return result


def _main() -> None:
    parser = argparse.ArgumentParser(description="Memory-enhanced multi-agent form runner", add_help=False)
    parser.add_argument("engine", nargs="?", default="")
    parser.add_argument("url", nargs="?", default="")
    parser.add_argument("--query-memory", default="")
    parser.add_argument("-h", "--help", action="store_true")
    args, _unknown = parser.parse_known_args()

    agent = MemoryEnhancedAgent()
    if args.help:
        print("Usage:")
        print("  python -m agents.memory_enhanced_agent <engine> <url>")
        print("  python -m agents.memory_enhanced_agent --query-memory \"query text\"")
        return

    if args.query_memory:
        result = agent.memory.search_similar(args.query_memory, top_k=10)
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

    result = agent.run(engine=engine, url=url)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
