"""
Send the "ClinicAI is now MedlynAI" announcement email.

  python manage.py send_rebrand_email --test you@example.com   # one preview, not recorded
  python manage.py send_rebrand_email --dry-run                 # who would get it
  python manage.py send_rebrand_email --all                     # send, paced and resumable

Each address is emailed at most once (tracked in EmailCampaignSend), so --all can
be stopped and re-run safely. Pacing defaults to 90/hour, under the ACS quota
for the verified medlynai.com domain (100/hour per subscription; password-reset
emails share it, hence the headroom).
"""

import time

from django.core.management.base import BaseCommand, CommandError

from notifications.models import EmailCampaignSend
from notifications.rebrand_email import CAMPAIGN, build_message, recipients


def _mask(email):
    local, _, domain = email.partition('@')
    return f'{local[:2]}***@{domain}'


class Command(BaseCommand):
    help = 'Send the ClinicAI → MedlynAI rebrand announcement email.'

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--test', metavar='EMAIL', help='Send one preview to EMAIL (not recorded).')
        mode.add_argument('--dry-run', action='store_true', help='List pending recipients, send nothing.')
        mode.add_argument('--all', action='store_true', help='Send to every pending recipient.')
        parser.add_argument('--per-hour', type=int, default=90,
                            help='Max emails per hour (default 90, under the 100/hour ACS quota).')
        parser.add_argument('--limit', type=int, default=0, help='Stop after this many sends (0 = no limit).')

    def handle(self, *args, **opts):
        everyone = recipients()

        if opts['test']:
            email = opts['test'].strip().lower()
            sent = build_message(email, everyone.get(email)).send()
            if not sent:
                raise CommandError(f'Not sent to {email} (blocked by EMAIL_ALLOWED_RECIPIENTS?).')
            self.stdout.write(self.style.SUCCESS(f'Preview sent to {email}.'))
            return

        done = set(EmailCampaignSend.objects.filter(campaign=CAMPAIGN).values_list('email', flat=True))
        pending = [(e, u) for e, u in everyone.items() if e not in done]
        self.stdout.write(f'{len(everyone)} addresses · {len(done)} already sent · {len(pending)} pending')

        if opts['dry_run']:
            for email, user in pending:
                self.stdout.write(f'  {_mask(email)}  ({user.username})')
            return

        if opts['limit']:
            pending = pending[:opts['limit']]
        gap = 3600 / max(opts['per_hour'], 1)
        if pending:
            self.stdout.write(f'Sending {len(pending)} at ~{opts["per_hour"]}/hour '
                              f'(about {len(pending) * gap / 3600:.1f} h). Ctrl+C to pause; re-run to resume.')

        sent_count = 0
        for i, (email, user) in enumerate(pending):
            if i:
                time.sleep(gap)
            if not self._send_with_retry(email, user):
                continue
            EmailCampaignSend.objects.get_or_create(campaign=CAMPAIGN, email=email, defaults={'user': user})
            sent_count += 1
            self.stdout.write(f'  [{sent_count}/{len(pending)}] sent → {_mask(email)}')

        self.stdout.write(self.style.SUCCESS(f'Done. Sent {sent_count} this run.'))

    def _send_with_retry(self, email, user, attempts=4):
        for attempt in range(attempts):
            try:
                if build_message(email, user).send():
                    return True
                self.stderr.write(f'  skipped {_mask(email)} (blocked by EMAIL_ALLOWED_RECIPIENTS)')
                return False
            except Exception as exc:
                status = getattr(exc, 'status_code', None)
                if status == 429 and attempt < attempts - 1:
                    retry = getattr(getattr(exc, 'response', None), 'headers', {}).get('Retry-After')
                    wait = int(retry) if str(retry or '').isdigit() else 600
                    self.stderr.write(f'  Azure quota reached; waiting {wait}s before retrying…')
                    time.sleep(wait)
                    continue
                self.stderr.write(f'  FAILED {_mask(email)}: {type(exc).__name__}: {exc}')
                return False
        return False
