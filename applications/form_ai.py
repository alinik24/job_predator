"""
AI-powered form field detection and filling.

This module provides generic form automation logic:
  - Detect form fields (text, select, radio, checkbox, textarea, file upload)
  - Map field labels to appropriate answers using ApplicationQA
  - Handle multi-step forms
  - Handle file uploads (CV, cover letter)

Used by all platform-specific appliers (LinkedIn, Indeed, StepStone).
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger

from core.config import settings
from core.models import CVProfileSchema, Job
from documents.qa import ApplicationQA


class FormAI:
    """
    Intelligent form filler that works with any Playwright page.
    Detects fields, generates answers, and fills them in.
    """

    def __init__(self, cv_profile: CVProfileSchema, cv_pdf_path: Optional[str] = None):
        self.cv_profile = cv_profile
        self.cv_pdf_path = cv_pdf_path or settings.cv_pdf_path
        self.qa = ApplicationQA(cv_profile)

    async def fill_form(
        self,
        page,
        job: Optional[Job] = None,
        cover_letter_path: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Fill all detected form fields on the current page.
        Returns a dict of {label: answer} for logging.
        """
        filled: Dict[str, str] = {}

        # Get all form elements
        fields = await self._detect_fields(page)
        logger.debug(f"[FormAI] Detected {len(fields)} form fields")

        for field in fields:
            try:
                answer = await self._fill_field(page, field, job, cover_letter_path)
                if answer:
                    filled[field.get("label", field.get("name", "?"))] = answer
                await asyncio.sleep(0.3)  # human-like delay between fields
            except Exception as e:
                logger.warning(f"[FormAI] Failed to fill field '{field.get('label')}': {e}")

        return filled

    async def _detect_fields(self, page) -> List[Dict]:
        """
        Detect all interactive form fields on the page.
        Returns a list of field descriptor dicts.
        """
        fields = []

        # Text inputs and textareas
        inputs = await page.query_selector_all(
            "input:not([type='hidden']):not([type='submit']):not([type='button']):not([type='checkbox']):not([type='radio']):not([type='file']), "
            "textarea"
        )
        for inp in inputs:
            field = await self._describe_field(page, inp)
            if field:
                fields.append(field)

        # Select dropdowns
        selects = await page.query_selector_all("select")
        for sel in selects:
            field = await self._describe_select(page, sel)
            if field:
                fields.append(field)

        # File uploads
        file_inputs = await page.query_selector_all("input[type='file']")
        for fi in file_inputs:
            label = await self._get_field_label(page, fi)
            fields.append({
                "type": "file",
                "element": fi,
                "label": label,
                "name": await fi.get_attribute("name") or "",
            })

        # Checkboxes and radios (grouped by name)
        checkboxes = await page.query_selector_all("input[type='checkbox'], input[type='radio']")
        seen_names = set()
        for cb in checkboxes:
            name = await cb.get_attribute("name") or ""
            if name and name not in seen_names:
                seen_names.add(name)
                label = await self._get_field_label(page, cb)
                field_type = await cb.get_attribute("type") or "checkbox"
                fields.append({
                    "type": field_type,
                    "element": cb,
                    "label": label,
                    "name": name,
                })

        return fields

    async def _describe_field(self, page, element) -> Optional[Dict]:
        """Build a descriptor dict for a text/textarea field."""
        try:
            tag = await element.evaluate("el => el.tagName.toLowerCase()")
            input_type = await element.get_attribute("type") or "text"
            name = await element.get_attribute("name") or ""
            placeholder = await element.get_attribute("placeholder") or ""
            is_required = await element.get_attribute("required") is not None
            is_visible = await element.is_visible()
            is_editable = await element.is_editable()

            if not is_visible or not is_editable:
                return None

            label = await self._get_field_label(page, element)

            # Determine field purpose from label/name/placeholder
            question = label or placeholder or name

            return {
                "type": "textarea" if tag == "textarea" else input_type,
                "element": element,
                "label": label,
                "name": name,
                "placeholder": placeholder,
                "question": question,
                "required": is_required,
            }
        except Exception:
            return None

    async def _describe_select(self, page, element) -> Optional[Dict]:
        """Build a descriptor dict for a select/dropdown field."""
        try:
            is_visible = await element.is_visible()
            if not is_visible:
                return None

            label = await self._get_field_label(page, element)
            name = await element.get_attribute("name") or ""

            # Get all options
            options = await element.evaluate(
                "el => Array.from(el.options).map(o => ({value: o.value, text: o.text.trim()}))"
            )

            return {
                "type": "select",
                "element": element,
                "label": label,
                "name": name,
                "options": [o["text"] for o in options if o["value"]],
                "option_values": {o["text"]: o["value"] for o in options if o["value"]},
                "question": label or name,
            }
        except Exception:
            return None

    async def _get_field_label(self, page, element) -> str:
        """Try multiple strategies to find the label for a form element."""
        try:
            # Strategy 1: aria-label attribute
            aria = await element.get_attribute("aria-label")
            if aria:
                return aria.strip()

            # Strategy 2: associated <label> via id
            el_id = await element.get_attribute("id")
            if el_id:
                label_el = await page.query_selector(f"label[for='{el_id}']")
                if label_el:
                    text = await label_el.inner_text()
                    return text.strip()

            # Strategy 3: parent label element
            parent_label = await element.evaluate(
                "el => el.closest('label')?.innerText?.trim() || ''"
            )
            if parent_label:
                return parent_label

            # Strategy 4: preceding sibling or parent text
            nearby_text = await element.evaluate(
                """el => {
                    const parent = el.parentElement;
                    if (!parent) return '';
                    const clone = parent.cloneNode(true);
                    clone.querySelectorAll('input, select, textarea, button').forEach(e => e.remove());
                    return clone.innerText?.trim() || '';
                }"""
            )
            return nearby_text[:100] if nearby_text else ""
        except Exception:
            return ""

    async def _fill_field(
        self,
        page,
        field: Dict,
        job: Optional[Job],
        cover_letter_path: Optional[str],
    ) -> Optional[str]:
        """Fill a single form field. Returns the filled value or None."""
        element = field["element"]
        field_type = field["type"]
        question = field.get("question", "") or field.get("label", "") or field.get("name", "")

        if not question:
            return None

        # File upload
        if field_type == "file":
            return await self._handle_file_upload(element, field, cover_letter_path)

        # Boolean / checkbox
        if field_type in ("checkbox", "radio"):
            return await self._handle_boolean_field(element, field, job, question)

        # Select dropdown
        if field_type == "select":
            return await self._handle_select(element, field, job, question)

        # Text / textarea / number / email / tel
        answer = await self.qa.answer(
            question=question,
            job=job,
            field_type="number" if field_type == "number" else "text",
        )

        if answer:
            await element.click()
            await element.fill(answer)
            return answer

        return None

    async def _handle_file_upload(
        self, element, field: Dict, cover_letter_path: Optional[str]
    ) -> Optional[str]:
        """Upload CV or cover letter to a file input."""
        label = (field.get("label") or "").lower()
        name = (field.get("name") or "").lower()
        field_hint = label + name

        # Determine which file to upload
        file_path = None
        if any(kw in field_hint for kw in ["cv", "resume", "lebenslauf"]):
            file_path = self.cv_pdf_path
        elif any(kw in field_hint for kw in ["cover", "anschreiben", "motivation"]):
            file_path = cover_letter_path

        if not file_path or not Path(file_path).exists():
            # Default: upload CV
            if self.cv_pdf_path and Path(self.cv_pdf_path).exists():
                file_path = self.cv_pdf_path
            else:
                logger.warning(f"[FormAI] No file found for upload: {field.get('label')}")
                return None

        try:
            await element.set_input_files(file_path)
            logger.info(f"[FormAI] Uploaded: {Path(file_path).name} → {field.get('label')}")
            return Path(file_path).name
        except Exception as e:
            logger.error(f"[FormAI] File upload failed: {e}")
            return None

    async def _handle_boolean_field(self, element, field: Dict, job, question: str) -> Optional[str]:
        """Handle checkbox/radio fields."""
        answer = await self.qa.answer(question, job, field_type="boolean")
        if answer and answer.lower() in ("yes", "ja", "true", "1"):
            try:
                is_checked = await element.is_checked()
                if not is_checked:
                    await element.click()
                return "Yes"
            except Exception as e:
                logger.debug(f"[FormAI] Checkbox error: {e}")
        return "No"

    async def _handle_select(self, element, field: Dict, job, question: str) -> Optional[str]:
        """Handle dropdown select fields."""
        options = field.get("options", [])
        if not options:
            return None

        answer = await self.qa.answer(question, job, field_type="select", options=options)

        # Find best matching option
        best_option = _find_best_option(answer, options)
        if best_option:
            try:
                await element.select_option(label=best_option)
                return best_option
            except Exception:
                # Try by value
                option_values = field.get("option_values", {})
                value = option_values.get(best_option)
                if value:
                    try:
                        await element.select_option(value=value)
                        return best_option
                    except Exception as e:
                        logger.debug(f"[FormAI] Select error: {e}")

        return None


def _find_best_option(answer: str, options: List[str]) -> Optional[str]:
    """Find the best matching option for a given answer string."""
    if not answer or not options:
        return None

    answer_lower = answer.lower().strip()

    # Exact match
    for opt in options:
        if opt.lower().strip() == answer_lower:
            return opt

    # Partial match
    for opt in options:
        if answer_lower in opt.lower() or opt.lower() in answer_lower:
            return opt

    # Skip placeholder options
    meaningful = [o for o in options if o.lower() not in ("", "select...", "bitte wählen", "--")]
    if len(meaningful) == 1:
        return meaningful[0]

    return None
