"""Staff moderation of reported ride content."""

from django.db import transaction
from django.utils import timezone

from .models import ContentReport, RideMessage, RidePost


def _close(reports, outcome, staff, now):
    return reports.filter(status=ContentReport.OPEN).update(
        status=ContentReport.CLOSED,
        outcome=outcome,
        closed_by=staff.get_username(),
        closed_at=now,
    )


def remove_posts(reports, staff):
    """Remove each selected post and close all open reports about it."""
    ids = set(reports.filter(post__isnull=False).values_list("post_id", flat=True))
    now = timezone.now()
    with transaction.atomic():
        posts = RidePost.objects.select_for_update().filter(pk__in=ids)
        changed = posts.exclude(status__in=[RidePost.DELETED, RidePost.REMOVED]).update(
            status=RidePost.REMOVED, note=""
        )
        _close(
            ContentReport.objects.filter(post_id__in=ids),
            ContentReport.CONTENT_REMOVED,
            staff,
            now,
        )
    return changed


def hide_messages(reports, staff):
    """Hide each selected message and close all open reports about it."""
    ids = set(
        reports.filter(message__isnull=False).values_list("message_id", flat=True)
    )
    now = timezone.now()
    with transaction.atomic():
        changed = (
            RideMessage.objects.select_for_update()
            .filter(pk__in=ids, hidden=False)
            .update(hidden=True)
        )
        _close(
            ContentReport.objects.filter(message_id__in=ids),
            ContentReport.CONTENT_REMOVED,
            staff,
            now,
        )
    return changed


def no_action(reports, staff):
    """Close selected reports while leaving their content in place."""
    return _close(reports, ContentReport.NO_ACTION, staff, timezone.now())
