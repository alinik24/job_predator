"""Standalone live form assistant powered by agent-browser CLI."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.env_loader import load_env_files
from agents.form_filler_agent import CVProfileData, load_cv_from_markdown
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


@dataclass
class SnapshotField:
    ref: str
    role: str
    label: str
    required: bool


class AgentBrowserLiveFormAgent:
    def __init__(
        self,
        cv_md_path: Path,
        cover_letter_pdf: Path = DEFAULT_COVER_LETTER_PDF,
        llm_model: str = DEFAULT_LLM_MODEL,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        session_name: str = "job_form_assistant",
        profile_path: Optional[Path] = None,
        follow_interval: float = 1.5,
        headed: bool = True,
    ) -> None:
        self.cv_md_path = Path(cv_md_path)
        self.cover_letter_pdf = ensure_placeholder_cover_letter_pdf(cover_letter_pdf)
        self.llm_model = (llm_model or DEFAULT_LLM_MODEL).strip()
        self.embedding_model = (embedding_model or DEFAULT_EMBEDDING_MODEL).strip()
        os.environ.setdefault("OPENAI_MODEL", self.llm_model)
        os.environ.setdefault("OPENAI_EMBEDDING_MODEL", self.embedding_model)
        _load_project_env_once()
        self.session_name = session_name
        self.follow_interval = float(max(0.8, follow_interval))
        self.headed = headed
        self.cdp = (os.getenv("AGENT_BROWSER_CDP") or os.getenv("FORM_AGENT_CDP_URL") or "").strip()
        self.auto_connect = (os.getenv("AGENT_BROWSER_AUTO_CONNECT") or "").strip().lower() in {"1", "true", "yes", "on"}

        self.project_root = Path(__file__).resolve().parents[1]
        self.output_dir = self.project_root / "output"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.profile_path = profile_path or (self.output_dir / "agent_browser_profile")
        self.profile_path.mkdir(parents=True, exist_ok=True)
        self.memory_path = self.output_dir / "agent_browser_form_memory.json"
        self.context_path = self.project_root / "memory" / "website_context.md"
        self.run_root = self.output_dir / "learning_runs" / "agent_browser"
        self.run_root.mkdir(parents=True, exist_ok=True)

        self.memory = self._load_memory()
        self.cv_profile = load_cv_from_markdown(self.cv_md_path)
        self.cv_data = self._prepare_cv_data(self.cv_profile)
        self.sequence_cursors: Dict[str, int] = {}
        self.used_semantic_values: Dict[str, set[str]] = {}
        self._command_log: List[Dict[str, Any]] = []
        self._decision_log: List[Dict[str, Any]] = []
        self._human_events: List[Dict[str, Any]] = []
        self._state_snapshots: deque[Dict[str, Any]] = deque(maxlen=30)
        self._last_snapshot_text: str = ""
        self._current_run_dir: Optional[Path] = None
        self._visual_artifacts: List[Dict[str, Any]] = []
        self._capture_every_cycles = int(max(1, int(os.getenv("FORM_AGENT_CAPTURE_EVERY_CYCLES", "2"))))
        self._idle_backoff_seconds = float(max(self.follow_interval, float(os.getenv("FORM_AGENT_IDLE_BACKOFF_SECONDS", "3.0"))))
        self._agent_browser_cmd = self._resolve_agent_browser_cmd()
        self._assert_cli_present()

    def _resolve_agent_browser_cmd(self) -> List[str]:
        candidates: List[Optional[str]] = [
            shutil.which("agent-browser"),
            shutil.which("agent-browser.cmd"),
            shutil.which("agent-browser.exe"),
        ]
        appdata = os.environ.get("APPDATA", "").strip()
        if appdata:
            candidates.append(str(Path(appdata) / "npm" / "agent-browser.cmd"))
            candidates.append(str(Path(appdata) / "npm" / "agent-browser"))

        for c in candidates:
            if c and Path(c).exists():
                return [c]

        npx = shutil.which("npx") or shutil.which("npx.cmd")
        if npx:
            # Use local/global package or fetch once in non-interactive mode.
            return [npx, "-y", "agent-browser"]

        raise RuntimeError(
            "agent-browser CLI not found.\n"
            "Install once and retry:\n"
            "  npm i -g agent-browser\n"
            "  agent-browser install"
        )

    def _assert_cli_present(self) -> None:
        proc = subprocess.run(
            self._agent_browser_cmd + ["--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if proc.returncode != 0:
            raise RuntimeError(f"Unable to run agent-browser --version:\n{err or out}")
        if not out and err:
            out = err
        if not out.strip():
            raise RuntimeError("agent-browser is installed but returned empty version output.")

    def _ab_base(self) -> List[str]:
        cmd = [
            *self._agent_browser_cmd,
            "--session-name",
            self.session_name,
            "--profile",
            str(self.profile_path),
        ]
        if self.cdp:
            cmd += ["--cdp", self.cdp]
        elif self.auto_connect:
            cmd += ["--auto-connect"]
        if self.headed:
            cmd += ["--headed"]
        return cmd

    def _run_ab(self, args: List[str], allow_error: bool = True) -> str:
        cmd = self._ab_base() + args
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=90)
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        self._command_log.append(
            {
                "ts": datetime.now().isoformat(),
                "cmd": cmd,
                "returncode": proc.returncode,
                "stdout": out[:5000],
                "stderr": err[:5000],
            }
        )
        if proc.returncode != 0 and not allow_error:
            raise RuntimeError(f"agent-browser command failed: {' '.join(args)}\n{err or out}")
        if proc.returncode != 0:
            return ""
        return out

    @staticmethod
    def _safe_parse_json_maybe_wrapped(raw: str) -> Any:
        text = (raw or "").strip()
        if not text:
            return None
        for candidate in (text, text.strip('"')):
            try:
                return json.loads(candidate)
            except Exception:
                continue
        # fallback for quoted+escaped json string
        try:
            first = json.loads(text)
            if isinstance(first, str):
                return json.loads(first)
            return first
        except Exception:
            return None

    def _context_text(self) -> str:
        if self.context_path.exists():
            try:
                return self.context_path.read_text(encoding="utf-8").strip()
            except Exception:
                return ""
        return ""

    def _inject_user_event_recorder(self) -> None:
        js = r"""
(() => {
  if (window.__jpaUserEventRecorderInstalled) return "already";
  window.__jpaUserEventRecorderInstalled = true;
  window.__jpaUserEvents = window.__jpaUserEvents || [];
  const push = (evt, extra = {}) => {
    const t = evt && evt.target ? evt.target : null;
    const label = t && t.labels && t.labels[0] ? (t.labels[0].innerText || "").trim() : "";
    window.__jpaUserEvents.push({
      ts: new Date().toISOString(),
      type: evt ? evt.type : "unknown",
      trusted: evt ? !!evt.isTrusted : false,
      tag: t ? (t.tagName || "").toLowerCase() : "",
      id: t ? (t.id || "") : "",
      name: t ? (t.name || "") : "",
      label,
      value: t && typeof t.value !== "undefined" ? String(t.value).slice(0, 240) : "",
      ...extra,
    });
  };
  ["click", "change", "input", "keydown", "focusin", "submit"].forEach((ev) => {
    document.addEventListener(ev, (e) => push(e), true);
  });
  return "ok";
})();
"""
        self._run_ab(["eval", js], allow_error=True)

    def _drain_user_events(self) -> List[Dict[str, Any]]:
        js = r"""
JSON.stringify((() => {
  const out = Array.isArray(window.__jpaUserEvents) ? window.__jpaUserEvents : [];
  window.__jpaUserEvents = [];
  return out;
})())
"""
        raw = self._run_ab(["eval", js], allow_error=True)
        parsed = self._safe_parse_json_maybe_wrapped(raw)
        if isinstance(parsed, list):
            events: List[Dict[str, Any]] = []
            for item in parsed:
                if isinstance(item, dict):
                    events.append(item)
            return events
        return []

    def _start_run_artifacts(self, url: str) -> None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        host = re.sub(r"[^a-zA-Z0-9_.-]+", "_", ((re.sub(r"^https?://", "", url)).split("/")[0] or "site"))
        self._current_run_dir = self.run_root / f"{ts}_{host}"
        self._current_run_dir.mkdir(parents=True, exist_ok=True)

    def _flush_run_artifacts(self, url: str, unresolved: List[Dict[str, Any]], total_seen: int, total_filled: int) -> Dict[str, str]:
        if not self._current_run_dir:
            return {}
        cmd_path = self._current_run_dir / "commands.jsonl"
        with cmd_path.open("w", encoding="utf-8") as f:
            for row in self._command_log:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

        decisions_path = self._current_run_dir / "decisions.jsonl"
        with decisions_path.open("w", encoding="utf-8") as f:
            for row in self._decision_log:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

        events_path = self._current_run_dir / "human_events.jsonl"
        with events_path.open("w", encoding="utf-8") as f:
            for row in self._human_events:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

        states_path = self._current_run_dir / "state_snapshots.jsonl"
        with states_path.open("w", encoding="utf-8") as f:
            for row in self._state_snapshots:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

        md_path = self._current_run_dir / "run_log.md"
        lines: List[str] = []
        lines.append(f"# Agent-Browser Run Log")
        lines.append("")
        lines.append(f"- Timestamp: {datetime.now().isoformat()}")
        lines.append(f"- URL: {url}")
        lines.append(f"- CV: {self.cv_md_path}")
        lines.append(f"- Cover letter PDF: {self.cover_letter_pdf}")
        lines.append(f"- Context file: {self.context_path}")
        lines.append(f"- Model: {self.llm_model}")
        lines.append(f"- Embedding model: {self.embedding_model}")
        lines.append(f"- CDP: {self.cdp or '(none)'}")
        lines.append(f"- Auto-connect: {self.auto_connect}")
        lines.append("")
        lines.append("## Result")
        lines.append("")
        lines.append(f"- Fields seen: {total_seen}")
        lines.append(f"- Fields filled: {total_filled}")
        lines.append(f"- Unresolved count: {len(unresolved)}")
        lines.append("")
        if unresolved:
            lines.append("## Unresolved Fields")
            lines.append("")
            for u in unresolved:
                lines.append(f"- `{u.get('field', '')}` | reason: `{u.get('reason', '')}` | suggestion: `{u.get('suggested', '')}`")
            lines.append("")
        lines.append("## Human Events")
        lines.append("")
        if self._human_events:
            for e in self._human_events[-120:]:
                lines.append(
                    f"- {e.get('ts','')} | type=`{e.get('type','')}` | trusted=`{e.get('trusted','')}` | "
                    f"tag=`{e.get('tag','')}` | label=`{e.get('label','')}` | value=`{e.get('value','')}`"
                )
        else:
            lines.append("- none captured")
        lines.append("")
        lines.append("## State Snapshots")
        lines.append("")
        if self._state_snapshots:
            for s in list(self._state_snapshots)[-20:]:
                lines.append(f"- {s.get('ts','')} | fields_seen={s.get('fields_seen',0)} | unresolved={s.get('unresolved',0)}")
        else:
            lines.append("- none")
        lines.append("")
        lines.append("## Command Log Files")
        lines.append("")
        lines.append(f"- commands: `{cmd_path}`")
        lines.append(f"- decisions: `{decisions_path}`")
        lines.append(f"- human events: `{events_path}`")
        lines.append(f"- state snapshots: `{states_path}`")
        if self._visual_artifacts:
            lines.append("- visual artifacts:")
            for item in self._visual_artifacts[-40:]:
                lines.append(f"  - `{item.get('kind','')}`: `{item.get('path','')}`")
        md_path.write_text("\n".join(lines), encoding="utf-8")
        return {
            "run_dir": str(self._current_run_dir),
            "run_log_md": str(md_path),
            "commands_jsonl": str(cmd_path),
            "decisions_jsonl": str(decisions_path),
            "human_events_jsonl": str(events_path),
            "state_snapshots_jsonl": str(states_path),
        }

    @staticmethod
    def _normalize(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "").strip()).lower()

    def _load_memory(self) -> Dict[str, Any]:
        if self.memory_path.exists():
            try:
                obj = json.loads(self.memory_path.read_text(encoding="utf-8"))
                if isinstance(obj, dict):
                    obj.setdefault("fields", {})
                    obj.setdefault("interventions", [])
                    obj.setdefault("runs", [])
                    return obj
            except Exception:
                pass
        return {"fields": {}, "interventions": [], "runs": []}

    def _save_memory(self) -> None:
        self.memory_path.write_text(json.dumps(self.memory, ensure_ascii=False, indent=2), encoding="utf-8")

    def _record_decision(
        self,
        decision: str,
        field_label: str = "",
        ref: str = "",
        value: str = "",
        reason: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        row: Dict[str, Any] = {
            "ts": datetime.now().isoformat(),
            "decision": decision,
            "field_label": field_label,
            "ref": ref,
            "value": (value or "")[:240],
            "reason": reason,
        }
        if extra:
            row.update(extra)
        self._decision_log.append(row)

    def _remember_intervention(self, event: Dict[str, Any]) -> None:
        recs = self.memory.setdefault("interventions", [])
        recs.append(
            {
                "ts": datetime.now().isoformat(),
                "event": event,
            }
        )
        # Keep memory bounded.
        if len(recs) > 500:
            self.memory["interventions"] = recs[-500:]

    def _remember(self, key: str, value: str) -> None:
        v = (value or "").strip()
        if not v:
            return
        rec = self.memory["fields"].setdefault(key, {"accepted": []})
        accepted = rec.setdefault("accepted", [])
        rec["accepted"] = [v] + [x for x in accepted if self._normalize(str(x)) != self._normalize(v)]
        rec["accepted"] = rec["accepted"][:12]
        rec["updated_at"] = datetime.now().isoformat()

    def _learned_values(self, key: str) -> List[str]:
        rec = self.memory["fields"].get(key, {})
        vals = rec.get("accepted", []) if isinstance(rec, dict) else []
        out: List[str] = []
        seen = set()
        for item in vals:
            s = str(item or "").strip()
            if s and self._normalize(s) not in seen:
                seen.add(self._normalize(s))
                out.append(s)
        return out

    def _prepare_cv_data(self, profile: CVProfileData) -> Dict[str, Any]:
        parts = [p for p in (profile.full_name or "").split() if p]
        exp = profile.work_experience or []
        return {
            "first_name": parts[0] if parts else "",
            "last_name": " ".join(parts[1:]) if len(parts) > 1 else "",
            "full_name": profile.full_name or "",
            "email": profile.email or "",
            "phone": profile.phone or "",
            "location": profile.location or "Paderborn, Germany",
            "linkedin": profile.linkedin_url or "",
            "github": profile.github_url or "",
            "summary": profile.summary or "",
            "cover_letter_placeholder": DEFAULT_COVER_LETTER_TEXT,
            "experience_titles": [str(e.get("title") or "").strip() for e in exp if e.get("title")],
            "experience_companies": [str(e.get("company") or "").strip() for e in exp if e.get("company")],
        }

    def _semantic_group(self, f: SnapshotField) -> str:
        t = self._normalize(f.label)
        if any(k in t for k in ("first name", "given name")):
            return "first_name"
        if any(k in t for k in ("last name", "surname", "family name")):
            return "last_name"
        if "confirm" in t and "email" in t:
            return "confirm_email"
        if "email" in t:
            return "email"
        if any(k in t for k in ("phone", "mobile", "telephone")):
            return "phone"
        if "linkedin" in t:
            return "linkedin"
        if any(k in t for k in ("github", "website", "portfolio")):
            return "website"
        if any(k in t for k in ("company", "employer", "organization")):
            return "exp_company"
        if any(k in t for k in ("title", "position", "role")):
            return "exp_title"
        if any(k in t for k in ("from", "start date", "start")):
            return "exp_from"
        if any(k in t for k in ("to", "end date", "until")):
            return "exp_to"
        if any(k in t for k in ("city", "location", "address")):
            return "location"
        if any(k in t for k in ("message", "summary", "motivation", "description", "about")):
            return "summary"
        return "generic"

    def _source_candidates(self, group: str) -> List[str]:
        d = self.cv_data
        mapping: Dict[str, List[str]] = {
            "first_name": [d.get("first_name", "")],
            "last_name": [d.get("last_name", "")],
            "confirm_email": [d.get("email", "")],
            "email": [d.get("email", "")],
            "phone": [d.get("phone", "")],
            "linkedin": [d.get("linkedin", "")],
            "website": [d.get("github", ""), d.get("linkedin", "")],
            "exp_title": d.get("experience_titles", []),
            "exp_company": d.get("experience_companies", []),
            "exp_from": [],
            "exp_to": ["Present"],
            "location": [d.get("location", "")],
            "summary": [d.get("summary", ""), d.get("cover_letter_placeholder", "")],
            "generic": [d.get("cover_letter_placeholder", "")],
        }
        vals = mapping.get(group, [])
        out: List[str] = []
        seen = set()
        for v in vals:
            s = str(v or "").strip()
            if s and self._normalize(s) not in seen:
                seen.add(self._normalize(s))
                out.append(s)
        return out

    def _pick_sequential_value(self, group: str, candidates: List[str]) -> str:
        usable = [c for c in candidates if str(c or "").strip()]
        if not usable:
            return ""
        used = self.used_semantic_values.setdefault(group, set())
        cursor = self.sequence_cursors.get(group, 0)
        for idx in range(cursor, len(usable)):
            v = usable[idx].strip()
            if self._normalize(v) not in used:
                self.sequence_cursors[group] = idx + 1
                used.add(self._normalize(v))
                return v
        return usable[min(cursor, len(usable) - 1)].strip()

    def _parse_snapshot_fields(self, snap: str) -> List[SnapshotField]:
        fields: List[SnapshotField] = []
        pattern = re.compile(r'^\s*[-*]?\s*(?P<role>[^\[]+?)\s*\[ref=(?P<ref>e\d+)\](?P<rest>.*)$')
        for line in snap.splitlines():
            m = pattern.search(line)
            if not m:
                continue
            role_part = m.group("role").strip()
            role = self._normalize(role_part.split('"')[0])
            if not any(x in role for x in ("textbox", "combobox", "textarea", "text field", "input", "select")):
                continue
            label_match = re.search(r'"([^"]+)"', role_part)
            label = label_match.group(1).strip() if label_match else role_part
            fields.append(
                SnapshotField(
                    ref=f"@{m.group('ref')}",
                    role=role,
                    label=label,
                    required="required" in self._normalize(m.group("rest") or ""),
                )
            )
        return fields

    def _snapshot_fields(self) -> List[SnapshotField]:
        snap = self._run_ab(["snapshot", "-i"], allow_error=False)
        self._last_snapshot_text = snap
        return self._parse_snapshot_fields(snap)

    def _get_value(self, ref: str) -> str:
        out = self._run_ab(["get", "value", ref, "--json"], allow_error=True)
        if not out:
            return ""
        try:
            obj = json.loads(out)
            data = obj.get("data", obj)
            if isinstance(data, dict):
                for key in ("value", "text", "result"):
                    v = data.get(key)
                    if isinstance(v, str):
                        return v.strip()
            if isinstance(data, str):
                return data.strip()
        except Exception:
            pass
        return ""

    def _fill_ref(self, ref: str, value: str) -> bool:
        v = (value or "").strip()
        if not v:
            return False
        self._run_ab(["fill", ref, v], allow_error=True)
        return True

    def _capture_visual_artifacts(self, cycle: int, changed: bool) -> None:
        if not self._current_run_dir or not changed:
            return
        if cycle % self._capture_every_cycles != 0:
            return
        shots_dir = self._current_run_dir / "screenshots"
        shots_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%H%M%S")
        normal = shots_dir / f"cycle_{cycle:04d}_{stamp}.png"
        annotated = shots_dir / f"cycle_{cycle:04d}_{stamp}_annotated.png"
        self._run_ab(["screenshot", str(normal)], allow_error=True)
        self._run_ab(["screenshot", "--annotate", str(annotated)], allow_error=True)
        self._visual_artifacts.append({"kind": "screenshot", "path": str(normal)})
        self._visual_artifacts.append({"kind": "screenshot_annotated", "path": str(annotated)})

    def _persist_snapshot_artifacts(self, cycle: int, snap: str, fields: List[SnapshotField]) -> None:
        if not self._current_run_dir:
            return
        snap_dir = self._current_run_dir / "snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        snap_file = snap_dir / f"snapshot_{cycle:04d}.md"
        parsed_file = snap_dir / f"fields_{cycle:04d}.json"
        snap_file.write_text(snap, encoding="utf-8")
        parsed_file.write_text(
            json.dumps(
                [
                    {
                        "ref": f.ref,
                        "role": f.role,
                        "label": f.label,
                        "required": f.required,
                    }
                    for f in fields
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self._visual_artifacts.append({"kind": "snapshot", "path": str(snap_file)})
        self._visual_artifacts.append({"kind": "parsed_fields", "path": str(parsed_file)})

    def _inject_helper_overlay(self, suggestions: List[Dict[str, Any]]) -> None:
        payload = json.dumps(suggestions, ensure_ascii=False)
        js = f"""
(() => {{
  const suggestions = {payload};
  const by = (s) => String(s || "").toLowerCase().replace(/\\s+/g, " ").trim();
  let panel = document.getElementById("__jpa_ab_panel");
  if (!panel) {{
    panel = document.createElement("div");
    panel.id = "__jpa_ab_panel";
    panel.style.cssText = "position:fixed;right:18px;bottom:18px;z-index:2147483647;max-width:430px;width:min(430px,90vw);background:rgba(24,24,27,.96);color:#f4f4f5;border:1px solid #3f3f46;border-radius:12px;padding:10px 12px;font:12px/1.4 ui-sans-serif,system-ui;box-shadow:0 10px 30px rgba(0,0,0,.35)";
    document.body.appendChild(panel);
  }}
  panel.innerHTML = `
    <div style="font-weight:600;margin-bottom:6px">Form Assistant</div>
    <div style="opacity:.85;margin-bottom:8px">Focus a field then click Apply or Copy.</div>
    <div style="display:flex;gap:8px">
      <button id="__jpa_ab_apply" style="border:1px solid #52525b;background:#18181b;color:#f4f4f5;border-radius:8px;padding:6px 10px;cursor:pointer">Apply suggestion</button>
      <button id="__jpa_ab_copy" style="border:1px solid #52525b;background:#18181b;color:#f4f4f5;border-radius:8px;padding:6px 10px;cursor:pointer">Copy suggestion</button>
    </div>
    <div id="__jpa_ab_status" style="margin-top:8px;opacity:.9"></div>`;
  const findForFocused = () => {{
    const el = document.activeElement;
    if (!el) return [null, "No focused field."];
    const tag = by(el.getAttribute("aria-label") || el.getAttribute("placeholder") || el.name || el.id);
    const s = suggestions.find(x => tag.includes(by(x.label)) || by(x.label).includes(tag)) || null;
    if (!s) return [null, "No suggestion for focused field."];
    return [s, ""];
  }};
  const status = (t, ok=true) => {{
    const el = document.getElementById("__jpa_ab_status");
    if (!el) return;
    el.textContent = t || "";
    el.style.color = ok ? "#86efac" : "#fca5a5";
  }};
  const apply = () => {{
    const [s, msg] = findForFocused();
    if (!s) return status(msg, false);
    const v = (s.suggested || (s.candidates && s.candidates[0]) || "").trim();
    if (!v) return status("Empty suggestion.", false);
    const el = document.activeElement;
    if (!el) return status("No focused field.", false);
    if (el.tagName === "SELECT") {{
      let ok = false;
      for (const o of Array.from(el.options || [])) {{
        const t = by(o.textContent);
        if (t === by(v) || t.includes(by(v)) || by(v).includes(t)) {{ el.value = o.value; ok = true; break; }}
      }}
      if (!ok) return status("Could not match select option.", false);
    }} else {{
      el.value = v;
    }}
    el.dispatchEvent(new Event("input", {{ bubbles: true }}));
    el.dispatchEvent(new Event("change", {{ bubbles: true }}));
    el.dataset.jpaUserDone = "1";
    return status("Applied suggestion.", true);
  }};
  const copy = async () => {{
    const [s, msg] = findForFocused();
    if (!s) return status(msg, false);
    const v = (s.suggested || (s.candidates && s.candidates[0]) || "").trim();
    if (!v) return status("Empty suggestion.", false);
    try {{
      await navigator.clipboard.writeText(v);
      return status("Copied.", true);
    }} catch {{
      return status("Copy blocked.", false);
    }}
  }};
  const ap = document.getElementById("__jpa_ab_apply");
  const cp = document.getElementById("__jpa_ab_copy");
  if (ap) ap.onclick = apply;
  if (cp) cp.onclick = () => {{ void copy(); }};
}})();
"""
        self._run_ab(["eval", js], allow_error=True)

    def run(self, url: str, follow: bool = True) -> Dict[str, Any]:
        self._command_log = []
        self._decision_log = []
        self._human_events = []
        self._state_snapshots.clear()
        self._visual_artifacts = []
        self._start_run_artifacts(url)
        self._run_ab(["open", url], allow_error=False)
        self._run_ab(["wait", "--load", "domcontentloaded"], allow_error=True)
        self._inject_user_event_recorder()

        unresolved: List[Dict[str, Any]] = []
        total_seen = 0
        total_filled = 0
        cycle = 0
        last_snapshot_hash = ""
        last_unresolved: List[Dict[str, Any]] = []
        last_suggestions: List[Dict[str, Any]] = []

        while True:
            cycle += 1
            events = self._drain_user_events()
            if events:
                self._human_events.extend(events)
                for evt in events:
                    if isinstance(evt, dict):
                        self._remember_intervention(evt)
                        if evt.get("trusted"):
                            label = str(evt.get("label") or evt.get("name") or evt.get("id") or "").strip()
                            value = str(evt.get("value") or "").strip()
                            if label and value:
                                self._remember(f"{self._normalize(label)}|manual", value)
                                self._record_decision(
                                    decision="human-intervention",
                                    field_label=label,
                                    value=value,
                                    reason=str(evt.get("type") or "event"),
                                )

            snap = self._run_ab(["snapshot", "-i"], allow_error=False)
            self._last_snapshot_text = snap
            fields = self._parse_snapshot_fields(snap)
            snap_hash = hashlib.sha1(snap.encode("utf-8", errors="ignore")).hexdigest()
            changed = snap_hash != last_snapshot_hash
            if changed:
                self._persist_snapshot_artifacts(cycle, snap, fields)
                self._capture_visual_artifacts(cycle, changed=True)
                last_snapshot_hash = snap_hash

            total_seen = max(total_seen, len(fields))
            unresolved = []
            suggestions: List[Dict[str, Any]] = []

            if not changed and not events and follow:
                self._inject_helper_overlay(last_suggestions)
                self._state_snapshots.append(
                    {
                        "ts": datetime.now().isoformat(),
                        "cycle": cycle,
                        "fields_seen": len(fields),
                        "unresolved": len(last_unresolved),
                        "changed": False,
                        "events": 0,
                        "snapshot_preview": self._last_snapshot_text[:1800],
                    }
                )
                self._save_memory()
                time.sleep(self._idle_backoff_seconds)
                continue

            for f in fields:
                current_value = self._get_value(f.ref)
                key = f"{self._normalize(f.label)}|{f.role}"
                if current_value:
                    self._remember(key, current_value)
                    self._record_decision(
                        decision="kept-existing-value",
                        field_label=f.label,
                        ref=f.ref,
                        value=current_value,
                        reason="already-filled",
                    )
                    continue

                group = self._semantic_group(f)
                learned = self._learned_values(key)
                source = self._source_candidates(group)
                merged = learned + [x for x in source if self._normalize(x) not in {self._normalize(y) for y in learned}]
                suggestion = self._pick_sequential_value(group, merged)

                hard = any(k in self._normalize(f.label) for k in ("captcha", "date", "month", "year", "upload", "resume"))
                suggestions.append(
                    {
                        "label": f.label,
                        "name": "",
                        "type": f.role,
                        "required": f.required,
                        "suggested": suggestion,
                        "candidates": merged[:8],
                        "hard": hard,
                    }
                )
                if hard:
                    self._record_decision(
                        decision="manual-required",
                        field_label=f.label,
                        ref=f.ref,
                        value=suggestion,
                        reason="hard-field",
                    )
                    unresolved.append({"field": f.label, "reason": "manual-step", "suggested": suggestion})
                    continue
                if suggestion and self._fill_ref(f.ref, suggestion):
                    total_filled += 1
                    self._remember(key, suggestion)
                    self._record_decision(
                        decision="filled-by-agent",
                        field_label=f.label,
                        ref=f.ref,
                        value=suggestion,
                        reason=group,
                    )
                elif f.required:
                    self._record_decision(
                        decision="required-unresolved",
                        field_label=f.label,
                        ref=f.ref,
                        value=suggestion,
                        reason="not-filled",
                    )
                    unresolved.append({"field": f.label, "reason": "not-filled", "suggested": suggestion})

            self._state_snapshots.append(
                {
                    "ts": datetime.now().isoformat(),
                    "cycle": cycle,
                    "fields_seen": len(fields),
                    "unresolved": len(unresolved),
                    "changed": changed,
                    "events": len(events),
                    "snapshot_preview": self._last_snapshot_text[:1800],
                }
            )
            self._inject_helper_overlay(suggestions)
            last_suggestions = suggestions
            last_unresolved = unresolved
            self._save_memory()
            if not follow:
                break
            time.sleep(self.follow_interval)

        current_url = self._run_ab(["get", "url"], allow_error=True).strip() or url
        run_record = {
            "ts": datetime.now().isoformat(),
            "url": current_url,
            "fields_seen": total_seen,
            "fields_filled": total_filled,
            "unresolved_count": len(unresolved),
            "human_events": len(self._human_events),
            "decisions": len(self._decision_log),
            "visual_artifacts": len(self._visual_artifacts),
        }
        runs = self.memory.setdefault("runs", [])
        runs.insert(0, run_record)
        self.memory["runs"] = runs[:50]
        self._save_memory()

        artifact_paths = self._flush_run_artifacts(
            url=current_url,
            unresolved=unresolved,
            total_seen=total_seen,
            total_filled=total_filled,
        )
        return {
            "engine": "agent-browser",
            "url": current_url,
            "total_fields_seen": total_seen,
            "fields_filled": total_filled,
            "unresolved": unresolved,
            "memory_file": str(self.memory_path),
            "profile_path": str(self.profile_path),
            "session_name": self.session_name,
            "cv_md_path": str(self.cv_md_path),
            "cover_letter_pdf": str(self.cover_letter_pdf),
            "context_path": str(self.context_path),
            "llm_model": self.llm_model,
            "embedding_model": self.embedding_model,
            "visual_artifacts": self._visual_artifacts[-80:],
            **artifact_paths,
        }


def run_agent_browser_live_form_agent(
    url: str,
    cv_md_path: Path,
    cover_letter_pdf: Path = DEFAULT_COVER_LETTER_PDF,
    llm_model: str = DEFAULT_LLM_MODEL,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    follow: bool = True,
    follow_interval: float = 1.5,
    session_name: str = "job_form_assistant",
    profile_path: Optional[Path] = None,
    headed: bool = True,
) -> Dict[str, Any]:
    agent = AgentBrowserLiveFormAgent(
        cv_md_path=cv_md_path,
        cover_letter_pdf=cover_letter_pdf,
        llm_model=llm_model,
        embedding_model=embedding_model,
        session_name=session_name,
        profile_path=profile_path,
        follow_interval=follow_interval,
        headed=headed,
    )
    return agent.run(url=url, follow=follow)


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Live form assistant via agent-browser",
        add_help=False,
    )
    parser.add_argument("url", nargs="?", default="")
    parser.add_argument("-h", "--help", action="store_true")
    args, _unknown = parser.parse_known_args()

    if args.help:
        print("Usage: python -m agents.agent_browser_live_form_agent <job-url>")
        print("If <job-url> is omitted, you will be prompted.")
        print(f"Static CV: {DEFAULT_CV_MD}")
        print(f"Static cover letter PDF: {DEFAULT_COVER_LETTER_PDF}")
        print(f"Static llm model: {DEFAULT_LLM_MODEL}")
        print(f"Static embedding model: {DEFAULT_EMBEDDING_MODEL}")
        print("Optional env: AGENT_BROWSER_CDP or AGENT_BROWSER_AUTO_CONNECT=1")
        return

    url = (args.url or "").strip()
    if not url:
        url = input("Job application URL (paste from your browser tab): ").strip()
    if not url:
        raise SystemExit("URL is required.")

    result = run_agent_browser_live_form_agent(
        url=url,
        cv_md_path=Path(DEFAULT_CV_MD),
        cover_letter_pdf=Path(DEFAULT_COVER_LETTER_PDF),
        llm_model=DEFAULT_LLM_MODEL,
        embedding_model=DEFAULT_EMBEDDING_MODEL,
        follow=True,
        follow_interval=1.5,
        session_name="job_form_assistant",
        profile_path=None,
        headed=True,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
