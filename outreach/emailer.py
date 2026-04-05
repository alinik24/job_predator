"""
Email outreach module — send tailored emails to HR contacts.

Uses Azure OpenAI to personalize each email based on:
  - The specific job and company
  - The HR contact's name and title
  - The candidate's CV profile
  - Whether it's a direct application, follow-up, or cold outreach

Also handles LinkedIn message drafting for when email isn't available.
"""
from __future__ import annotations

import asyncio
import smtplib
import ssl
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Optional
from uuid import UUID

import aiosmtplib
from loguru import logger
from openai import AzureOpenAI
from sqlalchemy import select

from core.config import settings, get_token_kwargs, get_token_kwargs
from core.database import get_session
from core.models import CVProfileSchema, HRContact, Job, OutreachChannel, OutreachMessage

EMAIL_PROMPT = """\
Write a professional, concise job application email in {language}.

TONE: Professional, enthusiastic, direct. NOT generic — use specific details.
LENGTH: 3-4 short paragraphs maximum. Subject line + body only.
FORMAT: Return as JSON: {{"subject": "...", "body": "..."}}

CANDIDATE: {cv_summary}
COMPANY: {company}
POSITION: {job_title}
CONTACT NAME: {contact_name}
CONTACT TITLE: {contact_title}
EMAIL TYPE: {email_type}

EMAIL TYPES:
- "application": Direct application with CV attached
- "follow_up": Follow-up 1 week after submitting application
- "cold_outreach": Reaching out before applying, requesting info or connection
- "linkedin_message": Short LinkedIn message (150 chars max)

For German emails:
- Use formal "Sie" address
- Address as "Sehr geehrte/r {name}" or "Sehr geehrtes {company} Team"
- Sign off with "Mit freundlichen Grüßen"

For linkedin_message: Must be under 150 characters, casual but professional.
"""

LINKEDIN_MESSAGE_PROMPT = """\
Write a very short LinkedIn connection request message (under 150 characters) in {language}.
Be specific, mention the job or company, and make it personal.

Context:
- Candidate: {candidate_name}
- Company: {company}
- Job: {job_title}
- Contact: {contact_name} ({contact_title})

Return ONLY the message text, nothing else.
"""


class Emailer:
    """Sends personalized emails and drafts LinkedIn messages for HR outreach."""

    def __init__(self, cv_profile: CVProfileSchema):
        self.cv_profile = cv_profile
        self.client = AzureOpenAI(
            azure_endpoint=settings.llm_api_base_url,
            api_key=settings.llm_api_key,
            api_version=settings.llm_api_version,
        )
        self.model_name = settings.llm_model_name
        from cv.cv_parser import CVParser
        self._cv_summary = CVParser().get_cv_summary_for_llm(cv_profile)

    def compose_email(
        self,
        job: Job,
        contact: HRContact,
        email_type: str = "application",
        language: str = "de",
    ) -> dict:
        """
        Generate a personalized email for a specific HR contact and job.
        Returns {"subject": str, "body": str}
        """
        contact_name = contact.full_name or contact.company
        contact_title = contact.title or "HR Team"

        prompt = EMAIL_PROMPT.format(
            language="German" if language == "de" else "English",
            cv_summary=self._cv_summary[:1000],
            company=job.company,
            job_title=job.title,
            contact_name=contact_name,
            contact_title=contact_title,
            email_type=email_type,
        )

        try:
            import json
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "You are an expert at writing job application emails."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.5,
                response_format={"type": "json_object"},
            )
            result = json.loads(response.choices[0].message.content)
            return result
        except Exception as e:
            logger.error(f"[Emailer] Compose error: {e}")
            return {
                "subject": f"Bewerbung als {job.title} - {self.cv_profile.full_name or ''}",
                "body": f"Sehr geehrte/r {contact_name},\n\nbitte finden Sie anbei meine Bewerbungsunterlagen für die Position {job.title}.\n\nMit freundlichen Grüßen\n{self.cv_profile.full_name or ''}",
            }

    def compose_linkedin_message(
        self,
        job: Job,
        contact: HRContact,
        language: str = "de",
    ) -> str:
        """Generate a short LinkedIn connection request message (< 150 chars)."""
        prompt = LINKEDIN_MESSAGE_PROMPT.format(
            language="German" if language == "de" else "English",
            candidate_name=self.cv_profile.full_name or "ich",
            company=job.company,
            job_title=job.title,
            contact_name=contact.full_name or "Sie",
            contact_title=contact.title or "",
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
                **get_token_kwargs(self.model_name, 60),
            )
            msg = response.choices[0].message.content.strip()
            return msg[:150]  # enforce limit
        except Exception as e:
            logger.error(f"[Emailer] LinkedIn message error: {e}")
            return f"Hallo {contact.full_name or ''}, ich bewerbe mich auf die Position {job.title} bei {job.company}."

    async def send_email(
        self,
        job: Job,
        contact: HRContact,
        email_type: str = "application",
        language: str = "de",
        attachments: Optional[List[str]] = None,
        dry_run: bool = False,
    ) -> OutreachMessage:
        """
        Compose and send an email to an HR contact.
        Stores the message in the database regardless of dry_run.
        """
        if not contact.email:
            logger.warning(f"[Emailer] No email address for {contact.full_name} @ {contact.company}")
            raise ValueError("Contact has no email address")

        # Compose
        loop = asyncio.get_event_loop()
        email_content = await loop.run_in_executor(
            None, lambda: self.compose_email(job, contact, email_type, language)
        )

        subject = email_content.get("subject", f"Bewerbung als {job.title}")
        body = email_content.get("body", "")

        logger.info(f"[Emailer] Prepared email to {contact.email}: '{subject}'")

        # Store in DB
        message = await self._store_message(
            contact_id=contact.id,
            job_id=job.id,
            channel=OutreachChannel.EMAIL,
            subject=subject,
            body=body,
        )

        if dry_run:
            logger.info("[Emailer] DRY RUN — email not sent")
            return message

        # Send
        if not settings.smtp_user or not settings.smtp_password:
            logger.error("[Emailer] SMTP credentials not configured")
            return message

        try:
            await self._send_via_smtp(
                to_email=contact.email,
                subject=subject,
                body=body,
                attachments=attachments or [],
            )

            # Update message status
            async with get_session() as session:
                msg = await session.get(OutreachMessage, message.id)
                if msg:
                    msg.sent_at = datetime.utcnow()
                    msg.status = "sent"
                    session.add(msg)

            logger.info(f"[Emailer] ✓ Email sent to {contact.email}")

        except Exception as e:
            logger.error(f"[Emailer] Send failed: {e}")

        return message

    async def _send_via_smtp(
        self,
        to_email: str,
        subject: str,
        body: str,
        attachments: List[str],
    ) -> None:
        """Send email via SMTP with optional attachments."""
        msg = MIMEMultipart()
        msg["From"] = settings.email_from or settings.smtp_user
        msg["To"] = to_email
        msg["Subject"] = subject

        msg.attach(MIMEText(body, "plain", "utf-8"))

        # Add attachments
        for file_path in attachments:
            path = Path(file_path)
            if path.exists():
                with open(path, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition", f'attachment; filename="{path.name}"'
                    )
                    msg.attach(part)

        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            start_tls=True,
            username=settings.smtp_user,
            password=settings.smtp_password,
        )

    async def draft_linkedin_messages_batch(
        self,
        jobs_with_contacts: list[tuple[Job, HRContact]],
    ) -> List[OutreachMessage]:
        """Batch-draft LinkedIn messages for all job contacts."""
        messages = []
        for job, contact in jobs_with_contacts:
            if not contact.linkedin_url:
                continue
            msg_text = self.compose_linkedin_message(job, contact)
            msg = await self._store_message(
                contact_id=contact.id,
                job_id=job.id,
                channel=OutreachChannel.LINKEDIN_MESSAGE,
                subject=None,
                body=msg_text,
            )
            messages.append(msg)
        return messages

    async def _store_message(
        self,
        contact_id: UUID,
        job_id,
        channel: OutreachChannel,
        subject: Optional[str],
        body: str,
    ) -> OutreachMessage:
        async with get_session() as session:
            msg = OutreachMessage(
                contact_id=contact_id,
                job_id=job_id,
                channel=channel,
                subject=subject,
                body=body,
                status="draft",
            )
            session.add(msg)
            await session.flush()
            await session.refresh(msg)
        return msg
