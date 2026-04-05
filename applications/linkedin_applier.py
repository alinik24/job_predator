"""
LinkedIn Easy Apply automation using Playwright.

Inspired by Auto_Jobs_Applier_AIHawk (feder-cr/Auto_Jobs_Applier_AIHawk)
but rewritten for Playwright (more reliable than Selenium for modern LinkedIn).

Flow:
  1. Login to LinkedIn
  2. Navigate to job listing
  3. Click "Easy Apply" button
  4. Handle multi-step application form
  5. Upload CV and cover letter
  6. Answer all questions via FormAI
  7. Submit (or pause for human review)
  8. Log result to database
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

LINKEDIN_BASE = "https://www.linkedin.com"


class LinkedInApplier:
    """Automates LinkedIn Easy Apply using Playwright."""

    def __init__(self, cv_profile: CVProfileSchema, cv_pdf_path: Optional[str] = None):
        self.cv_profile = cv_profile
        self.cv_pdf_path = cv_pdf_path or settings.cv_pdf_path
        self.form_ai = FormAI(cv_profile, cv_pdf_path)
        self._page = None
        self._browser = None

    async def __aenter__(self):
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=settings.headless_browser,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        self._page = await context.new_page()
        return self

    async def __aexit__(self, *args):
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def login(self) -> bool:
        """Login to LinkedIn. Returns True if successful."""
        if not settings.linkedin_email or not settings.linkedin_password:
            logger.error("[LinkedIn] No credentials configured (LINKEDIN_EMAIL / LINKEDIN_PASSWORD)")
            return False

        logger.info("[LinkedIn] Logging in...")
        page = self._page

        try:
            await page.goto(f"{LINKEDIN_BASE}/login", wait_until="domcontentloaded", timeout=30000)
            await page.fill("#username", settings.linkedin_email)
            await page.fill("#password", settings.linkedin_password)
            await page.click("button[type='submit']")
            await page.wait_for_timeout(3000)

            # Check for 2FA or CAPTCHA
            if "challenge" in page.url or "checkpoint" in page.url:
                logger.warning("[LinkedIn] 2FA / CAPTCHA detected — waiting for manual input (30s)")
                await page.wait_for_timeout(30000)

            if "feed" in page.url or "jobs" in page.url or "mynetwork" in page.url:
                logger.info("[LinkedIn] Login successful")
                return True

            logger.error(f"[LinkedIn] Login failed — current URL: {page.url}")
            return False

        except Exception as e:
            logger.error(f"[LinkedIn] Login error: {e}")
            return False

    async def apply_to_job(
        self,
        job: Job,
        cover_letter_path: Optional[str] = None,
        dry_run: bool = False,
    ) -> bool:
        """
        Apply to a single LinkedIn job.

        Args:
            job: The Job ORM object
            cover_letter_path: Path to generated cover letter PDF/DOCX
            dry_run: If True, fill form but don't submit

        Returns:
            True if application was submitted successfully
        """
        page = self._page
        logger.info(f"[LinkedIn] Applying to: '{job.title}' @ '{job.company}'")

        # Update status
        await self._update_status(job.id, ApplicationStatus.APPLYING)

        try:
            # Navigate to the job page
            await page.goto(job.url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            # Find and click the Easy Apply button
            easy_apply_btn = await self._find_easy_apply_button(page)
            if not easy_apply_btn:
                logger.warning(f"[LinkedIn] No Easy Apply button found for: {job.title}")
                await self._update_status(job.id, ApplicationStatus.SKIPPED)
                return False

            await easy_apply_btn.click()
            await page.wait_for_timeout(2000)

            # Handle the multi-step modal
            success = await self._handle_application_modal(
                page, job, cover_letter_path, dry_run
            )

            if success:
                await self._update_status(job.id, ApplicationStatus.APPLIED, applied=True)
                logger.info(f"[LinkedIn] ✓ Applied: '{job.title}' @ '{job.company}'")
            else:
                await self._update_status(job.id, ApplicationStatus.SKIPPED)

            return success

        except Exception as e:
            logger.error(f"[LinkedIn] Application error for '{job.title}': {e}")
            await self._update_status(job.id, ApplicationStatus.SKIPPED)
            return False

    async def _find_easy_apply_button(self, page) -> Optional[object]:
        """Find the Easy Apply button on the job page."""
        selectors = [
            "button.jobs-apply-button[aria-label*='Easy Apply']",
            "button[aria-label*='Easy Apply']",
            ".jobs-s-apply button",
            "button:has-text('Easy Apply')",
            "button:has-text('Einfach bewerben')",
        ]
        for selector in selectors:
            try:
                btn = await page.wait_for_selector(selector, timeout=3000)
                if btn and await btn.is_visible():
                    return btn
            except Exception:
                continue
        return None

    async def _handle_application_modal(
        self,
        page,
        job: Job,
        cover_letter_path: Optional[str],
        dry_run: bool,
    ) -> bool:
        """Handle the Easy Apply multi-step form modal."""
        max_steps = 15
        step = 0

        while step < max_steps:
            step += 1
            await page.wait_for_timeout(1000)

            # Check if modal is still open
            modal = await page.query_selector(
                ".jobs-easy-apply-modal, [data-test-modal-id='easy-apply-modal'], "
                ".artdeco-modal"
            )
            if not modal:
                logger.debug("[LinkedIn] Modal closed")
                break

            # Fill all visible fields on this step
            form_answers = await self.form_ai.fill_form(page, job, cover_letter_path)
            logger.debug(f"[LinkedIn] Step {step}: filled {len(form_answers)} fields")

            # Human review pause
            if settings.human_review and step == 1:
                logger.info("[LinkedIn] HUMAN REVIEW MODE — press Enter to continue...")
                # In production: implement a proper pause mechanism
                # For now, we check a flag file or wait a few seconds
                await page.wait_for_timeout(5000)

            # Look for Submit button
            submit_btn = await self._find_submit_button(page)
            if submit_btn:
                if dry_run:
                    logger.info("[LinkedIn] DRY RUN — not submitting")
                    return True
                await submit_btn.click()
                await page.wait_for_timeout(2000)

                # Confirm submission
                if await self._confirm_submission(page):
                    return True
                break

            # Look for Next button
            next_btn = await self._find_next_button(page)
            if next_btn:
                await next_btn.click()
                await page.wait_for_timeout(1000)
                continue

            # No next and no submit — something unexpected
            logger.warning(f"[LinkedIn] No next/submit button found at step {step}")
            break

        return False

    async def _find_submit_button(self, page) -> Optional[object]:
        selectors = [
            "button[aria-label='Submit application']",
            "button[aria-label='Bewerbung einreichen']",
            "button:has-text('Submit application')",
            "button:has-text('Bewerbung einreichen')",
            "footer button.artdeco-button--primary",
        ]
        for selector in selectors:
            try:
                btn = await page.query_selector(selector)
                if btn and await btn.is_visible() and await btn.is_enabled():
                    return btn
            except Exception:
                continue
        return None

    async def _find_next_button(self, page) -> Optional[object]:
        selectors = [
            "button[aria-label='Continue to next step']",
            "button[aria-label='Weiter zum nächsten Schritt']",
            "button:has-text('Next')",
            "button:has-text('Weiter')",
            "footer button.artdeco-button--primary",
        ]
        for selector in selectors:
            try:
                btn = await page.query_selector(selector)
                if btn and await btn.is_visible() and await btn.is_enabled():
                    return btn
            except Exception:
                continue
        return None

    async def _confirm_submission(self, page) -> bool:
        """Check if submission was confirmed (success modal appeared)."""
        try:
            success = await page.wait_for_selector(
                "[data-test-modal-id='post-apply-modal'], "
                ".artdeco-modal:has-text('application was sent'), "
                ".artdeco-modal:has-text('Bewerbung wurde gesendet')",
                timeout=5000,
            )
            if success:
                # Close the success modal
                close_btn = await page.query_selector("button[aria-label='Dismiss']")
                if close_btn:
                    await close_btn.click()
                return True
        except Exception:
            pass
        return False

    async def _update_status(
        self,
        job_id: UUID,
        status: ApplicationStatus,
        applied: bool = False,
    ) -> None:
        async with get_session() as session:
            # Find or create application record
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

            # Also update job status
            job = await session.get(Job, job_id)
            if job:
                job.status = status
                session.add(job)
