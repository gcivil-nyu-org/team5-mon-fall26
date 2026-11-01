# Accounts: notes for the stories that build on them

User accounts came in with US10 (sign up), US11 (sign in and sign out) and
US12 (manage and delete my account). This page is for the stories that add
data belonging to a user: saved routes (US13, US14), "Leave by" plans
(US15–US17), multi-stop plans (US20, US21). The decisions themselves are in
`docs/decisions.md`.

## 1. Deleting an account deletes everything saved in it

US12's acceptance criterion: *after deletion, the user's saved routes and
plans no longer exist in the database.* Saved routes and plans do not exist
yet, so this is how it is handled.

**The delete already covers data added later.** "Delete my account"
(`accounts/views.py`, `delete_account`) calls `request.user.delete()`.
Django then deletes every row in every table that links to that user with
`on_delete=models.CASCADE`, in the same transaction. When a `SavedRoute`
model is added, deleting the account removes its routes with **no change to
the US12 code**.

**Your model has to use CASCADE.** `on_delete` is set on *your* model's link
to the user, not on the user, so only your story can set it:

```python
from django.conf import settings
from django.db import models


class SavedRoute(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,  # required: deleting the account deletes the route
        related_name="saved_routes",
    )
    ...
```

**A check enforces it.** `accounts/checks.py` registers the Django system
check `accounts.E001`. Any `ForeignKey` or `OneToOneField` to the user
without `on_delete=models.CASCADE` (for example `SET_NULL`, `PROTECT`,
`DO_NOTHING`) is an error. It runs:

- in the test suite, so the Travis build fails;
- on `python manage.py check` and `runserver`;
- on `migrate`, so also during the Elastic Beanstalk deploy.

The error looks like this:

```
ERRORS:
routes.SavedRoute.user: (accounts.E001) SavedRoute.user links to the user without on_delete=models.CASCADE.
	HINT: Deleting an account must delete everything saved in it (US12 #41). Use on_delete=models.CASCADE.
```

**Add one test in your story.** The check proves the rule, but the
acceptance criterion can only be *shown* once your table exists. Add a test
like this to your story's tests:

```python
def test_deleting_the_user_deletes_their_saved_routes(self):
    user = User.objects.create_user("alex@example.com", "alex@example.com", "x")
    SavedRoute.objects.create(user=user, ...)

    user.delete()

    self.assertFalse(SavedRoute.objects.exists())
```

## 2. Pages that need an account

Use `@login_required` (or `LoginRequiredMixin` for class-based views). A
guest goes to `/accounts/signin/?next=<your page>` and comes back after
signing in (US11). Example: `accounts.views.AccountView`, the My account page.

```python
from django.contrib.auth.decorators import login_required


@login_required
def my_routes(request):
    routes = request.user.saved_routes.all()  # only this user's routes
    ...
```

Always filter by `request.user`, so a user can never see or change another
user's routes or plans (for example, look up a route with
`get_object_or_404(SavedRoute, pk=pk, user=request.user)`).

## 3. Every form needs a CSRF token

Put `{% csrf_token %}` in every `<form method="post">`. A test
(`accounts/tests/test_signin.py`, `CsrfTests`) fails the build if any
`method="post"` form in any template is missing it. Do not use
`@csrf_exempt`.

For JavaScript `fetch()` POSTs (for example a "Save route" button on the
map), send the token in the `X-CSRFToken` header.

## 4. Still open (see `docs/decisions.md`)

- **HTTPS** on the Integration and Production environments. Both are plain
  `http://` today, so passwords travel unencrypted. Needed before real users
  sign up.
- **Password reset by email** ("Forgot password?"). Needs an email service
  on AWS (for example Amazon SES). Until then, a user who forgets their
  password cannot get back in.
