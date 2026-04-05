"""
StepStone application automation using Playwright.

StepStone applications typically redirect to:
  1. StepStone's own application form (hosted on stepstone.de)
  2. External company ATS (Workday, Greenhouse, Lever, etc.)
  3. Direct email application

This module handles StepStone-hosted forms. For external ATS,
it delegates to form_ai.py for generic form filling.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import UUID

from loguru import logger

from applications.form_ai import FormAI
from core.config import settings
from core.database import get_session
from core.models import Application, ApplicationStatus, CVProfileSchema, Job
from scrapers.stepstone_scraper import _dismiss_cookie_banner


class StepStoneApplier:
    """Automates application submission on StepStone Germany."""

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
        """Apply to a StepStone job listing."""
        from playwright.async_api import async_playwright

        logger.info(f"[StepStone] Applying to: '{job.title}' @ '{job.company}'")
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
                await _dismiss_cookie_banner(page)
                await page.wait_for_timeout(2000)

                # Find the apply button
                apply_btn = await self._find_apply_button(page)
                if not apply_btn:
                    logger.warning(f"[StepStone] No apply button found for: {job.title}")
                    await self._update_status(job.id, ApplicationStatus.SKIPPED)
                    return False

                await apply_btn.click()
                await page.wait_for_timeout(2000)

                # Check if we're on StepStone's form or redirected
                current_url = page.url
                logger.debug(f"[StepStone] After click URL: {current_url}")

                # Handle login prompt (StepStone may ask to log in)
                await self._handle_login_prompt(page)

                # Fill the application form
                success = await self._fill_application(
                    page, job, cover_letter_path, dry_run
                )

                if success:
                    await self._update_status(job.id, ApplicationStatus.APPLIED, applied=True)
                    logger.info(f"[StepStone] ✓ Applied: '{job.title}'")
                else:
                    await self._update_status(job.id, ApplicationStatus.SKIPPED)

                return success

            except Exception as e:
                logger.error(f"[StepStone] Error applying to '{job.title}': {e}")
                await self._update_status(job.id, ApplicationStatus.SKIPPED)
                return False
            finally:
                await browser.close()

    async def _find_apply_button(self, page) -> Optional[object]:
        selectors = [
            "a[data-at='header-apply-button']",
            "button[data-at='header-apply-button']",
            "a.res-apply-button",
            "button:has-text('Jetzt bewerben')",
            "a:has-text('Jetzt bewerben')",
            "button:has-text('Bewerben')",
            "[class*='apply-button']",
        ]
        for selector in selectors:
            try:
                btn = await page.wait_for_selector(selector, timeout=3000)
                if btn and await btn.is_visible():
                    return btn
            except Exception:
                continue
        return None

    async def _handle_login_prompt(self, page) -> None:
        """Handle StepStone login prompt if it appears."""
        try:
            if not settings.stepstone_email or not settings.stepstone_password:
                # Try to proceed as guest
                guest_btn = await page.query_selector(
                    "button:has-text('Als Gast'), button:has-text('Continue as guest')"
                )
                if guest_btn:
                    await guest_btn.click()
                    await page.wait_for_timeout(1500)
                return

            login_form = await page.query_selector("input[type='email'], input[name='email']")
            if login_form and await login_form.is_visible():
                await login_form.fill(settings.stepstone_email)
                pwd_input = await page.query_selector(
                    "input[type='password'], input[name='password']"
                )
                if pwd_input:
                    await pwd_input.fill(settings.stepstone_password)
                    submit = await page.query_selector("button[type='submit']")
                    if submit:
                        await submit.click()
                        await page.wait_for_timeout(2000)
        except Exception as e:
            logger.debug(f"[StepStone] Login handling: {e}")

    async def _fill_application(
        self, page, job: Job, cover_letter_path: Optional[str], dry_run: bool
    ) -> bool:
        """Fill and submit the StepStone application form."""
        max_steps = 10
        for step in range(max_steps):
            await page.wait_for_timeout(1000)

            # Fill current page fields
            answers = await self.form_ai.fill_form(page, job, cover_letter_path)
            logger.debug(f"[StepStone] Step {step+1}: filled {len(answers)} fields")

            # Check for submit
            submit_btn = await page.query_selector(
                "button[type='submit']:has-text('Bewerbung absenden'), "
                "button:has-text('Jetzt absenden'), "
                "button:has-text('Absenden'), "
                "input[type='submit']"
            )
            if submit_btn and await submit_btn.is_visible():
                if dry_run:
                    logger.info("[StepStone] DRY RUN — not submitting")
                    return True
                await submit_btn.click()
                await page.wait_for_timeout(3000)

                # Check for success
                success_el = await page.query_selector(
                    "[class*='success'], [class*='confirmation'], "
                    ":has-text('Bewerbung eingegangen'), :has-text('erfolgreich')"
                )
                return success_el is not None

            # Next step
            next_btn = await page.query_selector(
                "button:has-text('Weiter'), button:has-text('Nächster Schritt'), "
                "button[type='submit']:not(:has-text('Absenden'))"
            )
            if next_btn and await next_btn.is_visible():
                await next_btn.click()
                continue

            break

        return False

    async def _update_status(
        self,
        job_id: UUID,
        status: ApplicationStatus,
        applied: bool = False,
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
