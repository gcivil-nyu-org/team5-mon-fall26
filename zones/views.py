from django.shortcuts import render


def map_view(request):
    """The main page: a Leaflet map of NYC. No zone data yet -- that
    is wired up in the US1 story via GET /api/zones."""
    return render(request, "zones/map.html")
