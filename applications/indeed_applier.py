"""
Indeed Germany application automation.

Indeed DE has two application flows:
  1. Indeed Apply (hosted on indeed.com) — handled here
  2. External redirect to company ATS — handled by form_ai.py

Indeed Apply uses a multi-step form similar to LinkedIn Easy Apply.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional
from uuid import UUID

from loguru import logger

from applications.form_ai import FormAI
from core.config import settings
from core.database import get_session
from core.models import Application, ApplicationStatus, CVProfileSchema, Job

INDEED_BASE = "https://de.indeed.com"


class IndeedApplier:
    """Automates Indeed Germany job applications."""

    def __init__(self, cv_profile: CVProfileSchema, cv_pdf_path: Optional[str] = None):
        self.cv_profile = cv_profile
        self.cv_pdf_path = cv_pdf_path or settings.cv_pdf_path
        self.form_ai = FormAI(cv_profile, cv_pdf_path)

    async def apply_to_job(
        self,
        job: Job,
        cover_letter_path: Optional[str] = None,
        dry_run: bool = False,
    ) -> bool:
        """Apply to an Indeed Germany job."""
        from playwright.async_api import async_playwright

        logger.info(f"[Indeed] Applying to: '{job.title}' @ '{job.company}'")
        await self._update_status(job.id, ApplicationStatus.APPLYING)

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=settings.headless_browser,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="de-DE",
            )
            page = await context.new_page()

            try:
                apply_url = job.apply_url or job.url
                await page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)

                # Dismiss cookie banner
                await self._dismiss_cookie_banner(page)
                await page.wait_for_timeout(2000)

                # Login to Indeed if credentials available
                if settings.indeed_email and settings.indeed_password:
                    await self._login(page)

                # Find apply button
                apply_btn = await self._find_apply_button(page)
                if not apply_btn:
                    logger.warning(f"[Indeed] No apply button for: {job.title}")
                    await self._update_status(job.id, ApplicationStatus.SKIPPED)
                    return False

                await apply_btn.click()
                await page.wait_for_timeout(2000)

                # Fill application
                success = await self._fill_indeed_apply(page, job, cover_letter_path, dry_run)

                if success:
                    await self._update_status(job.id, ApplicationStatus.APPLIED, applied=True)
                    logger.info(f"[Indeed] ✓ Applied: '{job.title}'")
                else:
                    await self._update_status(job.id, ApplicationStatus.SKIPPED)

                return success

            except Exception as e:
                logger.error(f"[Indeed] Error: {e}")
                await self._update_status(job.id, ApplicationStatus.SKIPPED)
                return False
            finally:
                await browser.close()

    async def _login(self, page) -> None:
        """Login to Indeed.de."""
        try:
            current = page.url
            await page.goto(f"{INDEED_BASE}/account/login", wait_until="domcontentloaded")
            await self._dismiss_cookie_banner(page)

            email_input = await page.query_selector("#ifl-InputFormField-3, input[name='__email']")
            if email_input:
                await email_input.fill(settings.indeed_email)
                continue_btn = await page.query_selector(
                    "button:has-text('Weiter'), button:has-text('Continue')"
                )
                if continue_btn:
                    await continue_btn.click()
                    await page.wait_for_timeout(1500)

            pwd_input = await page.query_selector(
                "input[type='password'], input[name='__password']"
            )
            if pwd_input:
                await pwd_input.fill(settings.indeed_password)
                login_btn = await page.query_selector("button[type='submit']")
                if login_btn:
                    await login_btn.click()
                    await page.wait_for_timeout(2000)

            # Navigate back to original page
            await page.goto(current, wait_until="domcontentloaded")
        except Exception as e:
            logger.debug(f"[Indeed] Login: {e}")

    async def _find_apply_button(self, page) -> Optional[object]:
        selectors = [
            "button[id*='apply'], button.indeed-apply-button",
            "a.indeed-apply-button",
            "button:has-text('Jetzt bewerben')",
            "button:has-text('Sofort bewerben')",
            "a:has-text('Bewerben')",
            "[data-testid='apply-button']",
        ]
        for selector in selectors:
            try:
                btn = await page.wait_for_selector(selector, timeout=3000)
                if btn and await btn.is_visible():
                    return btn
            except Exception:
                continue
        return None

    async def _fill_indeed_apply(
        self, page, job: Job, cover_letter_path: Optional[str], dry_run: bool
    ) -> bool:
        """Handle Indeed Apply multi-step form."""
        for step in range(10):
            await page.wait_for_timeout(1000)

            # Upload CV if requested
            file_input = await page.query_selector("input[type='file']")
            if file_input and self.cv_pdf_path:
                try:
                    await file_input.set_input_files(self.cv_pdf_path)
                except Exception:
                    pass

            # Fill fields
            answers = await self.form_ai.fill_form(page, job, cover_letter_path)
            logger.debug(f"[Indeed] Step {step+1}: filled {len(answers)} fields")

            # Submit
            submit = await page.query_selector(
                "button[type='submit']:has-text('Bewerbung einreichen'), "
                "button:has-text('Jetzt bewerben'), "
                "button[data-testid='submit-application']"
            )
            if submit and await submit.is_visible():
                if dry_run:
                    return True
                await submit.click()
                await page.wait_for_timeout(3000)
                return await self._check_success(page)

            # Next
            nxt = await page.query_selector(
                "button:has-text('Weiter'), button[data-testid='continue-button']"
            )
            if nxt and await nxt.is_visible():
                await nxt.click()
                continue

            break

        return False

    async def _check_success(self, page) -> bool:
        try:
            success = await page.wait_for_selector(
                ":has-text('Bewerbung eingegangen'), :has-text('application submitted'), "
                "[class*='success-message'], [class*='thankYou']",
                timeout=5000,
            )
            return success is not None
        except Exception:
            return False

    async def _dismiss_cookie_banner(self, page) -> None:
        selectors = [
            "button#onetrust-accept-btn-handler",
            "button:has-text('Alle akzeptieren')",
            "button:has-text('Accept all')",
        ]
        for selector in selectors:
            try:
                btn = await page.wait_for_selector(selector, timeout=2000)
                if btn:
                    await btn.click()
                    return
            except Exception:
                continue

    async def _update_status(
        self, job_id: UUID, status: ApplicationStatus, applied: bool = False
    ) -> None:
        async with get_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(Application).where(Application.job_id == job_id)
            )
            app = result.scalar_one_or_none()
            if not app:
                app = Application(job_id=job_id, status=status)
                session.add(app)
            else:
                app.status = status
            if applied:
                app.applied_at = datetime.utcnow()
            job = await session.get(Job, job_id)
            if job:
                job.status = status
