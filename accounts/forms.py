import re

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import AuthenticationForm, UsernameField
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from .models import DISPLAY_NAME_MAX_LENGTH, Profile

User = get_user_model()

EMAIL_TAKEN = "An account with this email already exists."
SIGN_IN_ERROR = "The email or password is incorrect."


class SignUpForm(forms.Form):
    """US10 #39: email and password. The lowercased email is stored as both
    username and email, so sign-in can use Django's username-based auth."""

    email = forms.EmailField(
        max_length=150,  # User.username's max length
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
    )
    password1 = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=password_validation.password_validators_help_text_html(),
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(username__iexact=email).exists():
            raise ValidationError(EMAIL_TAKEN)
        return email

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "The two passwords do not match.")
        if password1:
            # The validators compare the password with the email, so build
            # the user it would belong to.
            email = cleaned.get("email", "")
            user = User(username=email, email=email)
            try:
                password_validation.validate_password(password1, user)
            except ValidationError as error:
                self.add_error("password1", error)
        return cleaned

    def save(self):
        """Create the user. Returns None if the email was taken meanwhile."""
        email = self.cleaned_data["email"]
        try:
            with transaction.atomic():
                return User.objects.create_user(
                    username=email,
                    email=email,
                    password=self.cleaned_data["password1"],
                )
        except IntegrityError:
            self.add_error("email", EMAIL_TAKEN)
            return None


class SignInForm(AuthenticationForm):
    """US11 #40: Django's AuthenticationForm with the email as the
    username. Every failure (unknown email, wrong password, inactive
    account) shows the same message, so it never says whether an email has
    an account."""

    error_messages = {
        "invalid_login": SIGN_IN_ERROR,
        "inactive": SIGN_IN_ERROR,
    }

    username = UsernameField(
        label="Email",
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
    )

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


class DeleteAccountForm(forms.Form):
    """US12 #41: confirm deleting the account by entering the password."""

    password = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise ValidationError("The password is incorrect.")
        return password


# ---- US30 #92: display name ----

DISPLAY_NAME_MIN_LENGTH = 3
NAME_REQUIRED = "Enter a display name."
NAME_TOO_SHORT = f"Use at least {DISPLAY_NAME_MIN_LENGTH} characters."
NAME_TOO_LONG = f"Use at most {DISPLAY_NAME_MAX_LENGTH} characters."
NAME_OTHER_CHARACTERS = (
    "Use only letters (A to Z), numbers, spaces, dots (.), dashes (-) "
    "and underscores (_)."
)
NAME_CONTAINS_EMAIL = (
    "A display name can't contain an email address. Other riders see this name."
)
NAME_IS_EMAIL_START = (
    "Choose a name that isn't the start of your email address. "
    "Other riders see this name."
)
NAME_NEEDS_LETTER = "Include at least one letter or number."
NAME_RESERVED = "That name is reserved. Choose another one."
NAME_TAKEN = "That display name is already taken. Choose another one."

# ASCII only, so a look-alike letter (Cyrillic "А") can't copy another
# rider's "Alex" past the case-insensitive uniqueness check.
ALLOWED_NAME = re.compile(r"[A-Za-z0-9 ._-]+")
HAS_LETTER_OR_NUMBER = re.compile(r"[A-Za-z0-9]")
# Compared ignoring capitals, so nobody can pose as the site or its staff.
RESERVED_NAMES = frozenset(
    {
        "admin",
        "administrator",
        "moderator",
        "mod",
        "staff",
        "support",
        "system",
        "official",
        "taxiscope",
        "taxiscope nyc",
    }
)


class DisplayNameForm(forms.Form):
    """US30 #92: the name other riders see, set and changed on My account."""

    display_name = forms.CharField(
        label="Display name",
        error_messages={"required": NAME_REQUIRED},
        help_text=f"{DISPLAY_NAME_MIN_LENGTH} to {DISPLAY_NAME_MAX_LENGTH} "
        "characters: letters, numbers, spaces, dots, dashes and underscores.",
        widget=forms.TextInput(
            attrs={"maxlength": str(DISPLAY_NAME_MAX_LENGTH), "autocomplete": "off"}
        ),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        self.profile = Profile.objects.filter(user=user).first()
        if self.profile is not None:
            kwargs.setdefault("initial", {"display_name": self.profile.display_name})
        super().__init__(*args, **kwargs)

    def clean_display_name(self):
        # The field has already trimmed it; runs of spaces become one.
        name = re.sub(" {2,}", " ", self.cleaned_data["display_name"])
        if "@" in name:
            raise forms.ValidationError(NAME_CONTAINS_EMAIL)
        if len(name) < DISPLAY_NAME_MIN_LENGTH:
            raise forms.ValidationError(NAME_TOO_SHORT)
        if len(name) > DISPLAY_NAME_MAX_LENGTH:
            raise forms.ValidationError(NAME_TOO_LONG)
        if not ALLOWED_NAME.fullmatch(name):
            raise forms.ValidationError(NAME_OTHER_CHARACTERS)
        if not HAS_LETTER_OR_NUMBER.search(name):
            raise forms.ValidationError(NAME_NEEDS_LETTER)
        if name.lower() in RESERVED_NAMES:
            raise forms.ValidationError(NAME_RESERVED)
        if name.lower() == self.user.email.split("@")[0].lower():
            raise forms.ValidationError(NAME_IS_EMAIL_START)
        taken = Profile.objects.filter(display_name__iexact=name).exclude(
            user=self.user
        )
        if taken.exists():
            raise forms.ValidationError(NAME_TAKEN)
        return name

    def save(self):
        """Create or change the name. Returns None if someone else took it
        meanwhile; the database's case-insensitive unique index decides."""
        try:
            with transaction.atomic():
                profile, _ = Profile.objects.update_or_create(
                    user=self.user,
                    defaults={"display_name": self.cleaned_data["display_name"]},
                )
                return profile
        except IntegrityError:
            self.add_error("display_name", NAME_TAKEN)
            return None
