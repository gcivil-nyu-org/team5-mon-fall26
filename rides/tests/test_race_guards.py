"""Checks that run when a post changes between loading a page and saving it,
plus the report admin. Covers US34-US38 code paths the request tests can't reach."""

from datetime import timedelta
from unittest import mock

from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404 as real_get_object_or_404
from django.test import RequestFactory
from django.urls import reverse

from rides import reporting
from rides.admin import ContentReportAdmin
from rides.forms import (
    DEPARTURE_PAST,
    DEPARTURE_TOO_FAR,
    EDIT_UNAVAILABLE,
    TOO_FEW_SEATS,
    RidePostEditForm,
)
from rides.models import ContentReport, RideInterest, RideMessage, RidePost

from .test_show_interest import NOW, PASSWORD, TOMORROW, InterestTestData, at


class EditSaveRecheckTests(InterestTestData):
    """RidePostEditForm.save() rechecks under the row lock what clean() checked."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.rider2 = get_user_model().objects.create_user(
            "r2@example.com", password=PASSWORD
        )

    def valid_form(self, post, **overrides):
        data = {"departure_at": "2026-11-12T10:00", "seats": "2", "note": ""}
        data.update(overrides)
        form = RidePostEditForm(self.owner, data, instance=post)
        self.assertTrue(form.is_valid(), form.errors)
        return form

    def test_post_closed_meanwhile_is_not_saved(self):
        post = self.post()
        form = self.valid_form(post)
        RidePost.objects.filter(pk=post.pk).update(status=RidePost.CLOSED)
        self.assertIsNone(form.save())
        self.assertIn(EDIT_UNAVAILABLE, form.non_field_errors())
        post.refresh_from_db()
        self.assertEqual(post.status, RidePost.CLOSED)

    def test_new_departure_passed_meanwhile_is_not_saved(self):
        post = self.post(departure=at(TOMORROW, 12))
        form = self.valid_form(post)  # 10:00 tomorrow
        with mock.patch("django.utils.timezone.now", return_value=at(TOMORROW, 11)):
            self.assertIsNone(form.save())
        self.assertEqual(form.errors["departure_at"], [DEPARTURE_PAST])
        post.refresh_from_db()
        self.assertEqual(post.departure_at, at(TOMORROW, 12))

    def test_new_departure_too_far_by_save_time_is_not_saved(self):
        post = self.post()
        far = (NOW + timedelta(days=13)).strftime("%Y-%m-%dT10:00")
        form = self.valid_form(post, departure_at=far)
        with mock.patch(
            "django.utils.timezone.now", return_value=NOW - timedelta(days=2)
        ):
            self.assertIsNone(form.save())
        self.assertEqual(form.errors["departure_at"], [DEPARTURE_TOO_FAR])

    def test_rider_accepted_meanwhile_keeps_seats_from_dropping_too_low(self):
        post = self.post(seats=2)
        self.interest(post, status=RideInterest.ACCEPTED)
        form = self.valid_form(post, seats="1")
        RideInterest.objects.create(
            post=post, rider=self.rider2, status=RideInterest.ACCEPTED
        )
        self.assertIsNone(form.save())
        self.assertEqual(form.errors["seats"], [TOO_FEW_SEATS])
        post.refresh_from_db()
        self.assertEqual(post.seats, 2)


class OwnerViewRecheckTests(InterestTestData):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner)

    def test_edit_page_shows_the_current_values(self):
        post = self.post(seats=3, note="Blue door")
        r = self.client.get(reverse("rides:edit_ride", args=[post.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["form"].instance, post)
        self.assertContains(r, "Blue door")

    def test_closing_a_deleted_post_is_404(self):
        post = self.post(status=RidePost.DELETED)
        r = self.client.post(reverse("rides:close_ride", args=[post.pk]))
        self.assertEqual(r.status_code, 404)
        post.refresh_from_db()
        self.assertEqual(post.status, RidePost.DELETED)

    def test_delete_page_for_a_deleted_post_is_404(self):
        post = self.post(status=RidePost.DELETED)
        r = self.client.get(reverse("rides:delete_ride", args=[post.pk]))
        self.assertEqual(r.status_code, 404)

    def test_post_deleted_in_another_tab_meanwhile_is_404(self):
        post = self.post()
        calls = []

        def deleted_after_first_load(*args, **kwargs):
            obj = real_get_object_or_404(*args, **kwargs)
            if not calls:  # the other tab deletes it right after this page loads
                RidePost.objects.filter(pk=obj.pk).update(status=RidePost.DELETED)
            calls.append(obj)
            return obj

        with mock.patch(
            "rides.views.get_object_or_404", side_effect=deleted_after_first_load
        ):
            r = self.client.post(reverse("rides:delete_ride", args=[post.pk]))
        self.assertEqual(r.status_code, 404)
        self.assertEqual(len(calls), 2)


class ReportRaceTests(InterestTestData):
    def test_second_report_sent_at_the_same_moment_is_refused(self):
        post = self.post()
        self.assertTrue(reporting.report(self.rider, "spam", "", post=post))
        # The page check passed for both requests; the unique index stops the second.
        self.assertFalse(reporting.report(self.rider, "unsafe", "", post=post))
        self.assertEqual(ContentReport.objects.count(), 1)


class ReportAdminTests(InterestTestData):
    def setUp(self):
        super().setUp()
        self.admin = ContentReportAdmin(ContentReport, site)
        self.ride = self.post(note="Meet at the blue door")
        self.message = RideMessage.objects.create(
            post=self.ride, sender=self.owner, receiver=self.rider, text="Pay me first"
        )

    def test_current_content_shows_the_message_or_the_post_as_it_is_now(self):
        on_message = ContentReport.objects.create(
            reporter=self.rider, message=self.message, reason="spam"
        )
        on_post = ContentReport.objects.create(
            reporter=self.rider, post=self.ride, reason="unsafe"
        )
        self.assertEqual(self.admin.current_content(on_message), "Pay me first")
        self.assertIn(
            "Note: Meet at the blue door", self.admin.current_content(on_post)
        )

    def test_mark_closed_and_mark_open_actions(self):
        ContentReport.objects.create(reporter=self.rider, post=self.ride, reason="spam")
        request = RequestFactory().post("/")
        self.admin.mark_closed(request, ContentReport.objects.all())
        self.assertEqual(ContentReport.objects.get().status, ContentReport.CLOSED)
        self.admin.mark_open(request, ContentReport.objects.all())
        self.assertEqual(ContentReport.objects.get().status, ContentReport.OPEN)
