"""EMAIL-201: Transactional email infrastructure. Abstract provider for verification, invites, password resets."""

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Protocol


@dataclass
class EmailMessage:
    to: str
    subject: str
    body_text: str
    body_html: str | None = None


class EmailProvider(Protocol):
    """Protocol for sending transactional email. Implement with SendGrid, SES, etc."""

    def send(self, message: EmailMessage) -> bool:
        """Send email. Return True if accepted for delivery."""
        ...


class ConsoleEmailProvider:
    """Stub provider that logs to stdout. Use in dev/tests when SMTP_HOST is unset."""

    def send(self, message: EmailMessage) -> bool:
        print(f"[EMAIL] To: {message.to}\nSubject: {message.subject}\n\n{message.body_text}\n", flush=True)
        return True


class SmtpEmailProvider:
    """Send via SMTP (STARTTLS on 587, or SSL on 465). Set SMTP_HOST to enable."""

    def __init__(
        self,
        host: str,
        port: int,
        user: str | None,
        password: str | None,
        from_addr: str,
        use_tls: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.from_addr = from_addr
        self.use_tls = use_tls

    def send(self, message: EmailMessage) -> bool:
        try:
            mime = MIMEMultipart("alternative")
            mime["Subject"] = message.subject
            mime["From"] = self.from_addr
            mime["To"] = message.to
            mime.attach(MIMEText(message.body_text, "plain", "utf-8"))
            if message.body_html:
                mime.attach(MIMEText(message.body_html, "html", "utf-8"))
            raw = mime.as_string()

            if self.port == 465:
                ctx = ssl.create_default_context()
                with smtplib.SMTP_SSL(self.host, self.port, context=ctx) as s:
                    if self.user and self.password:
                        s.login(self.user, self.password)
                    s.sendmail(self.from_addr, [message.to], raw)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=10) as s:
                    s.ehlo()
                    if self.use_tls:
                        s.starttls(context=ssl.create_default_context())
                        s.ehlo()
                    if self.user and self.password:
                        s.login(self.user, self.password)
                    s.sendmail(self.from_addr, [message.to], raw)
            return True
        except Exception as e:
            print(f"[EMAIL] SMTP send failed ({self.host}:{self.port}): {e}", flush=True)
            print(f"[EMAIL-FALLBACK] To: {message.to}\nSubject: {message.subject}\n\n{message.body_text}\n", flush=True)
            return False


_default_provider: EmailProvider | None = None


def get_email_provider() -> EmailProvider:
    """Return the configured email provider (SMTP if SMTP_HOST set, else console stub)."""
    global _default_provider
    if _default_provider is not None:
        return _default_provider
    host = os.getenv("SMTP_HOST", "").strip()
    if host:
        port = int(os.getenv("SMTP_PORT", "587").strip() or "587")
        user = os.getenv("SMTP_USER", "").strip() or None
        password = os.getenv("SMTP_PASSWORD", "").strip() or None
        from_addr = os.getenv("SMTP_FROM", "").strip() or user or "noreply@localhost"
        use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes")
        _default_provider = SmtpEmailProvider(
            host=host,
            port=port,
            user=user,
            password=password,
            from_addr=from_addr,
            use_tls=use_tls,
        )
        print(f"[EMAIL] Provider: SMTP ({host}:{port}, from={from_addr}, tls={use_tls})", flush=True)
    else:
        _default_provider = ConsoleEmailProvider()
        print("[EMAIL] Provider: Console (SMTP_HOST not set; emails logged to stdout)", flush=True)
    return _default_provider


def set_email_provider(provider: EmailProvider | None) -> None:
    """Set the email provider (e.g. for tests). Pass None to reset lazy init."""
    global _default_provider
    _default_provider = provider


def send_verification_email(to: str, verify_url: str) -> bool:
    """Send email verification link. Used by AUTH-207."""
    msg = EmailMessage(
        to=to,
        subject="Verify your email - Trust Copilot",
        body_text=f"Click to verify your email: {verify_url}\n\nThis link expires in 24 hours.",
        body_html=f"<p>Click to verify your email: <a href=\"{verify_url}\">{verify_url}</a></p><p>This link expires in 24 hours.</p>",
    )
    return get_email_provider().send(msg)


def send_password_reset_email(to: str, reset_url: str) -> bool:
    """Send password reset link. Used by AUTH-209."""
    msg = EmailMessage(
        to=to,
        subject="Reset your password - Trust Copilot",
        body_text=f"Click to reset your password: {reset_url}\n\nThis link expires in 1 hour.",
        body_html=f"<p>Click to reset your password: <a href=\"{reset_url}\">{reset_url}</a></p><p>This link expires in 1 hour.</p>",
    )
    return get_email_provider().send(msg)


def send_invite_email(
    to: str,
    inviter_name: str,
    workspace_name: str,
    verify_page_url: str,
    verification_code: str,
) -> bool:
    """Send workspace invite with human verification code and link to the verify page (AUTH-208)."""
    msg = EmailMessage(
        to=to,
        subject=f"You're invited to {workspace_name} - Trust Copilot",
        body_text=(
            f"{inviter_name} invited you to join the workspace \"{workspace_name}\" on Trust Copilot.\n\n"
            f"Your verification code:\n  {verification_code}\n\n"
            f"Open this link and enter the email address this invite was sent to plus the code above:\n  {verify_page_url}\n\n"
            f"The code expires when the invite expires (typically 7 days)."
        ),
        body_html=(
            f"<p>{inviter_name} invited you to join <strong>{workspace_name}</strong> on Trust Copilot.</p>"
            f"<p>Your verification code:</p>"
            f"<p style=\"font-size:1.25rem;letter-spacing:0.05em;font-family:monospace;font-weight:bold;\">{verification_code}</p>"
            f"<p>Open the link below, then enter your email and this code to continue:</p>"
            f"<p><a href=\"{verify_page_url}\">{verify_page_url}</a></p>"
        ),
    )
    return get_email_provider().send(msg)


def send_suspicious_login_email(to: str, reason: str = "Failed two-factor verification") -> bool:
    """AUTH-214: Notify user of suspicious/failed auth (e.g. failed MFA)."""
    msg = EmailMessage(
        to=to,
        subject="Suspicious sign-in attempt - Trust Copilot",
        body_text=f"We noticed: {reason}. If this wasn't you, please change your password and review your security settings.",
        body_html=f"<p>We noticed: <strong>{reason}</strong>.</p><p>If this wasn't you, please change your password and review your security settings.</p>",
    )
    return get_email_provider().send(msg)


def send_trust_reply_email(to: str, body: str, subject: str | None = None) -> bool:
    """TR-REQ-B3: Send reply to a trust request requester. Body is the reply text."""
    subj = subject or "Re: Your trust information request"
    msg = EmailMessage(
        to=to,
        subject=f"{subj} - Trust Copilot",
        body_text=body,
        body_html=f"<p>{body.replace(chr(10), '<br>')}</p>",
    )
    return get_email_provider().send(msg)
