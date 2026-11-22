"""
URL configuration for taxiscope project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import include, path

from zones.dashboard import data_quality

urlpatterns = [
    # US48 #122: staff only (admin_view sends anyone else to the admin sign-in).
    path(
        "admin/data-quality/",
        admin.site.admin_view(data_quality),
        name="data_quality",
    ),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("", include("routes.urls")),
    path("", include("reports.urls")),
    path("", include("rides.urls")),
    path("", include("zones.urls")),
]
