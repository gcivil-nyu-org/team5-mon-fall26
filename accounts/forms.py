from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

User = get_user_model()

EMAIL_TAKEN = "An account with this email already exists."


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
