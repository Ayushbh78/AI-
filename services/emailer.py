"""Send e-mail for free.

Order of use:
  1. BREVO_API_KEY set  -> Brevo HTTPS API (free plan: 300 e-mails a day). Works on Render's free plan, which blocks SMTP ports.
  2. SMTP_HOST set      -> normal SMTP (for your own PC, e.g. Gmail app password). Does NOT work on Render free.
  3. nothing set        -> only on your own PC: the code is printed in the terminal so you can test.
                           On Render the sign-up shows a clear "email is not set up" message instead.
"""
import os
import smtplib
import ssl
from email.message import EmailMessage

import requests

from .config import get_setting

BREVO_URL = "https://api.brevo.com/v3/smtp/email"


class MailError(Exception):
    pass


def _sender():
    address = get_setting("MAIL_FROM") or get_setting("SMTP_USER")
    return address, get_setting("MAIL_FROM_NAME", "AI Vidyalaya")


def configured():
    return bool(get_setting("BREVO_API_KEY") or get_setting("SMTP_HOST"))


def is_cloud():
    return bool(os.environ.get("RENDER"))


def send(to, subject, text, html):
    """Send one e-mail. Returns True if it was handed to a provider, False if only printed locally. Raises MailError."""
    address, name = _sender()
    api_key = get_setting("BREVO_API_KEY")
    if api_key:
        if not address:
            raise MailError("MAIL_FROM is missing. Set it to the sender e-mail you verified in Brevo.")
        try:
            r = requests.post(BREVO_URL, timeout=15,
                              headers={"api-key": api_key, "accept": "application/json", "content-type": "application/json"},
                              json={"sender": {"name": name, "email": address}, "to": [{"email": to}],
                                    "subject": subject, "htmlContent": html, "textContent": text})
        except requests.RequestException as exc:
            raise MailError("Could not reach the e-mail service. Try again in a moment.") from exc
        if r.status_code not in (200, 201, 202):
            print(f"Brevo error {r.status_code}: {r.text[:300]}", flush=True)
            raise MailError("The e-mail could not be sent. The app owner should check the Brevo key and sender.")
        return True

    host = get_setting("SMTP_HOST")
    if host:
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, f"{name} <{address}>", to
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        port = int(get_setting("SMTP_PORT", "465") or 465)
        try:
            if port == 465:
                with smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context()) as s:
                    s.login(get_setting("SMTP_USER"), get_setting("SMTP_PASSWORD")); s.send_message(msg)
            else:
                with smtplib.SMTP(host, port, timeout=15) as s:
                    s.starttls(context=ssl.create_default_context())
                    s.login(get_setting("SMTP_USER"), get_setting("SMTP_PASSWORD")); s.send_message(msg)
        except (OSError, smtplib.SMTPException) as exc:
            raise MailError("The e-mail could not be sent. Check the SMTP settings.") from exc
        return True

    if is_cloud():
        raise MailError("E-mail sending is not set up yet. The app owner must add BREVO_API_KEY and MAIL_FROM.")
    print(f"\n=== E-MAIL (not sent, no provider set) ===\nTo: {to}\nSubject: {subject}\n{text}\n==========================================\n", flush=True)
    return False


def send_code(to, code, purpose):
    """The one e-mail this app sends: a 6-digit code. purpose: signup | reset | login."""
    what = {"signup": "verify your e-mail and finish creating your account",
            "reset": "reset your password",
            "login": "log in"}.get(purpose, "continue")
    subject = f"{code} is your AI Vidyalaya code"
    text = (f"Your AI Vidyalaya code is {code}\n\nUse it to {what}. It works for 10 minutes.\n"
            "If you did not ask for this, you can ignore this e-mail.")
    html = f"""<div style="font-family:Arial,sans-serif;max-width:420px;margin:auto;padding:24px;border:1px solid #e3e6f0;border-radius:14px">
<h2 style="margin:0 0 6px;color:#3b3bb5">AI विद्यालय</h2>
<p style="color:#444;margin:0 0 18px">Use this code to {what}:</p>
<div style="font-size:34px;font-weight:700;letter-spacing:8px;text-align:center;background:#f2f3fb;border-radius:12px;padding:14px 0;color:#1d1d3a">{code}</div>
<p style="color:#666;font-size:13px;margin:18px 0 0">It works for 10 minutes. If you did not ask for this, ignore this e-mail.</p></div>"""
    return send(to, subject, text, html)
