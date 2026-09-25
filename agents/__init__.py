"""Standalone form agents package.

Intentionally avoids eager submodule imports so `python -m agents.<module>`
does not preload the target module and trigger runpy warnings.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "CVProfileData",
    "load_cv_from_markdown",
    "BrowserUseLiveFormAgent",
    "run_browser_use_live_form_agent",
    "AgentBrowserLiveFormAgent",
    "run_agent_browser_live_form_agent",
    "RepoMultiAgentLearningSystem",
    "LearningMemoryCurator",
    "SystemConfig",
    "MemoryEnhancedAgent",
]


def __getattr__(name: str) -> Any:
    if name in {"CVProfileData", "load_cv_from_markdown"}:
        from agents.form_filler_agent import CVProfileData, load_cv_from_markdown

        mapping = {
            "CVProfileData": CVProfileData,
            "load_cv_from_markdown": load_cv_from_markdown,
        }
        return mapping[name]

    if name in {"BrowserUseLiveFormAgent", "run_browser_use_live_form_agent"}:
        from agents.browser_use_live_form_agent import (
            BrowserUseLiveFormAgent,
            run_browser_use_live_form_agent,
        )

        mapping = {
            "BrowserUseLiveFormAgent": BrowserUseLiveFormAgent,
            "run_browser_use_live_form_agent": run_browser_use_live_form_agent,
        }
        return mapping[name]

    if name in {"AgentBrowserLiveFormAgent", "run_agent_browser_live_form_agent"}:
        from agents.agent_browser_live_form_agent import (
            AgentBrowserLiveFormAgent,
            run_agent_browser_live_form_agent,
        )

        mapping = {
            "AgentBrowserLiveFormAgent": AgentBrowserLiveFormAgent,
            "run_agent_browser_live_form_agent": run_agent_browser_live_form_agent,
        }
        return mapping[name]

    if name in {"RepoMultiAgentLearningSystem", "LearningMemoryCurator", "SystemConfig"}:
        from agents.repo_multi_agent_learning_system import (
            LearningMemoryCurator,
            RepoMultiAgentLearningSystem,
            SystemConfig,
        )

        mapping = {
            "RepoMultiAgentLearningSystem": RepoMultiAgentLearningSystem,
            "LearningMemoryCurator": LearningMemoryCurator,
            "SystemConfig": SystemConfig,
        }
        return mapping[name]

    if name in {"MemoryEnhancedAgent"}:
        from agents.memory_enhanced_agent import MemoryEnhancedAgent

        mapping = {
            "MemoryEnhancedAgent": MemoryEnhancedAgent,
        }
        return mapping[name]

    raise AttributeError(f"module 'agents' has no attribute {name!r}")
