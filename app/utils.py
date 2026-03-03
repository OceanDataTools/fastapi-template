import hashlib
from uuid import UUID

import bcrypt
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from app.config import settings


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def get_apikey_hash(apikey: str) -> str:
    return hashlib.sha256(apikey.encode()).hexdigest()


def send_reset_email(email: str, token: str) -> bool:
    """Send a password reset email via SendGrid."""
    reset_link = f"{settings.frontend_url}/reset-password?token={token}"
    print(f"[DEV] Send email to {email} with link: {reset_link}")

    # Return now if sendgrid not configured
    if not settings.sendgrid_from_email:
        return True

    message = Mail(
        from_email=settings.sendgrid_from_email,
        to_emails=email,
        subject="Password Reset Request",
        plain_text_content=f"Click the following link to reset your password: {reset_link}",
        html_content=f"""
            <p>Hello,</p>
            <p>You requested a password reset. Click the link below to set a new password:</p>
            <p><a href="{reset_link}">Reset Password</a></p>
            <p>If you did not request this, you can safely ignore this email.</p>
        """,
    )

    try:
        sg = SendGridAPIClient(settings.sendgrid_api_key)
        response = sg.send(message)
        return response.status_code == 202  # 202 = Accepted for delivery
    except Exception as e:
        print(f"Error sending email: {e}")
        return False


def cast_uuid(val):
    return str(val) if isinstance(val, UUID) else val
