from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import SignInForm

app_name = "accounts"

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path(
        "signin/",
        auth_views.LoginView.as_view(
            template_name="accounts/signin.html",
            authentication_form=SignInForm,
            redirect_authenticated_user=True,
        ),
        name="signin",
    ),
    path("signout/", auth_views.LogoutView.as_view(), name="signout"),
    path("account/", views.AccountView.as_view(), name="account"),
]
