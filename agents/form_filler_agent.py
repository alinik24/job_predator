"""
Minimal form filler agent.

MVP goals:
  - Fill application fields from CV data.
  - Support CV input from Markdown file.
  - Work either on a URL or an attached existing browser tab (CDP).
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from urllib.request import urlopen

from loguru import logger
from playwright.async_api import ElementHandle, Page, async_playwright

_PROJECT_ENV_LOADED = False


def _load_project_env_once() -> None:
    """Load .env values into process env only when keys are missing."""
    global _PROJECT_ENV_LOADED
    if _PROJECT_ENV_LOADED:
        return
    _PROJECT_ENV_LOADED = True

    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return

    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value and key not in os.environ:
                os.environ[key] = value
    except Exception:
        # Best-effort loader; the app can still run without local env file parsing.
        return


def _bootstrap_browser_use_env() -> None:
    """
    Map project-level LLM_* env vars to names expected by browser-use providers.
    This keeps CLI usage simple (just run fill-form) for this MVP.
    """
    _load_project_env_once()

    llm_api_key = (os.getenv("LLM_API_KEY") or "").strip()
    llm_api_base_url = (os.getenv("LLM_API_BASE_URL") or "").strip()
    llm_model_name = (os.getenv("LLM_MODEL_NAME") or "").strip()

    if llm_api_key:
        os.environ.setdefault("OPENAI_API_KEY", llm_api_key)
        os.environ.setdefault("AZURE_OPENAI_API_KEY", llm_api_key)
        os.environ.setdefault("AZURE_OPENAI_KEY", llm_api_key)

    if llm_api_base_url:
        normalized_base = llm_api_base_url.rstrip("/")
        lower_base = normalized_base.lower()
        if "services.ai.azure.com" in lower_base and "/openai/" not in lower_base:
            normalized_base = f"{normalized_base}/openai/v1"
        os.environ.setdefault("OPENAI_BASE_URL", normalized_base)

        if "azure" in lower_base:
            azure_endpoint = normalized_base
            if azure_endpoint.lower().endswith("/openai/v1"):
                azure_endpoint = azure_endpoint[: -len("/openai/v1")]
            os.environ.setdefault("AZURE_OPENAI_ENDPOINT", azure_endpoint.rstrip("/"))

    if llm_model_name:
        os.environ.setdefault("OPENAI_MODEL", llm_model_name)
        os.environ.setdefault("AZURE_OPENAI_DEPLOYMENT", llm_model_name)


@dataclass
class FormField:
    element: ElementHandle
    field_type: str
    label: str
    name: str
    required: bool
    options: List[str]
    value: Optional[Any] = None


@dataclass
class CVProfileData:
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    summary: Optional[str] = None
    skills: Optional[List[str]] = None
    languages: Optional[List[Dict[str, str]]] = None
    work_experience: Optional[List[Dict[str, Any]]] = None
    education: Optional[List[Dict[str, Any]]] = None
    certifications: Optional[List[str]] = None
    raw_text: Optional[str] = None


class FormFillerAgent:
    """Fill fields on job application pages from structured CV profile data."""

    def __init__(
        self,
        cv_profile: CVProfileData,
        headless: bool = False,
        use_existing_browser: bool = False,
        cdp_url: str = "http://127.0.0.1:9222",
    ):
        self.cv_profile = cv_profile
        self.headless = headless
        self.use_existing_browser = use_existing_browser
        self.cdp_url = self._normalize_cdp_url(cdp_url)
        self.page: Optional[Page] = None
        self.form_data: Dict[str, Any] = {}
        self._last_detected_count: Optional[int] = None
        self._sequence_cursors: Dict[str, int] = {}
        self._field_sequence_assignments: Dict[str, Any] = {}
        self._last_form_signature: Optional[str] = None
        self._memory_path = Path(__file__).resolve().parents[1] / "output" / "form_field_memory.json"
        self._learned_memory: Dict[str, Any] = self._load_learned_memory()
        self._prepare_cv_data()

    def _load_learned_memory(self) -> Dict[str, Any]:
        try:
            if self._memory_path.exists():
                raw = json.loads(self._memory_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    raw.setdefault("version", 1)
                    raw.setdefault("fields", {})
                    if isinstance(raw.get("fields"), dict):
                        return raw
        except Exception:
            pass
        return {"version": 1, "fields": {}}

    def _save_learned_memory(self) -> None:
        try:
            self._memory_path.parent.mkdir(parents=True, exist_ok=True)
            self._memory_path.write_text(
                json.dumps(self._learned_memory, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _current_host(self) -> str:
        try:
            if self.page and self.page.url:
                return (urlparse(self.page.url).netloc or "*").lower()
        except Exception:
            pass
        return "*"

    def _memory_compound_key(self, field_base_key: str, host: Optional[str] = None) -> str:
        field_base_key = (field_base_key or "").strip().lower()
        target_host = (host or self._current_host() or "*").strip().lower()
        return f"{target_host}::{field_base_key}"

    def _memory_candidates(self, field_base_key: str) -> List[str]:
        fields_mem = self._learned_memory.get("fields", {})
        if not isinstance(fields_mem, dict):
            return []

        out: List[str] = []
        seen = set()
        for key in (
            self._memory_compound_key(field_base_key, self._current_host()),
            self._memory_compound_key(field_base_key, "*"),
        ):
            rec = fields_mem.get(key, {})
            accepted = rec.get("accepted", []) if isinstance(rec, dict) else []
            if not isinstance(accepted, list):
                continue
            for item in accepted:
                value = str(item or "").strip()
                if value and value.lower() not in seen:
                    seen.add(value.lower())
                    out.append(value)
        return out[:8]

    def _remember_field_value(self, field_base_key: str, value: Any) -> None:
        text = self._serialize_value(value).strip()
        if not text or len(text) > 400:
            return

        fields_mem = self._learned_memory.setdefault("fields", {})
        if not isinstance(fields_mem, dict):
            return

        host_key = self._memory_compound_key(field_base_key, self._current_host())
        global_key = self._memory_compound_key(field_base_key, "*")

        for key in (host_key, global_key):
            rec = fields_mem.setdefault(key, {})
            if not isinstance(rec, dict):
                fields_mem[key] = {}
                rec = fields_mem[key]

            accepted = rec.setdefault("accepted", [])
            if not isinstance(accepted, list):
                rec["accepted"] = []
                accepted = rec["accepted"]

            # Keep latest accepted value at top; dedupe case-insensitively.
            normalized = text.lower()
            rec["accepted"] = [text] + [v for v in accepted if str(v).strip().lower() != normalized]
            rec["accepted"] = rec["accepted"][:12]
            rec["updated_at"] = datetime.now().isoformat()

    def _next_from_sequence(self, key: str, values: List[str]) -> Optional[str]:
        cleaned = [v.strip() for v in values if str(v).strip()]
        if not cleaned:
            return None
        idx = self._sequence_cursors.get(key, 0)
        if idx >= len(cleaned):
            idx = len(cleaned) - 1
        self._sequence_cursors[key] = idx + 1
        return cleaned[idx]

    def _sequence_value_for_field(
        self,
        field_key: str,
        sequence_key: str,
        values: List[str],
        fallback: Optional[str] = None,
    ) -> Optional[str]:
        assigned = self._field_sequence_assignments.get(field_key)
        if assigned not in (None, ""):
            return str(assigned)

        next_value = self._next_from_sequence(sequence_key, values)
        if next_value in (None, ""):
            next_value = fallback

        if next_value not in (None, ""):
            self._field_sequence_assignments[field_key] = str(next_value)
            return str(next_value)

        return None

    @staticmethod
    def _normalize_cdp_url(cdp_url: str) -> str:
        raw = (cdp_url or "").strip()
        if not raw:
            return "http://127.0.0.1:9222"
        if not raw.startswith(("http://", "https://", "ws://", "wss://")):
            raw = f"http://{raw}"
        return raw.rstrip("/")

    async def _connect_existing_browser_with_retries(self, p: Any) -> Any:
        base = self._normalize_cdp_url(self.cdp_url)
        endpoints: List[str] = [base]
        # Deterministic fallback: same endpoint's browser websocket if available.
        if base.startswith(("http://", "https://")):
            try:
                with urlopen(f"{base}/json/version", timeout=2) as resp:
                    version_data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                ws_browser = str(version_data.get("webSocketDebuggerUrl") or "").strip()
                if ws_browser and ws_browser.lower() != base.lower():
                    endpoints.append(ws_browser)
            except Exception:
                pass

        attempts_per_endpoint = 3
        errors: List[str] = []

        for endpoint in endpoints:
            for attempt in range(1, attempts_per_endpoint + 1):
                try:
                    browser = await p.chromium.connect_over_cdp(endpoint, timeout=10000)
                    logger.info(f"✓ Connected to existing browser via: {endpoint}")
                    return browser
                except Exception as exc:
                    err_msg = str(exc)
                    # Only add unique errors
                    if attempt == attempts_per_endpoint:
                        errors.append(f"{endpoint}: {err_msg}")
                    if attempt < attempts_per_endpoint:
                        await asyncio.sleep(0.5 * attempt)  # Exponential backoff

        detail = "\n".join(errors[-5:]) if errors else "No CDP endpoint attempts were made."
        raise RuntimeError(
            "Could not attach to current browser session via CDP.\n"
            f"Tried managed endpoint(s):\n{detail}\n\n"
            "Make sure managed Chrome is running with remote debugging."
        )

    @staticmethod
    def _normalize_url(url: str) -> str:
        if not url:
            return ""
        parsed = urlparse(url)
        host = parsed.netloc.lower().replace("localhost", "127.0.0.1")
        path = parsed.path.rstrip("/")
        return f"{parsed.scheme}://{host}{path}"

    def _prepare_cv_data(self) -> None:
        cv = self.cv_profile
        full_name = (cv.full_name or "").strip()
        parts = full_name.split()

        self.form_data = {
            "first_name": parts[0] if parts else "",
            "last_name": " ".join(parts[1:]) if len(parts) > 1 else "",
            "full_name": full_name,
            "email": cv.email or "",
            "phone": cv.phone or "",
            "location": cv.location or "",
            "linkedin": cv.linkedin_url or "",
            "github": cv.github_url or "",
            "summary": cv.summary or "",
            "cv_text": cv.raw_text or "",
            "skills": ", ".join(cv.skills or []),
        }

        if cv.work_experience:
            latest = cv.work_experience[0]
            self.form_data["current_company"] = str(latest.get("company", ""))
            self.form_data["current_title"] = str(latest.get("title", ""))
            self.form_data["experience_titles"] = [
                str(item.get("title", "")).strip()
                for item in cv.work_experience
                if str(item.get("title", "")).strip()
            ]
            self.form_data["experience_companies"] = [
                str(item.get("company", "")).strip()
                for item in cv.work_experience
                if str(item.get("company", "")).strip()
            ]
            self.form_data["experience_from_dates"] = [
                str(item.get("from", "")).strip()
                for item in cv.work_experience
                if str(item.get("from", "")).strip()
            ]
            self.form_data["experience_to_dates"] = [
                str(item.get("to", "")).strip()
                for item in cv.work_experience
                if str(item.get("to", "")).strip()
            ]

        if cv.education:
            latest_edu = cv.education[0]
            self.form_data["university"] = str(latest_edu.get("institution", ""))
            self.form_data["degree"] = str(latest_edu.get("degree", ""))
            self.form_data["field_of_study"] = str(latest_edu.get("field_of_study", ""))

        self.form_data["date_candidates"] = self._extract_date_candidates(self.form_data.get("cv_text", ""))

        logger.info(f"Prepared form data for: {self.form_data.get('full_name')}")

    @staticmethod
    def _extract_date_candidates(text: str) -> List[str]:
        if not text:
            return []

        month_map = {
            "january": "01",
            "jan": "01",
            "february": "02",
            "feb": "02",
            "march": "03",
            "mar": "03",
            "april": "04",
            "apr": "04",
            "may": "05",
            "june": "06",
            "jun": "06",
            "july": "07",
            "jul": "07",
            "august": "08",
            "aug": "08",
            "september": "09",
            "sep": "09",
            "sept": "09",
            "october": "10",
            "oct": "10",
            "november": "11",
            "nov": "11",
            "december": "12",
            "dec": "12",
        }
        candidates: List[str] = []

        for m in re.findall(r"\b(20\d{2})-(0[1-9]|1[0-2])\b", text):
            candidates.append(f"{m[0]}-{m[1]}-01")

        for month, year in re.findall(
            r"\b(January|Jan|February|Feb|March|Mar|April|Apr|May|June|Jun|July|Jul|August|Aug|September|Sep|Sept|October|Oct|November|Nov|December|Dec)\s+(20\d{2})\b",
            text,
            flags=re.IGNORECASE,
        ):
            mm = month_map.get(month.lower())
            if mm:
                candidates.append(f"{year}-{mm}-01")

        # Deduplicate preserving order.
        unique: List[str] = []
        seen = set()
        for c in candidates:
            if c not in seen:
                unique.append(c)
                seen.add(c)
        return unique

    async def _get_field_label(self, page: Page, element: ElementHandle) -> str:
        element_id = await element.get_attribute("id")
        if element_id:
            label = await page.query_selector(f"label[for='{element_id}']")
            if label:
                text = (await label.text_content()) or ""
                if text.strip():
                    return text.strip()

        for attr in ("aria-label", "placeholder", "name", "id"):
            value = await element.get_attribute(attr)
            if value and value.strip():
                return value.strip()

        return "unknown"

    async def detect_form_fields(self, page: Page) -> List[FormField]:
        fields: List[FormField] = []

        inputs = await page.query_selector_all("input")
        for inp in inputs:
            field_type = (await inp.get_attribute("type") or "text").lower()
            if field_type in {"hidden", "submit", "button", "image", "reset"}:
                continue

            name = await inp.get_attribute("name") or await inp.get_attribute("id") or ""
            required = (
                await inp.get_attribute("required") is not None
                or (await inp.get_attribute("aria-required") or "").lower() == "true"
            )
            label = await self._get_field_label(page, inp)
            fields.append(FormField(inp, field_type, label, name, required, []))

        textareas = await page.query_selector_all("textarea")
        for ta in textareas:
            name = await ta.get_attribute("name") or await ta.get_attribute("id") or ""
            required = (
                await ta.get_attribute("required") is not None
                or (await ta.get_attribute("aria-required") or "").lower() == "true"
            )
            label = await self._get_field_label(page, ta)
            fields.append(FormField(ta, "textarea", label, name, required, []))

        selects = await page.query_selector_all("select")
        for sel in selects:
            name = await sel.get_attribute("name") or await sel.get_attribute("id") or ""
            required = (
                await sel.get_attribute("required") is not None
                or (await sel.get_attribute("aria-required") or "").lower() == "true"
            )
            label = await self._get_field_label(page, sel)
            option_nodes = await sel.query_selector_all("option")
            options: List[str] = []
            for opt in option_nodes:
                text = (await opt.text_content()) or ""
                if text.strip():
                    options.append(text.strip())
            fields.append(FormField(sel, "select", label, name, required, options))

        return fields

    async def _ensure_dom_watcher(self) -> None:
        if not self.page:
            return
        await self.page.evaluate(
            """
            () => {
              if (window.__jobpredatorDomWatcherInstalled) return;
              window.__jobpredatorDomWatcherInstalled = true;
              window.__jobpredatorDomVersion = 1;

              const bump = () => { window.__jobpredatorDomVersion = (window.__jobpredatorDomVersion || 0) + 1; };
              const isAssistantNode = (node) => {
                if (!node || !node.closest) return false;
                return !!node.closest("#jobpredator-assistant-panel");
              };
              const observer = new MutationObserver((mutations) => {
                for (const m of mutations) {
                  const target = m && m.target;
                  if (isAssistantNode(target)) continue;
                  if (m && m.type === "attributes" && (m.attributeName || "") === "data-jobpredator-locked") {
                    continue;
                  }

                  const added = Array.from((m && m.addedNodes) || []);
                  if (added.length && added.every((n) => isAssistantNode(n))) continue;

                  const removed = Array.from((m && m.removedNodes) || []);
                  if (removed.length && removed.every((n) => isAssistantNode(n))) continue;

                  bump();
                  break;
                }
              });
              observer.observe(document.documentElement || document.body, {
                childList: true,
                subtree: true,
                attributes: true,
                characterData: false
              });

              window.addEventListener("popstate", bump, true);
              window.addEventListener("hashchange", bump, true);
            }
            """
        )

    async def _get_dom_version(self) -> int:
        if not self.page:
            return 0
        try:
            return int(await self.page.evaluate("() => Number(window.__jobpredatorDomVersion || 0)"))
        except Exception:
            return 0

    def _match_field_to_cv_data(self, field: FormField, field_key: str = "") -> Optional[Any]:
        text = f"{field.label} {field.name}".lower()

        if any(k in text for k in ("first name", "firstname", "given name", "vorname")):
            return self.form_data.get("first_name")
        if any(k in text for k in ("last name", "lastname", "surname", "family name", "nachname")):
            return self.form_data.get("last_name")
        if "name" in text and "first" not in text and "last" not in text:
            return self.form_data.get("full_name")

        if any(k in text for k in ("confirm email", "email confirmation")):
            return self.form_data.get("email")
        if any(k in text for k in ("email", "e-mail")):
            return self.form_data.get("email")

        if any(k in text for k in ("phone", "telephone", "mobile", "tel", "handy")):
            return self.form_data.get("phone")

        if any(k in text for k in ("location", "city", "address", "wohnort", "stadt")):
            return self.form_data.get("location")

        if "linkedin" in text:
            return self.form_data.get("linkedin")
        if "github" in text:
            return self.form_data.get("github")
        if any(k in text for k in ("website", "portfolio")):
            return self.form_data.get("linkedin") or self.form_data.get("github")

        if any(k in text for k in ("university", "college", "school")):
            return self.form_data.get("university")
        if any(k in text for k in ("degree", "qualification")):
            return self.form_data.get("degree")
        if any(k in text for k in ("field of study", "major")):
            return self.form_data.get("field_of_study")

        if any(k in text for k in ("current company", "employer", "organization", "company")):
            return self._sequence_value_for_field(
                field_key=field_key or self._field_key(field.label, field.name, field.field_type),
                sequence_key="exp_company",
                values=self.form_data.get("experience_companies", []) or [],
                fallback=self.form_data.get("current_company"),
            )
        if any(k in text for k in ("current title", "job title", "position")) or "title" in text:
            return self._sequence_value_for_field(
                field_key=field_key or self._field_key(field.label, field.name, field.field_type),
                sequence_key="exp_title",
                values=self.form_data.get("experience_titles", []) or [],
                fallback=self.form_data.get("current_title"),
            )

        if any(k in text for k in ("from", "start date", "start")):
            return self._sequence_value_for_field(
                field_key=field_key or self._field_key(field.label, field.name, field.field_type),
                sequence_key="exp_from",
                values=self.form_data.get("experience_from_dates", []) or [],
            )

        if any(k in text for k in ("to", "end date", "end", "until")):
            return self._sequence_value_for_field(
                field_key=field_key or self._field_key(field.label, field.name, field.field_type),
                sequence_key="exp_to",
                values=self.form_data.get("experience_to_dates", []) or [],
            )

        if any(k in text for k in ("skills", "competencies", "fähigkeiten")):
            return self.form_data.get("skills")
        if any(k in text for k in ("summary", "about", "motivation", "cover letter", "why")):
            return self.form_data.get("summary")

        if field.field_type == "checkbox":
            if any(k in text for k in ("privacy", "gdpr", "consent", "terms", "agree")):
                return True
            if any(k in text for k in ("newsletter", "marketing", "promo")):
                return False

        return None

    @staticmethod
    def _find_best_option_match(value: Any, options: List[str]) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip().lower()
        if not text:
            return None
        for opt in options:
            if opt.lower() == text:
                return opt
        for opt in options:
            if text in opt.lower() or opt.lower() in text:
                return opt
        return None

    @staticmethod
    def _serialize_value(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "yes" if value else "no"
        return str(value)

    def _field_candidates(self, field: FormField, suggested: Any, field_base_key: str) -> List[str]:
        text = f"{field.label} {field.name}".lower()
        candidates: List[str] = []

        candidates.extend(self._memory_candidates(field_base_key))

        if suggested not in (None, ""):
            candidates.append(self._serialize_value(suggested))

        if any(k in text for k in ("title", "position", "role")):
            if self.form_data.get("current_title"):
                candidates.append(str(self.form_data["current_title"]))
            candidates.extend(self.form_data.get("experience_titles", [])[:8])

        if any(k in text for k in ("company", "employer", "organization")):
            if self.form_data.get("current_company"):
                candidates.append(str(self.form_data["current_company"]))
            candidates.extend(self.form_data.get("experience_companies", [])[:8])

        if any(k in text for k in ("institution", "university", "school", "college")):
            if self.form_data.get("university"):
                candidates.append(str(self.form_data["university"]))

        if any(k in text for k in ("from", "start", "start date")):
            date_candidates = self.form_data.get("date_candidates", [])
            candidates.extend(self.form_data.get("experience_from_dates", [])[:8])
            candidates.extend(date_candidates[:5] if date_candidates else ["2024-01-01"])
        if any(k in text for k in ("to", "end", "until")):
            date_candidates = self.form_data.get("date_candidates", [])
            candidates.extend(self.form_data.get("experience_to_dates", [])[:8])
            candidates.extend(["Present"] + (date_candidates[:5] if date_candidates else ["2024-12-31"]))

        if field.field_type == "select" and field.options:
            # Add the first few options as copy-ready fallback hints.
            candidates.extend(field.options[:6])

        # Deduplicate while preserving order.
        out: List[str] = []
        seen = set()
        for c in candidates:
            cc = str(c).strip()
            if cc and cc not in seen:
                out.append(cc)
                seen.add(cc)
        return out[:8]

    @staticmethod
    def _field_key(label: str, name: str, field_type: str) -> str:
        return f"{label.strip().lower()}|{name.strip().lower()}|{field_type.strip().lower()}"

    async def _field_runtime_value(self, field: FormField) -> str:
        try:
            if field.field_type == "checkbox":
                checked = await field.element.evaluate("el => !!el.checked")
                return "checked" if checked else "unchecked"

            if field.field_type == "select":
                selected = await field.element.evaluate(
                    "el => el.selectedIndex >= 0 ? ((el.options[el.selectedIndex]?.textContent || '').trim()) : ''"
                )
                return str(selected or "").strip()

            value = await field.element.evaluate(
                """
                el => {
                  if (typeof el.value !== 'undefined' && el.value !== null) {
                    return String(el.value).trim();
                  }
                  return String(el.textContent || '').trim();
                }
                """
            )
            return str(value or "").strip()
        except Exception:
            return ""

    async def _compute_form_signature(self, fields: List[FormField]) -> str:
        parts: List[str] = []
        for field in fields:
            key = self._field_key(field.label, field.name, field.field_type)
            value = await self._field_runtime_value(field)
            parts.append(f"{key}::{value}::{int(field.required)}::{len(field.options)}")
        return "\n".join(parts)

    async def _inject_assistant_overlay(self, suggestions: List[Dict[str, Any]]) -> None:
        """
        Inject/update an in-page assistant panel.
        The panel updates when user focuses/clicks a field and shows copy-ready suggestions.
        """
        if not self.page:
            return

        await self.page.evaluate(
            """
            ({ suggestions }) => {
              const normalize = (v) => (v || "").toString().trim().toLowerCase();
              const payload = Array.isArray(suggestions) ? suggestions : [];
              window.__jobpredatorSuggestions = payload;

              const panelId = "jobpredator-assistant-panel";
              const contentId = "jobpredator-assistant-content";
              const statusId = "jobpredator-assistant-status";
              const applyBtnId = "jobpredator-assistant-apply-btn";
              const copyBtnId = "jobpredator-assistant-copy-btn";

              let panel = document.getElementById(panelId);
              if (!panel) {
                panel = document.createElement("div");
                panel.id = panelId;
                panel.style.position = "fixed";
                panel.style.left = "12px";
                panel.style.top = "12px";
                panel.style.width = "340px";
                panel.style.maxHeight = "42vh";
                panel.style.overflow = "auto";
                panel.style.background = "rgba(17, 24, 39, 0.96)";
                panel.style.color = "#e5e7eb";
                panel.style.border = "1px solid #374151";
                panel.style.borderRadius = "10px";
                panel.style.padding = "10px";
                panel.style.zIndex = "2147483647";
                panel.style.fontSize = "12px";
                panel.style.fontFamily = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";

                const title = document.createElement("div");
                title.textContent = "JobPredator Assistant";
                title.style.fontWeight = "700";
                title.style.marginBottom = "6px";
                panel.appendChild(title);

                const hint = document.createElement("div");
                hint.textContent = "Focus a field, then click Apply or Copy";
                hint.style.opacity = "0.85";
                hint.style.marginBottom = "8px";
                panel.appendChild(hint);

                const status = document.createElement("div");
                status.id = statusId;
                status.style.minHeight = "16px";
                status.style.opacity = "0.9";
                status.style.marginBottom = "8px";
                status.textContent = "";
                panel.appendChild(status);

                const content = document.createElement("div");
                content.id = contentId;
                content.textContent = "Waiting for field focus...";
                panel.appendChild(content);

                const applyBtn = document.createElement("button");
                applyBtn.id = applyBtnId;
                applyBtn.type = "button";
                applyBtn.textContent = "Apply to focused field";
                applyBtn.style.marginTop = "10px";
                applyBtn.style.width = "100%";
                applyBtn.style.padding = "8px";
                applyBtn.style.background = "#111827";
                applyBtn.style.color = "#e5e7eb";
                applyBtn.style.border = "1px solid #4b5563";
                applyBtn.style.borderRadius = "8px";
                applyBtn.style.cursor = "pointer";
                panel.appendChild(applyBtn);

                const copyBtn = document.createElement("button");
                copyBtn.id = copyBtnId;
                copyBtn.type = "button";
                copyBtn.textContent = "Copy suggestion";
                copyBtn.style.marginTop = "8px";
                copyBtn.style.width = "100%";
                copyBtn.style.padding = "8px";
                copyBtn.style.background = "#0f172a";
                copyBtn.style.color = "#bfdbfe";
                copyBtn.style.border = "1px solid #334155";
                copyBtn.style.borderRadius = "8px";
                copyBtn.style.cursor = "pointer";
                panel.appendChild(copyBtn);

                document.documentElement.appendChild(panel);
              }

              const setContent = (html) => {
                const node = document.getElementById(contentId);
                if (node) node.innerHTML = html;
              };

              const setStatus = (text, ok = false) => {
                const node = document.getElementById(statusId);
                if (!node) return;
                node.textContent = text || "";
                node.style.color = ok ? "#34d399" : "#fbbf24";
              };

              const positionPanelNearField = (el) => {
                const panel = document.getElementById(panelId);
                if (!panel || !el || !el.getBoundingClientRect) return;
                const rect = el.getBoundingClientRect();
                const panelWidth = 340;
                const gap = 12;
                let left = rect.right + gap;
                if (left + panelWidth > window.innerWidth - 10) {
                  left = rect.left - panelWidth - gap;
                }
                if (left < 8) left = 8;

                let top = rect.top;
                const maxTop = window.innerHeight - panel.offsetHeight - 8;
                if (top > maxTop) top = Math.max(8, maxTop);
                if (top < 8) top = 8;

                panel.style.left = `${Math.round(left)}px`;
                panel.style.top = `${Math.round(top)}px`;
              };

              const getLabel = (el) => {
                const aria = el.getAttribute("aria-label");
                if (aria) return aria.trim();
                const ph = el.getAttribute("placeholder");
                if (ph) return ph.trim();
                const id = el.getAttribute("id");
                if (id) {
                  const label = document.querySelector(`label[for="${CSS.escape(id)}"]`);
                  if (label && label.textContent) return label.textContent.trim();
                }
                if (el.labels && el.labels.length && el.labels[0].textContent) {
                  return el.labels[0].textContent.trim();
                }
                return el.getAttribute("name") || el.getAttribute("id") || el.tagName.toLowerCase();
              };

              const matchSuggestion = (el) => {
                const name = normalize(el.getAttribute("name") || el.getAttribute("id") || "");
                const label = normalize(getLabel(el));
                let best = null;
                let bestScore = -1;
                for (const rec of payload) {
                  const recName = normalize(rec.name || "");
                  const recLabel = normalize(rec.label || "");
                  let score = 0;
                  if (name && recName && name === recName) score += 8;
                  if (label && recLabel && label === recLabel) score += 8;
                  if (name && recName && (name.includes(recName) || recName.includes(name))) score += 3;
                  if (label && recLabel && (label.includes(recLabel) || recLabel.includes(label))) score += 3;
                  if (score > bestScore) {
                    bestScore = score;
                    best = rec;
                  }
                }
                return bestScore >= 2 ? best : null;
              };

              const renderRec = (rec) => {
                if (!rec) {
                  setContent("<div>No matching suggestion found for this field yet.</div>");
                  setStatus("No suggestion for focused field.", false);
                  return;
                }
                const candidates = Array.isArray(rec.candidate_values) ? rec.candidate_values : [];
                const options = Array.isArray(rec.options) ? rec.options : [];
                let html = "";
                html += `<div><b>Field:</b> ${(rec.label || rec.name || "").toString()}</div>`;
                html += `<div><b>Type:</b> ${(rec.type || "").toString()}${rec.required ? " | required" : ""}</div>`;
                if (rec.suggested) html += `<div><b>Suggestion:</b> ${String(rec.suggested)}</div>`;
                if (candidates.length) {
                  html += "<div style='margin-top:6px'><b>Copy-paste options:</b></div>";
                  html += "<ol style='margin:4px 0 0 18px'>";
                  for (const c of candidates.slice(0, 8)) html += `<li>${String(c)}</li>`;
                  html += "</ol>";
                }
                if (options.length) {
                  html += "<div style='margin-top:6px'><b>Dropdown options:</b></div>";
                  html += "<ol style='margin:4px 0 0 18px'>";
                  for (const o of options.slice(0, 8)) html += `<li>${String(o)}</li>`;
                  html += "</ol>";
                }
                setContent(html);
              };

              const getCandidatePool = (rec) => {
                if (!rec) return [];
                const values = [];
                const pushValue = (v) => {
                  const s = (v || "").toString().trim();
                  if (s) values.push(s);
                };
                pushValue(rec.suggested);
                const candidates = Array.isArray(rec.candidate_values) ? rec.candidate_values : [];
                for (const c of candidates) pushValue(c);
                const options = Array.isArray(rec.options) ? rec.options : [];
                for (const o of options) pushValue(o);
                const dedup = [];
                const seen = new Set();
                for (const v of values) {
                  const key = v.toLowerCase();
                  if (!seen.has(key)) {
                    seen.add(key);
                    dedup.push(v);
                  }
                }
                return dedup;
              };

              const getMemKey = (rec) => {
                if (!rec) return "";
                return `${(rec.label || "").toString().toLowerCase()}|${(rec.name || "").toString().toLowerCase()}|${(rec.type || "").toString().toLowerCase()}`;
              };

              const ensureMem = (rec) => {
                if (!window.__jobpredatorMemory) window.__jobpredatorMemory = {};
                const key = getMemKey(rec);
                if (!key) return null;
                if (!window.__jobpredatorMemory[key]) {
                  window.__jobpredatorMemory[key] = { cursor: 0, rejected: [], lastApplied: "" };
                }
                return window.__jobpredatorMemory[key];
              };

              const pickValue = (rec) => {
                const pool = getCandidatePool(rec);
                if (!pool.length) return "";
                const mem = ensureMem(rec);
                if (!mem) return pool[0];

                const rejected = new Set((mem.rejected || []).map((v) => (v || "").toString().toLowerCase()));
                const start = Math.max(0, Number(mem.cursor || 0)) % pool.length;
                for (let i = 0; i < pool.length; i++) {
                  const idx = (start + i) % pool.length;
                  const val = pool[idx];
                  if (!rejected.has(val.toLowerCase())) {
                    mem.cursor = (idx + 1) % pool.length;
                    return val;
                  }
                }
                mem.cursor = (start + 1) % pool.length;
                return pool[start];
              };

              const dispatchInputEvents = (el) => {
                el.dispatchEvent(new Event("input", { bubbles: true }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
              };

              const applySuggestionToElement = (el, rec) => {
                if (!el || !rec) return "";
                const value = pickValue(rec);
                if (!value) return "";

                const tag = (el.tagName || "").toLowerCase();
                const type = (el.getAttribute("type") || "").toLowerCase();

                if (tag === "select") {
                  const target = value.toLowerCase();
                  let matched = false;
                  for (const opt of Array.from(el.options || [])) {
                    const txt = (opt.textContent || "").trim().toLowerCase();
                    if (txt === target || txt.includes(target) || target.includes(txt)) {
                      el.value = opt.value;
                      matched = true;
                      break;
                    }
                  }
                  if (!matched) return "";
                  dispatchInputEvents(el);
                  return value;
                }

                if (type === "checkbox") {
                  const wantChecked = ["yes", "true", "1", "on"].includes(value.toLowerCase());
                  if (el.checked !== wantChecked) {
                    el.click();
                  } else {
                    dispatchInputEvents(el);
                  }
                  return value;
                }

                if (el.isContentEditable) {
                  el.focus();
                  el.textContent = value;
                  dispatchInputEvents(el);
                  return value;
                }

                if (typeof el.value !== "undefined") {
                  el.focus();
                  el.value = value;
                  dispatchInputEvents(el);
                  return value;
                }

                return "";
              };

              const copyCurrentSuggestion = async () => {
                const rec = window.__jobpredatorActiveRec;
                if (!rec) {
                  setStatus("No suggestion to copy.", false);
                  return;
                }
                const value = ((rec.suggested || "").toString().trim()) || ((Array.isArray(rec.candidate_values) && rec.candidate_values[0]) ? String(rec.candidate_values[0]).trim() : "");
                if (!value) {
                  setStatus("No suggestion to copy.", false);
                  return;
                }
                try {
                  if (navigator.clipboard && navigator.clipboard.writeText) {
                    await navigator.clipboard.writeText(value);
                  } else {
                    const ta = document.createElement("textarea");
                    ta.value = value;
                    ta.style.position = "fixed";
                    ta.style.left = "-9999px";
                    document.body.appendChild(ta);
                    ta.select();
                    document.execCommand("copy");
                    ta.remove();
                  }
                  setStatus("Suggestion copied.", true);
                } catch (e) {
                  setStatus("Copy blocked by browser permissions.", false);
                }
              };

              const applyCurrentSuggestion = () => {
                const el = window.__jobpredatorActiveField;
                const rec = window.__jobpredatorActiveRec;
                if (!el) {
                  setStatus("Focus a field first.", false);
                  return;
                }
                if (!rec) {
                  setStatus("No suggestion available for focused field.", false);
                  return;
                }
                const appliedValue = applySuggestionToElement(el, rec);
                if (appliedValue) {
                  const mem = ensureMem(rec);
                  if (mem) mem.lastApplied = appliedValue;
                  setStatus("Applied suggestion to focused field.", true);
                } else {
                  setStatus("Could not auto-apply. Use copy-paste options.", false);
                }
              };

              const lockIfUserEdited = (event, el) => {
                if (!event || !el || !el.dataset) return;
                if (!event.isTrusted) return;
                el.dataset.jobpredatorLocked = "1";
              };

              if (!window.__jobpredatorFocusListenerInstalled) {
                window.__jobpredatorFocusListenerInstalled = true;
                document.addEventListener(
                  "focusin",
                  (event) => {
                    const target = event.target;
                    if (!target || !target.matches) return;
                    const el = target.closest("input, textarea, select, [contenteditable='true']");
                    if (!el) return;
                    const rec = matchSuggestion(el);
                    window.__jobpredatorActiveField = el;
                    window.__jobpredatorActiveRec = rec;
                    positionPanelNearField(el);
                    renderRec(rec);
                  },
                  true
                );

                document.addEventListener(
                  "input",
                  (event) => {
                    const target = event.target;
                    if (!target || !target.matches) return;
                    const el = target.closest("input, textarea, select, [contenteditable='true']");
                    if (!el) return;
                    lockIfUserEdited(event, el);
                  },
                  true
                );

                document.addEventListener(
                  "change",
                  (event) => {
                    const target = event.target;
                    if (!target || !target.matches) return;
                    const el = target.closest("input, textarea, select, [contenteditable='true']");
                    if (!el) return;
                    lockIfUserEdited(event, el);
                    const rec = matchSuggestion(el);
                    if (!rec) return;
                    const mem = ensureMem(rec);
                    if (!mem) return;
                    const current = (
                      el.tagName && el.tagName.toLowerCase() === "select"
                        ? ((el.options && el.selectedIndex >= 0 && el.options[el.selectedIndex]) ? el.options[el.selectedIndex].textContent : el.value)
                        : (typeof el.value !== "undefined" ? el.value : el.textContent)
                    );
                    const cur = (current || "").toString().trim();
                    const lastApplied = (mem.lastApplied || "").toString().trim();
                    if (cur && lastApplied && cur.toLowerCase() !== lastApplied.toLowerCase()) {
                      if (!Array.isArray(mem.rejected)) mem.rejected = [];
                      if (!mem.rejected.some((v) => (v || "").toString().toLowerCase() === lastApplied.toLowerCase())) {
                        mem.rejected.push(lastApplied);
                      }
                    }
                  },
                  true
                );
              }

              const applyBtn = document.getElementById(applyBtnId);
              if (applyBtn && !window.__jobpredatorApplyListenerInstalled) {
                window.__jobpredatorApplyListenerInstalled = true;
                applyBtn.addEventListener("click", applyCurrentSuggestion);
              }

              const copyBtn = document.getElementById(copyBtnId);
              if (copyBtn && !window.__jobpredatorCopyListenerInstalled) {
                window.__jobpredatorCopyListenerInstalled = true;
                copyBtn.addEventListener("click", () => { void copyCurrentSuggestion(); });
              }

              if (!window.__jobpredatorPanelRepositionInstalled) {
                window.__jobpredatorPanelRepositionInstalled = true;
                window.addEventListener("scroll", () => {
                  const el = window.__jobpredatorActiveField;
                  if (el) positionPanelNearField(el);
                }, true);
                window.addEventListener("resize", () => {
                  const el = window.__jobpredatorActiveField;
                  if (el) positionPanelNearField(el);
                });
              }
            }
            """,
            {"suggestions": suggestions},
        )

    async def _scan_and_fill_once(
        self,
        aggregate_filled: Dict[str, Dict[str, Any]],
        aggregate_suggestions: Dict[str, Dict[str, Any]],
        aggregate_unresolved_required: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not self.page:
            return {"total_fields": 0}

        fields = await self.detect_form_fields(self.page)
        pre_signature = await self._compute_form_signature(fields)
        if pre_signature == self._last_form_signature and aggregate_suggestions:
            await self._inject_assistant_overlay(list(aggregate_suggestions.values()))
            return {"total_fields": len(fields)}

        if self._last_detected_count != len(fields):
            logger.info(f"Detected {len(fields)} form fields")
            self._last_detected_count = len(fields)

        occurrence_counter: Dict[str, int] = {}
        for field in fields:
            base_key = self._field_key(field.label, field.name, field.field_type)
            occurrence_counter[base_key] = occurrence_counter.get(base_key, 0) + 1
            occurrence = occurrence_counter[base_key]
            key = f"{base_key}#{occurrence}"

            suggested = self._match_field_to_cv_data(field, key)
            await self.fill_field(field, suggested)
            candidate_values = self._field_candidates(field, suggested, base_key)

            filled = field.value is not None and field.value != ""

            rec = {
                "label": field.label,
                "name": field.name,
                "type": field.field_type,
                "required": field.required,
                "suggested": self._serialize_value(suggested),
                "candidate_values": candidate_values,
                "options": field.options[:10],
                "filled_value": self._serialize_value(field.value),
                "status": "filled" if filled else "needs_review",
            }
            aggregate_suggestions[key] = rec

            if filled:
                aggregate_filled[key] = {
                    "label": field.label,
                    "type": field.field_type,
                    "value": field.value,
                    "required": field.required,
                }
                self._remember_field_value(base_key, field.value)
                aggregate_unresolved_required.pop(key, None)
            elif field.required:
                aggregate_unresolved_required[key] = {
                    "label": field.label,
                    "name": field.name,
                    "type": field.field_type,
                    "suggested": self._serialize_value(suggested),
                    "candidate_values": candidate_values,
                    "options": field.options[:10],
                }

        await self._inject_assistant_overlay(list(aggregate_suggestions.values()))
        self._last_form_signature = await self._compute_form_signature(fields)
        self._save_learned_memory()
        return {"total_fields": len(fields)}

    async def fill_field(self, field: FormField, suggested: Any) -> bool:
        if field.field_type in {"text", "email", "tel", "url", "search", "number", "date", "textarea"}:
            existing_value = await field.element.evaluate(
                "el => (typeof el.value !== 'undefined' ? (el.value ?? '') : (el.textContent ?? '')).toString().trim()"
            )
            if existing_value:
                field.value = existing_value
                return False

        if field.field_type == "select":
            current_selected = await field.element.evaluate(
                "el => el.selectedIndex >= 0 ? (el.options[el.selectedIndex]?.textContent || '').trim() : ''"
            )
            if current_selected and not re.match(r"^(select|choose|please select|--)$", current_selected.lower()):
                field.value = current_selected
                return False

        if field.field_type == "checkbox":
            checked = await field.element.evaluate("el => !!el.checked")
            if checked:
                field.value = True

        if suggested is None or suggested == "":
            return False

        is_disabled = await field.element.evaluate("el => !!el.disabled")
        is_readonly = await field.element.evaluate(
            "el => !!(el.readOnly || el.getAttribute('readonly') !== null || el.getAttribute('aria-readonly') === 'true')"
        )
        is_locked = await field.element.evaluate("el => (el.dataset && el.dataset.jobpredatorLocked === '1')")
        if is_disabled or is_readonly or is_locked:
            return False

        try:
            if field.field_type in {"text", "email", "tel", "url", "search", "number", "date"}:
                await field.element.fill(str(suggested))
                field.value = suggested
                await asyncio.sleep(0.2)
                return True
            elif field.field_type == "textarea":
                await field.element.fill(str(suggested))
                field.value = suggested
                await asyncio.sleep(0.2)
                return True
            elif field.field_type == "select":
                match = self._find_best_option_match(suggested, field.options)
                if match:
                    await field.element.select_option(label=match)
                    field.value = match
                    await asyncio.sleep(0.2)
                    return True
            elif field.field_type == "checkbox":
                locked_checkbox = await field.element.evaluate("el => (el.dataset && el.dataset.jobpredatorLocked === '1')")
                if locked_checkbox:
                    return False
                desired = bool(suggested)
                checked = await field.element.evaluate("el => !!el.checked")
                if checked != desired:
                    await field.element.click()
                field.value = desired
                await asyncio.sleep(0.2)
                return checked != desired
        except Exception as exc:
            logger.warning(f"Could not fill field '{field.label}': {exc}")
            return False

        return False

    async def _open_target_page(self, p: Any, url: Optional[str], tab_url: Optional[str]) -> Any:
        if self.use_existing_browser:
            browser = await self._connect_existing_browser_with_retries(p)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            pages = context.pages

            chosen: Optional[Page] = None
            target = self._normalize_url(tab_url or url or "")
            if target:
                for pg in pages:
                    if self._normalize_url(pg.url) == target:
                        chosen = pg
                        break
            if chosen is None and pages:
                chosen = pages[0]
            if chosen is None:
                chosen = await context.new_page()

            self.page = chosen
            try:
                await self.page.bring_to_front()
            except Exception:
                pass

            if url and self._normalize_url(self.page.url) != self._normalize_url(url):
                await self.page.goto(url, wait_until="networkidle", timeout=60000)
            return browser

        browser = await p.chromium.launch(headless=self.headless)
        context = await browser.new_context()
        self.page = await context.new_page()
        if not url:
            raise ValueError("URL is required when not using existing browser.")
        await self.page.goto(url, wait_until="networkidle", timeout=60000)
        return browser

    async def fill_form(
        self,
        url: Optional[str],
        submit: bool = False,
        tab_url: Optional[str] = None,
        follow: bool = True,
        follow_interval: float = 1.5,
        follow_seconds: int = 0,
    ) -> Dict[str, Any]:
        if not url and not self.use_existing_browser:
            raise ValueError("Provide a job URL or use existing browser mode.")

        async with async_playwright() as p:
            browser = await self._open_target_page(p, url, tab_url)
            await self.page.wait_for_timeout(1200)
            await self._ensure_dom_watcher()

            aggregate_filled: Dict[str, Dict[str, Any]] = {}
            aggregate_suggestions: Dict[str, Dict[str, Any]] = {}
            aggregate_unresolved_required: Dict[str, Dict[str, Any]] = {}

            scan_result = await self._scan_and_fill_once(
                aggregate_filled,
                aggregate_suggestions,
                aggregate_unresolved_required,
            )
            last_total_fields = int(scan_result.get("total_fields", 0))

            if follow:
                logger.info(
                    f"Follower mode active (interval={follow_interval}s, seconds={follow_seconds or 'until-stopped'})"
                )
                start = monotonic()
                last_dom_version = await self._get_dom_version()
                while True:
                    if follow_seconds > 0 and (monotonic() - start) >= follow_seconds:
                        break
                    await self.page.wait_for_timeout(int(max(0.5, follow_interval) * 1000))
                    dom_version = await self._get_dom_version()
                    if dom_version == last_dom_version:
                        continue
                    last_dom_version = dom_version
                    scan_result = await self._scan_and_fill_once(
                        aggregate_filled,
                        aggregate_suggestions,
                        aggregate_unresolved_required,
                    )
                    last_total_fields = max(last_total_fields, int(scan_result.get("total_fields", 0)))

            screenshot_path = Path(f"output/form_screenshots/{datetime.now():%Y%m%d_%H%M%S}.png")
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            await self.page.screenshot(path=str(screenshot_path), full_page=True)

            submitted = False
            if submit:
                submit_button = await self.page.query_selector(
                    "button[type='submit'], input[type='submit']"
                )
                if submit_button:
                    await submit_button.click()
                    await self.page.wait_for_timeout(2000)
                    submitted = True

            result = {
                "url": self.page.url or (url or ""),
                "filled_at": datetime.now().isoformat(),
                "fields_filled": len(aggregate_filled),
                "total_fields": last_total_fields,
                "filled_fields": list(aggregate_filled.values()),
                "field_suggestions": list(aggregate_suggestions.values()),
                "unfilled_required_fields": list(aggregate_unresolved_required.values()),
                "screenshot": str(screenshot_path),
                "submitted": submitted,
            }

            if not self.use_existing_browser:
                await browser.close()

            self._save_learned_memory()
            return result


def list_cdp_tabs(cdp_url: str) -> List[Dict[str, str]]:
    endpoint = f"{FormFillerAgent._normalize_cdp_url(cdp_url)}/json/list"
    with urlopen(endpoint, timeout=5) as resp:
        payload = resp.read().decode("utf-8", errors="ignore")
    data = json.loads(payload)
    tabs: List[Dict[str, str]] = []
    for item in data if isinstance(data, list) else []:
        tabs.append(
            {
                "title": str(item.get("title", "")).strip(),
                "url": str(item.get("url", "")).strip(),
                "type": str(item.get("type", "")).strip(),
            }
        )
    return tabs


def load_cv_from_markdown(cv_md_path: Path) -> CVProfileData:
    text = cv_md_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    def clean_md_value(value: str) -> str:
        out = value.strip()
        out = out.replace("**", "").replace("__", "").strip()
        # Convert markdown link [label](url) -> url
        out = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\2", out)
        return out

    def find_line(prefixes: List[str]) -> str:
        for line in lines:
            lower = line.lower().strip()
            for prefix in prefixes:
                if lower.startswith(prefix):
                    return clean_md_value(line.split(":", 1)[1].strip()) if ":" in line else ""
        return ""

    full_name = find_line(["name:", "full name:", "full_name:"])
    email = find_line(["email:", "e-mail:", "email_address:"])
    phone = find_line(["phone:", "mobile:", "telephone:", "phone_number:"])
    location = find_line(["location:", "city:", "address:"])
    current_title = find_line(["current_title:", "title:", "current title:"])
    current_employer = find_line(["current_employer:", "current company:", "employer:", "company:"])

    if not current_title:
        in_experience = False
        for idx, line in enumerate(lines):
            stripped = line.strip()
            lower = stripped.lower()
            if lower.startswith("#") and "experience" in lower:
                in_experience = True
                continue
            if in_experience and re.match(r"^##\s+.+", stripped):
                current_title = re.sub(r"^##\s+", "", stripped).strip()
                # Try to find organization/company in the nearby lines.
                window = lines[idx + 1 : idx + 10]
                for w in window:
                    wl = w.strip()
                    wll = wl.lower()
                    if wll.startswith("**organization:**") or wll.startswith("**company:**") or wll.startswith("**employer:**"):
                        current_employer = wl.split(":", 1)[1].strip() if ":" in wl else current_employer
                        current_employer = clean_md_value(current_employer or "")
                        break
                break

    linkedin = ""
    github = ""
    url_candidates: List[str] = []
    for match in re.findall(r"\[[^\]]+\]\((https?://[^)\s]+)\)", text):
        url_candidates.append(match.strip())
    text_without_md_links = re.sub(r"\[[^\]]+\]\((https?://[^)\s]+)\)", " ", text)
    for match in re.findall(r"https?://[^\s)\]]+", text_without_md_links):
        url_candidates.append(match.strip(").,"))
    for url in url_candidates:
        low = url.lower()
        if "linkedin.com" in low and not linkedin:
            linkedin = url
        if "github.com" in low and not github:
            github = url

    if not full_name:
        first_header = next((ln for ln in lines if ln.strip().startswith("#")), "")
        full_name = first_header.lstrip("# ").strip()

    skills: List[str] = []
    in_skills = False
    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("#") and "skill" in lower:
            in_skills = True
            continue
        if in_skills and re.match(r"^##(?!#)", lower) and "skill" not in lower:
            break
        if in_skills and stripped.startswith(("-", "*")):
            item = stripped[1:].strip()
            # Remove basic markdown markers.
            item = item.replace("**", "").strip()
            if ":" in item:
                _, values = item.split(":", 1)
                for part in values.split(","):
                    skill = part.strip()
                    if skill:
                        skills.append(skill)
            elif item:
                skills.append(item)

    summary = ""
    in_summary = False
    summary_lines: List[str] = []
    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("#") and any(k in lower for k in ("summary", "profile", "about")):
            in_summary = True
            continue
        if lower.startswith("#") and in_summary:
            break
        if in_summary and stripped:
            summary_lines.append(stripped)
    if summary_lines:
        summary = " ".join(summary_lines)

    if not email:
        m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
        email = m.group(0) if m else ""

    if not phone:
        m = re.search(r"(\+?\d[\d\-\s()]{7,}\d)", text)
        phone = m.group(0).strip() if m else ""

    return CVProfileData(
        full_name=full_name or None,
        email=email or None,
        phone=phone or None,
        location=location or None,
        linkedin_url=linkedin or None,
        github_url=github or None,
        summary=summary or None,
        skills=skills,
        languages=[],
        work_experience=(
            [{"title": current_title, "company": current_employer}]
            if (current_title or current_employer)
            else []
        ),
        education=[],
        certifications=[],
        raw_text=text,
    )


def _normalize_engine(engine: str) -> str:
    value = (engine or "playwright").strip().lower()
    aliases = {
        "playwright": "playwright",
        "pw": "playwright",
        "browser-use": "browser-use",
        "browser_use": "browser-use",
        "browseruse": "browser-use",
        "bu": "browser-use",
    }
    if value not in aliases:
        raise ValueError("Unsupported engine. Use 'playwright' or 'browser-use'.")
    return aliases[value]


def _cdp_is_reachable(cdp_url: str) -> bool:
    endpoint = f"{FormFillerAgent._normalize_cdp_url(cdp_url)}/json/version"
    try:
        with urlopen(endpoint, timeout=2):
            return True
    except Exception:
        return False


def _instantiate_browser_use_llm(
    llm_provider: str = "auto",
    llm_model: Optional[str] = None,
):
    _bootstrap_browser_use_env()

    try:
        import browser_use as bu  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError(
            "browser-use is not installed. Install with: uv pip install browser-use && uvx browser-use install"
        ) from exc

    provider = (llm_provider or "auto").strip().lower()
    openai_base_url = (os.getenv("OPENAI_BASE_URL") or "").strip().lower()
    is_azure_openai_style = "azure" in openai_base_url or "services.ai.azure.com" in openai_base_url

    candidates = {
        "azure": ("ChatAzureOpenAI", "AZURE_OPENAI_API_KEY", None, "AZURE_OPENAI_DEPLOYMENT"),
        "browser-use": ("ChatBrowserUse", "BROWSER_USE_API_KEY", None, "BROWSER_USE_MODEL"),
        "openai": (
            "ChatOpenAI",
            "OPENAI_API_KEY",
            (None if is_azure_openai_style else "gpt-4.1-mini"),
            ("OPENAI_MODEL" if not is_azure_openai_style else "AZURE_OPENAI_DEPLOYMENT"),
        ),
        "google": ("ChatGoogle", "GOOGLE_API_KEY", "gemini-flash-latest", "GOOGLE_MODEL"),
        "anthropic": ("ChatAnthropic", "ANTHROPIC_API_KEY", "claude-sonnet-4-6", "ANTHROPIC_MODEL"),
    }

    if provider != "auto" and provider not in candidates:
        raise ValueError(
            "Unsupported browser-use llm provider. Use: auto, azure, browser-use, openai, google, anthropic"
        )

    if provider == "auto":
        # Prefer Azure class when Azure-style endpoint/env is present.
        auto_order = ["azure", "browser-use", "openai", "google", "anthropic"]
        ordered = [(name, candidates[name]) for name in auto_order]
    else:
        ordered = [(provider, candidates[provider])]

    for provider_name, (class_name, env_key, default_model, model_env_key) in ordered:
        llm_cls = getattr(bu, class_name, None)
        if llm_cls is None:
            continue
        if provider == "auto" and not os.getenv(env_key):
            continue

        model_value = (
            llm_model
            or os.getenv(model_env_key or "")
            or os.getenv("LLM_MODEL_NAME")
            or default_model
        )
        if provider_name == "openai" and is_azure_openai_style and not model_value:
            raise RuntimeError(
                "Detected Azure OpenAI-style OPENAI_BASE_URL, but no deployment/model is set. "
                "Provide --browser-use-model <azure-deployment-name> or set AZURE_OPENAI_DEPLOYMENT."
            )

        constructor_kwargs: Dict[str, Any] = {}
        try:
            sig = inspect.signature(llm_cls)
            params = sig.parameters
            if model_value:
                if "model" in params:
                    constructor_kwargs["model"] = model_value
                elif "model_name" in params:
                    constructor_kwargs["model_name"] = model_value

            # Prevent provider-incompatible `reasoning_effort` injection for gpt-5-like models
            # on OpenAI-compatible endpoints that do not accept this argument.
            if "reasoning_models" in params:
                constructor_kwargs["reasoning_models"] = []
            if "reasoning_effort" in params:
                constructor_kwargs["reasoning_effort"] = "low"
        except Exception:
            constructor_kwargs = {"model": model_value} if model_value else {}

        if constructor_kwargs:
            try:
                return llm_cls(**constructor_kwargs)
            except Exception:
                pass

        try:
            return llm_cls()
        except Exception:
            # Last attempt: pass model even if signature inspection failed
            if model_value:
                try:
                    return llm_cls(model=model_value, reasoning_models=[])
                except Exception:
                    pass
            if provider != "auto":
                raise

    raise RuntimeError(
        "Could not initialize a browser-use LLM. "
        "Set one of AZURE_OPENAI_API_KEY / BROWSER_USE_API_KEY / OPENAI_API_KEY / GOOGLE_API_KEY / ANTHROPIC_API_KEY "
        "or pass --browser-use-llm-provider explicitly."
    )


def _build_browser_use_task(
    target_url: str,
    form_data: Dict[str, Any],
    submit: bool,
) -> str:
    profile_json = json.dumps(form_data, ensure_ascii=False, indent=2)
    submit_instruction = (
        "Submit only after required fields are completed and then confirm success."
        if submit
        else "Do NOT submit. Stop after filling as much as possible."
    )
    return (
        f"You are filling a job application form at {target_url}.\n"
        "Use this profile data as source of truth:\n"
        f"{profile_json}\n\n"
        "Rules:\n"
        "1) Open the target URL and fill fields with best matches from profile data.\n"
        "2) Respect existing values: if a field already has a meaningful non-empty value, treat it as done.\n"
        "3) For dropdowns/radios, choose the closest valid option shown by the site.\n"
        "4) If dynamic sections appear (drawers, popups, new steps), continue filling them.\n"
        "5) If uncertain, keep the field unchanged and mention it in final_result with suggested value.\n"
        "6) Handle interruptions/popups and continue.\n"
        f"7) {submit_instruction}\n"
        "8) In final_result, include a concise summary and a bullet list of unresolved fields.\n"
    )


def _history_call(history: Any, method_name: str, default: Any) -> Any:
    method = getattr(history, method_name, None)
    if callable(method):
        try:
            return method()
        except Exception:
            return default
    return default


async def _fill_application_form_browser_use(
    *,
    url: str,
    form_data: Dict[str, Any],
    submit: bool,
    headless: bool,
    use_existing_browser: bool,
    cdp_url: str,
    browser_use_llm_provider: str,
    browser_use_model: Optional[str],
    browser_use_max_steps: int,
    chrome_profile: Optional[str],
) -> Dict[str, Any]:
    try:
        import browser_use as bu  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError(
            "browser-use is not installed. Install with: uv pip install browser-use && uvx browser-use install"
        ) from exc

    Browser = getattr(bu, "Browser", None)
    Agent = getattr(bu, "Agent", None)
    if Browser is None or Agent is None:
        raise RuntimeError("browser-use installation is missing Browser/Agent exports.")

    llm = _instantiate_browser_use_llm(
        llm_provider=browser_use_llm_provider,
        llm_model=browser_use_model,
    )

    browser = None
    normalized_cdp = FormFillerAgent._normalize_cdp_url(cdp_url)
    if use_existing_browser and _cdp_is_reachable(normalized_cdp):
        browser = Browser(cdp_url=normalized_cdp)
    elif use_existing_browser and hasattr(Browser, "from_system_chrome"):
        # Fallback path if CDP endpoint is not open.
        if chrome_profile:
            browser = Browser.from_system_chrome(profile_directory=chrome_profile)
        else:
            browser = Browser.from_system_chrome()
        logger.warning("CDP endpoint not reachable. Falling back to Browser.from_system_chrome().")
    elif use_existing_browser:
        raise RuntimeError(
            "Could not attach to existing browser. Either open CDP endpoint "
            "(e.g., --cdp-url http://127.0.0.1:9222) or provide a browser-use compatible profile."
        )
    else:
        kwargs: Dict[str, Any] = {"headless": headless}
        if chrome_profile:
            kwargs["profile_directory"] = chrome_profile
        browser = Browser(**kwargs)

    task = _build_browser_use_task(url, form_data=form_data, submit=submit)
    agent = Agent(
        task=task,
        llm=llm,
        browser=browser,
    )

    history = await agent.run(max_steps=max(20, int(browser_use_max_steps)))
    final_result = _history_call(history, "final_result", "")
    urls = _history_call(history, "urls", []) or []
    screenshot_paths = _history_call(history, "screenshot_paths", []) or []
    errors = _history_call(history, "errors", []) or []
    steps = _history_call(history, "number_of_steps", 0)
    done = _history_call(history, "is_done", False)
    successful = _history_call(history, "is_successful", None)

    non_empty_errors = [str(e) for e in errors if e]
    if successful is False or (not done and non_empty_errors):
        last_error = non_empty_errors[-1] if non_empty_errors else ""
        if "DeploymentNotFound" in last_error:
            raise RuntimeError(
                "browser-use failed because the configured model/deployment was not found. "
                "Set AZURE_OPENAI_DEPLOYMENT (or OPENAI_MODEL) to an existing deployment, "
                "or run with --browser-use-model <deployment-name>."
            )
        raise RuntimeError(
            "browser-use agent did not complete successfully. "
            + (f"Last error: {last_error}" if last_error else "No final successful result.")
        )

    return {
        "url": str(urls[-1]) if urls else url,
        "filled_at": datetime.now().isoformat(),
        "fields_filled": 0,  # browser-use returns free-form result; exact count is not guaranteed
        "total_fields": 0,
        "filled_fields": [],
        "field_suggestions": [],
        "unfilled_required_fields": [],
        "screenshot": str(screenshot_paths[-1]) if screenshot_paths else "n/a",
        "submitted": bool(submit),
        "backend": "browser-use",
        "browser_use": {
            "steps": int(steps or 0),
            "final_result": str(final_result or ""),
            "errors": non_empty_errors,
        },
    }


async def fill_application_form(
    url: Optional[str] = None,
    cv_md_path: Optional[Path] = None,
    submit: bool = False,
    headless: bool = False,
    use_existing_browser: bool = False,
    cdp_url: str = "http://127.0.0.1:9222",
    tab_url: Optional[str] = None,
    follow: bool = True,
    follow_interval: float = 1.5,
    follow_seconds: int = 0,
    engine: str = "playwright",
    browser_use_llm_provider: str = "auto",
    browser_use_model: Optional[str] = None,
    browser_use_max_steps: int = 120,
    chrome_profile: Optional[str] = None,
) -> Dict[str, Any]:
    if cv_md_path is None:
        cv_md_path = Path(__file__).resolve().parents[1] / "cv" / "cv.md"
    if not cv_md_path.exists():
        raise ValueError(f"CV markdown file not found: {cv_md_path}")

    cv_profile = load_cv_from_markdown(cv_md_path)
    if not cv_profile.raw_text:
        raise ValueError(f"Could not parse CV markdown file: {cv_md_path}")

    normalized_engine = _normalize_engine(engine)

    if normalized_engine == "browser-use":
        target_url = (tab_url or url or "").strip()
        if not target_url:
            raise ValueError("Browser-use engine requires a URL. Pass --url or --tab-url.")

        cv_agent = FormFillerAgent(
            cv_profile=cv_profile,
            headless=headless,
            use_existing_browser=use_existing_browser,
            cdp_url=cdp_url,
        )
        result = await _fill_application_form_browser_use(
            url=target_url,
            form_data=cv_agent.form_data,
            submit=submit,
            headless=headless,
            use_existing_browser=use_existing_browser,
            cdp_url=cdp_url,
            browser_use_llm_provider=browser_use_llm_provider,
            browser_use_model=browser_use_model,
            browser_use_max_steps=browser_use_max_steps,
            chrome_profile=chrome_profile,
        )
        logger.success("Browser-use form flow complete.")
        return result

    agent = FormFillerAgent(
        cv_profile=cv_profile,
        headless=headless,
        use_existing_browser=use_existing_browser,
        cdp_url=cdp_url,
    )
    result = await agent.fill_form(
        url=url,
        submit=submit,
        tab_url=tab_url,
        follow=follow,
        follow_interval=follow_interval,
        follow_seconds=follow_seconds,
    )
    logger.success(f"Form filling complete. Filled {result['fields_filled']}/{result['total_fields']} fields")
    return result
