"""
Django email backend for Azure Communication Services (ACS) Email.

Auth is Microsoft Entra ID via DefaultAzureCredential — no secrets:
  * on Azure App Service: the web app's system-assigned managed identity
  * locally: your `az login` session

Safety valve: if settings.EMAIL_ALLOWED_RECIPIENTS is non-empty, any other
recipient is dropped (logged, never sent). Local .env sets it to the
developer's own address so a dev database full of real users can't be emailed.
"""

import logging
from email.utils import parseaddr

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)


class AzureCommunicationEmailBackend(BaseEmailBackend):
    _client = None

    def _get_client(self):
        if AzureCommunicationEmailBackend._client is None:
            from azure.communication.email import EmailClient
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
            AzureCommunicationEmailBackend._client = EmailClient(settings.ACS_EMAIL_ENDPOINT, credential)
        return AzureCommunicationEmailBackend._client

    def _allowed(self, address):
        allow = {a.lower() for a in settings.EMAIL_ALLOWED_RECIPIENTS}
        return not allow or address.lower() in allow

    def send_messages(self, email_messages):
        sent = 0
        for message in email_messages:
            recipients = [parseaddr(r)[1] for r in message.recipients()]
            blocked = [r for r in recipients if not self._allowed(r)]
            if blocked:
                logger.warning('EMAIL_BLOCKED_BY_ALLOWLIST to=%s subject=%r', blocked, message.subject)
            recipients = [r for r in recipients if self._allowed(r)]
            if not recipients:
                continue

            html = next(
                (body for body, mime in getattr(message, 'alternatives', []) if mime == 'text/html'),
                None,
            )
            content = {'subject': message.subject, 'plainText': message.body}
            if html:
                content['html'] = html

            payload = {
                'senderAddress': parseaddr(message.from_email or settings.DEFAULT_FROM_EMAIL)[1],
                'recipients': {'to': [{'address': r} for r in recipients]},
                'content': content,
            }
            if message.reply_to:
                payload['replyTo'] = [{'address': parseaddr(r)[1]} for r in message.reply_to]

            try:
                # begin_send returns once ACS has accepted the message; delivery
                # continues asynchronously, so don't block the request on it.
                self._get_client().begin_send(payload)
                logger.info('EMAIL_QUEUED to=%s subject=%r', recipients, message.subject)
                sent += 1
            except Exception:
                logger.exception('EMAIL_SEND_FAILED to=%s subject=%r', recipients, message.subject)
                if not self.fail_silently:
                    raise
        return sent
