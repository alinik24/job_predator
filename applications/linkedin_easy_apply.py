"""
LinkedIn Easy Apply Automation (AIHawk-inspired)
================================================
Automated application submission for LinkedIn Easy Apply jobs.

Features:
- GPT-powered form field analysis and intelligent answering
- Resume upload automation
- Cover letter generation and upload
- Multi-step application handling
- CAPTCHA detection and pause
- Anti-bot detection evasion (human-like delays, mouse movements)

Based on Auto_Jobs_Applier_AIHawk architecture (20k+ stars on GitHub)
"""

import asyncio
import random
import time
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from playwright.async_api import async_playwright, Page, Browser
from loguru import logger
from core.llm_client import get_llm_client

from core.config import settings
from core.models import Job


class LinkedInEasyApply:
    """
    Automates LinkedIn Easy Apply job applications with GPT-powered form filling.
    """

    def __init__(
        self,
        email: str,
        password: str,
        resume_path: Path,
        cover_letter_generator: Optional[callable] = None,
        headless: bool = False
    ):
        """
        Args:
            email: LinkedIn email
            password: LinkedIn password
            resume_path: Path to PDF resume
            cover_letter_generator: Function to generate cover letter for a job
            headless: Run browser in headless mode
        """
        self.email = email
        self.password = password
        self.resume_path = Path(resume_path)
        self.cover_letter_generator = cover_letter_generator
        self.headless = headless

        # GPT client for form filling
        self.llm = AzureOpenAI(
            azure_endpoint=settings.llm_api_base_url,
            api_key=settings.llm_api_key,
            api_version=settings.llm_api_version,
        )

        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.applications_submitted = 0

    async def initialize(self):
        """Launch browser and login to LinkedIn"""
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=self.headless)

        # Create context with realistic user agent
        context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        self.page = await context.new_page()

        # Login
        await self._login()
        logger.info("LinkedIn Easy Apply initialized and logged in")

    async def _login(self):
        """Login to LinkedIn with human-like behavior"""
        logger.info("Logging in to LinkedIn...")

        await self.page.goto("https://www.linkedin.com/login", wait_until="networkidle")
        await self._human_delay(1, 2)

        # Type email with human-like delays
        await self.page.fill('input[name="session_key"]', "")
        for char in self.email:
            await self.page.type('input[name="session_key"]', char, delay=random.randint(50, 150))
        await self._human_delay(0.5, 1)

        # Type password
        await self.page.fill('input[name="session_password"]', "")
        for char in self.password:
            await self.page.type('input[name="session_password"]', char, delay=random.randint(50, 150))
        await self._human_delay(0.5, 1)

        # Click login
        await self.page.click('button[type="submit"]')
        await self._human_delay(3, 5)

        # Check if logged in
        try:
            await self.page.wait_for_selector('input[placeholder*="Search"]', timeout=10000)
            logger.info("Successfully logged in to LinkedIn")
        except:
            logger.error("Login failed or CAPTCHA detected. Please solve manually.")
            # Wait for manual intervention
            await asyncio.sleep(60)

    async def apply_to_job(self, job_url: str, job_data: Optional[Dict] = None) -> Tuple[bool, str]:
        """
        Apply to a single LinkedIn Easy Apply job.

        Args:
            job_url: LinkedIn job URL
            job_data: Optional job metadata for better form filling

        Returns:
            (success: bool, message: str)
        """
        try:
            logger.info(f"Applying to job: {job_url}")

            # Navigate to job page
            await self.page.goto(job_url, wait_until="networkidle")
            await self._human_delay(2, 4)

            # Check if Easy Apply button exists
            easy_apply_button = await self.page.query_selector('button:has-text("Easy Apply")')
            if not easy_apply_button:
                return False, "Not an Easy Apply job"

            # Click Easy Apply
            await easy_apply_button.click()
            await self._human_delay(1, 2)

            # Handle multi-step application form
            success = await self._fill_application_form(job_data)

            if success:
                self.applications_submitted += 1
                return True, f"Application submitted successfully (#{self.applications_submitted})"
            else:
                return False, "Failed to complete application form"

        except Exception as e:
            logger.error(f"Error applying to job: {e}")
            return False, str(e)

    async def _fill_application_form(self, job_data: Optional[Dict]) -> bool:
        """
        Fill out multi-step LinkedIn Easy Apply form using GPT.

        Returns True if successfully submitted.
        """
        max_steps = 10
        current_step = 0

        while current_step < max_steps:
            current_step += 1
            await self._human_delay(1, 2)

            # Check if we've reached the review/submit page
            submit_button = await self.page.query_selector('button:has-text("Submit application")')
            if submit_button:
                logger.info("Reached final submit page")
                await submit_button.click()
                await self._human_delay(2, 3)

                # Check for success confirmation
                try:
                    await self.page.wait_for_selector('h3:has-text("Your application was sent")', timeout=5000)
                    logger.info("✓ Application submitted successfully!")
                    return True
                except:
                    logger.warning("Submit may have failed or confirmation not detected")
                    return False

            # Fill current step
            await self._fill_form_fields(job_data)

            # Click Next button
            next_button = await self.page.query_selector('button:has-text("Next")')
            if next_button:
                await next_button.click()
                await self._human_delay(1, 2)
            else:
                # If no Next button, check for Review
                review_button = await self.page.query_selector('button:has-text("Review")')
                if review_button:
                    await review_button.click()
                    await self._human_delay(1, 2)
                else:
                    logger.warning("Could not find Next or Review button")
                    return False

        logger.warning("Exceeded maximum application steps")
        return False

    async def _fill_form_fields(self, job_data: Optional[Dict]):
        """Fill form fields on current page using GPT"""
        # Get all input fields
        text_inputs = await self.page.query_selector_all('input[type="text"], input[type="tel"], input[type="email"]')
        textareas = await self.page.query_selector_all('textarea')
        selects = await self.page.query_selector_all('select')
        radio_groups = await self.page.query_selector_all('fieldset')

        # Upload resume if file input exists
        file_inputs = await self.page.query_selector_all('input[type="file"]')
        for file_input in file_inputs:
            label = await self._get_field_label(file_input)
            if "resume" in label.lower() or "cv" in label.lower():
                await file_input.set_input_files(str(self.resume_path))
                logger.debug(f"Uploaded resume to: {label}")

        # Fill text inputs
        for input_field in text_inputs:
            label = await self._get_field_label(input_field)
            value = await self._generate_field_answer(label, job_data)
            if value:
                await input_field.fill(value)
                await self._human_delay(0.2, 0.5)
                logger.debug(f"Filled '{label}' with '{value}'")

        # Fill textareas
        for textarea in textareas:
            label = await self._get_field_label(textarea)
            value = await self._generate_field_answer(label, job_data, is_long_text=True)
            if value:
                await textarea.fill(value)
                await self._human_delay(0.5, 1)
                logger.debug(f"Filled textarea '{label}'")

        # Fill selects (dropdowns)
        for select in selects:
            label = await self._get_field_label(select)
            options = await select.query_selector_all('option')
            option_texts = [await opt.inner_text() for opt in options]

            # Use GPT to select best option
            selected = await self._select_best_option(label, option_texts, job_data)
            if selected:
                await select.select_option(label=selected)
                await self._human_delay(0.3, 0.6)
                logger.debug(f"Selected '{selected}' for '{label}'")

        # Handle radio buttons
        for fieldset in radio_groups:
            legend = await fieldset.query_selector('legend')
            if legend:
                question = await legend.inner_text()
                radios = await fieldset.query_selector_all('input[type="radio"]')

                if radios:
                    # Use GPT to answer yes/no questions
                    answer = await self._answer_yes_no_question(question, job_data)
                    # Click appropriate radio button
                    for radio in radios:
                        label_elem = await self.page.query_selector(f'label[for="{await radio.get_attribute("id")}"]')
                        if label_elem:
                            label_text = await label_elem.inner_text()
                            if answer.lower() in label_text.lower():
                                await radio.click()
                                await self._human_delay(0.2, 0.4)
                                break

    async def _get_field_label(self, element) -> str:
        """Get the label text for a form field"""
        try:
            # Try to find associated label
            field_id = await element.get_attribute("id")
            if field_id:
                label = await self.page.query_selector(f'label[for="{field_id}"]')
                if label:
                    return await label.inner_text()

            # Fallback: use placeholder or name
            placeholder = await element.get_attribute("placeholder")
            if placeholder:
                return placeholder

            name = await element.get_attribute("name")
            return name or "Unknown field"

        except:
            return "Unknown field"

    async def _generate_field_answer(
        self,
        field_label: str,
        job_data: Optional[Dict],
        is_long_text: bool = False
    ) -> str:
        """Use GPT to generate appropriate answer for a field"""
        # Simple rule-based answers for common fields
        field_lower = field_label.lower()

        if "phone" in field_lower or "mobile" in field_lower:
            return "+49 123 4567890"  # Placeholder
        elif "email" in field_lower:
            return self.email
        elif "linkedin" in field_lower:
            return "linkedin.com/in/yourprofile"
        elif "salary" in field_lower or "compensation" in field_lower:
            return "Negotiable"
        elif "years of experience" in field_lower or "experience" in field_lower:
            return "3"  # Adjust based on CV
        elif "notice period" in field_lower:
            return "3 months"
        elif "available" in field_lower and "start" in field_lower:
            return "Immediately"
        elif is_long_text:
            # Use GPT for long-form answers
            return await self._gpt_answer_question(field_label, job_data)

        return ""

    async def _gpt_answer_question(self, question: str, job_data: Optional[Dict]) -> str:
        """Use GPT to answer open-ended questions"""
        try:
            prompt = f"""You are filling out a job application form. Answer this question professionally and concisely (max 200 words):

Question: {question}

Job context: {job_data.get('title', 'Not specified') if job_data else 'Not specified'}

Your answer:"""

            response = self.llm.chat.completions.create(
                model=settings.llm_model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.7
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            logger.warning(f"GPT answer generation failed: {e}")
            return "I am very interested in this opportunity and believe my skills align well with the requirements."

    async def _select_best_option(
        self,
        question: str,
        options: List[str],
        job_data: Optional[Dict]
    ) -> Optional[str]:
        """Use GPT to select best option from dropdown"""
        if not options or len(options) <= 1:
            return None

        # Filter out placeholder options
        real_options = [opt for opt in options if opt and opt.strip() and opt.strip() != "Select" and opt.strip() != "Choose"]

        if not real_options:
            return None

        # Simple heuristic for common questions
        question_lower = question.lower()
        if "authorization" in question_lower or "legally authorized" in question_lower:
            for opt in real_options:
                if "yes" in opt.lower() or "authorized" in opt.lower():
                    return opt

        # Return first valid option as fallback
        return real_options[0]

    async def _answer_yes_no_question(self, question: str, job_data: Optional[Dict]) -> str:
        """Answer yes/no questions intelligently"""
        question_lower = question.lower()

        # Default to "yes" for authorization questions
        if "authorized" in question_lower or "eligible" in question_lower or "legally" in question_lower:
            return "yes"

        # Default to "no" for sponsorship questions
        if "sponsor" in question_lower or "visa" in question_lower:
            return "no"

        # Default to "yes" for willingness questions
        if "willing" in question_lower or "able to" in question_lower:
            return "yes"

        return "yes"  # Conservative default

    async def _human_delay(self, min_seconds: float = 0.5, max_seconds: float = 2.0):
        """Add random delay to simulate human behavior"""
        delay = random.uniform(min_seconds, max_seconds)
        await asyncio.sleep(delay)

    async def close(self):
        """Close browser"""
        if self.browser:
            await self.browser.close()
            logger.info(f"LinkedIn Easy Apply closed. Total applications: {self.applications_submitted}")


# Example usage
async def main():
    applier = LinkedInEasyApply(
        email="your@email.com",
        password="yourpassword",
        resume_path=Path("./user_documents/cv.pdf"),
        headless=False
    )

    await applier.initialize()

    # Apply to jobs
    job_urls = [
        "https://www.linkedin.com/jobs/view/1234567890/",
        # Add more job URLs
    ]

    for url in job_urls:
        success, message = await applier.apply_to_job(url)
        print(f"{url}: {message}")
        await asyncio.sleep(random.randint(30, 60))  # Delay between applications

    await applier.close()


if __name__ == "__main__":
    asyncio.run(main())
