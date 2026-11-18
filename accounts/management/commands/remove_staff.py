"""US39 #113: take away an account's staff rights. The account stays as a
normal rider account; delete it in the admin (Accounts) to remove it fully.
Django checks is_staff on every admin request, so this takes effect at once,
even for a staff member who is signed in."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()


class Command(BaseCommand):
    help = (
        "Remove an account's staff rights, so it can no longer open /admin/. "
        "The account itself is kept."
    )

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="The account's email.")

    def handle(self, *args, email, **options):
        email = email.strip().lower()
        user = User.objects.filter(username=email).first()
        if user is None:
            raise CommandError(f"No account with the email {email}.")
        if not (user.is_staff or user.is_superuser):
            self.stdout.write(f"{email} is not a staff account. Nothing changed.")
            return
        user.is_staff = False
        user.is_superuser = False
        user.save(update_fields=["is_staff", "is_superuser"])
        self.stdout.write(
            f"{email} is no longer a staff account. The account is kept as a "
            "normal rider account."
        )
