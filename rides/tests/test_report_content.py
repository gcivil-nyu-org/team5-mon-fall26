"""US38 #101: Report a Post or Message."""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile
from rides import interest, messaging, reporting
from rides.models import ContentReport, RideMessage, RidePost

from .test_show_interest import PASSWORD, InterestTestData


class ReportTestData(InterestTestData):
    """self.owner (Early Bird) posts; self.rider (Night Owl) is interested
    and is the client's signed-in user. The owner sent the rider a message."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        users = get_user_model().objects
        cls.stranger = users.create_user("stranger@example.com", password=PASSWORD)
        Profile.objects.create(user=cls.stranger, display_name="Stranger")

    def setUp(self):
        super().setUp()
        self.ride = self.post(note="Meet at the blue door")
        self.interest(self.ride)
        self.to_rider = RideMessage.objects.create(
            post=self.ride, sender=self.owner, receiver=self.rider, text="Pay me first"
        )
        self.to_owner = RideMessage.objects.create(
            post=self.ride, sender=self.rider, receiver=self.owner, text="Sure"
        )

    def post_url(self, post=None):
        return reverse("rides:report_post", args=[(post or self.ride).pk])

    def message_url(self, message=None):
        return reverse("rides:report_message", args=[(message or self.to_rider).pk])

    def chat(self):
        return reverse("rides:conversation", args=[self.ride.pk, self.rider.pk])

    def report_post(self, post=None, **data):
        return self.client.post(self.post_url(post), {"reason": "unsafe", **data})

    def report_message(self, message=None, **data):
        return self.client.post(self.message_url(message), {"reason": "spam", **data})


class ReportPostTests(ReportTestData):
    def test_rider_reports_a_post_with_a_reason(self):
        page = self.client.get(self.post_url())
        self.assertContains(page, "Report this post")
        self.assertContains(page, "Meet at the blue door")
        self.assertContains(page, "csrfmiddlewaretoken")

        response = self.report_post(note="Asked for my home address")
        self.assertRedirects(response, self.detail(self.ride))
        self.assertEqual(self.messages(response), [reporting.THANKS])
        report = ContentReport.objects.get()
        self.assertEqual(
            (report.reporter, report.post, report.message, report.reason),
            (self.rider, self.ride, None, ContentReport.UNSAFE),
        )
        self.assertEqual(report.note, "Asked for my home address")
        self.assertEqual(report.status, ContentReport.OPEN)
        self.assertIn("Meet at the blue door", report.reported_text)
        self.assertEqual(report.reported_user, self.owner)

    def test_post_page_has_a_report_link_for_other_riders_only(self):
        link = f'href="{self.post_url()}"'
        self.assertContains(self.client.get(self.detail(self.ride)), link)
        self.client.force_login(self.owner)
        self.assertNotContains(self.client.get(self.detail(self.ride)), link)

    def test_cannot_report_own_post(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.post_url()).status_code, 404)
        self.assertEqual(self.report_post().status_code, 404)
        self.assertFalse(ContentReport.objects.exists())

    def test_cannot_report_a_post_they_cannot_see(self):
        closed = self.post(status=RidePost.CLOSED)
        deleted = self.post(status=RidePost.DELETED)
        for post in (closed, deleted):
            with self.subTest(status=post.status):
                self.assertEqual(self.report_post(post).status_code, 404)
        self.assertFalse(ContentReport.objects.exists())

    def test_any_rider_can_report_an_open_post(self):
        self.client.force_login(self.stranger)
        self.report_post(reason="offensive")
        self.assertEqual(ContentReport.objects.get().reporter, self.stranger)


class ReportMessageTests(ReportTestData):
    def test_receiver_reports_a_message(self):
        page = self.client.get(self.message_url())
        self.assertContains(page, "Report this message")
        self.assertContains(page, "Pay me first")

        response = self.report_message()
        self.assertRedirects(response, self.chat(), fetch_redirect_response=False)
        report = ContentReport.objects.get()
        self.assertEqual(
            (report.message, report.post, report.reason, report.reported_text),
            (self.to_rider, None, ContentReport.SPAM, "Pay me first"),
        )
        self.assertEqual(report.reported_user, self.owner)

    def test_owner_reports_a_message_and_returns_to_the_conversation(self):
        self.client.force_login(self.owner)
        response = self.report_message(self.to_owner)
        self.assertRedirects(response, self.chat(), fetch_redirect_response=False)
        self.assertEqual(ContentReport.objects.get().reported_user, self.rider)

    def test_each_received_message_has_a_report_link(self):
        response = self.client.get(self.chat())
        self.assertContains(response, f'href="{self.message_url()}"')
        self.assertNotContains(response, f'href="{self.message_url(self.to_owner)}"')
        self.assertContains(
            response, f'data-report-url="{reverse("rides:report_message", args=[0])}"'
        )

    def test_cannot_report_own_message(self):
        response = self.report_message(self.to_owner)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(ContentReport.objects.exists())

    def test_cannot_report_other_riders_messages(self):
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(self.message_url()).status_code, 404)
        self.assertEqual(self.report_message().status_code, 404)


class OncePerItemTests(ReportTestData):
    def test_second_report_of_the_same_post_is_refused(self):
        self.report_post()
        page = self.client.get(self.post_url())
        self.assertContains(page, "already reported this")
        self.assertNotContains(page, "Send report")
        response = self.report_post(reason="spam")
        self.assertEqual(self.messages(response), [reporting.ALREADY])
        self.assertEqual(ContentReport.objects.count(), 1)

    def test_second_report_of_the_same_message_is_refused(self):
        self.report_message()
        self.report_message(reason="offensive")
        self.assertEqual(ContentReport.objects.count(), 1)
        self.assertContains(
            self.client.get(self.message_url()), "already reported this"
        )

    def test_reported_items_say_so_to_the_reporter(self):
        self.report_post()
        self.report_message()
        self.assertContains(
            self.client.get(self.detail(self.ride)), "You reported this post."
        )
        chat = self.client.get(self.chat())
        self.assertContains(
            chat, '<span class="chat-report">Reported</span>', html=True
        )
        self.assertNotContains(chat, f'href="{self.message_url()}"')

    def test_other_riders_can_still_report_it(self):
        self.report_post()
        self.client.force_login(self.stranger)
        self.report_post()
        self.assertEqual(ContentReport.objects.count(), 2)

    def test_database_allows_one_report_per_user_per_item(self):
        ContentReport.objects.create(reporter=self.rider, post=self.ride, reason="spam")
        with self.assertRaises(IntegrityError), transaction.atomic():
            ContentReport.objects.create(
                reporter=self.rider, post=self.ride, reason="other"
            )
        ContentReport.objects.create(
            reporter=self.rider, message=self.to_rider, reason="spam"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ContentReport.objects.create(
                reporter=self.rider, message=self.to_rider, reason="other"
            )

    def test_report_is_for_exactly_one_post_or_message(self):
        for fields in ({}, {"post": self.ride, "message": self.to_rider}):
            with self.subTest(fields=list(fields)):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    ContentReport.objects.create(
                        reporter=self.rider, reason="spam", **fields
                    )


class ValidationTests(ReportTestData):
    def test_reason_is_required_and_must_be_one_of_the_four(self):
        for data in ({"reason": ""}, {"reason": "boring"}):
            with self.subTest(data=data):
                response = self.client.post(self.post_url(), data)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors["reason"])
        self.assertFalse(ContentReport.objects.exists())

    def test_all_four_reasons_are_offered(self):
        page = self.client.get(self.post_url())
        for value, label in ContentReport.REASON_CHOICES:
            with self.subTest(reason=value):
                self.assertContains(page, f'value="{value}"')
                self.assertContains(page, label)

    def test_note_is_optional_and_at_most_300_characters(self):
        response = self.report_post(note="x" * 301)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors["note"])
        self.report_post(note="x" * 300)
        self.assertEqual(len(ContentReport.objects.get().note), 300)

    def test_guest_is_sent_to_sign_in(self):
        self.client.logout()
        response = self.report_post()
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:signin"), response.url)
        self.assertFalse(ContentReport.objects.exists())


class PrivacyTests(ReportTestData):
    """The reported rider never sees who reported them."""

    def test_reported_owner_sees_nothing_about_the_report(self):
        self.report_post(note="Night Owl thinks this is unsafe")
        self.report_message()
        owner = (
            Client()
        )  # a separate browser, so the reporter's notices aren't carried over
        owner.force_login(self.owner)
        for url in (self.detail(self.ride), self.chat(), reverse("rides:my_rides")):
            with self.subTest(url=url):
                response = owner.get(url)
                self.assertNotContains(response, "reported")
                self.assertNotContains(response, "Reported")
                self.assertNotContains(response, "thinks this is unsafe")

    def test_deleting_the_reporters_account_deletes_their_reports(self):
        self.report_post()
        self.rider.delete()
        self.assertFalse(ContentReport.objects.exists())


class AdminTests(ReportTestData):
    def setUp(self):
        super().setUp()
        self.report_post(note="Asked for my address")
        self.report_message()
        admin_user = get_user_model().objects.create_superuser(
            "admin@example.com", "admin@example.com", PASSWORD
        )
        self.client.force_login(admin_user)

    def test_reports_are_listed_with_the_reported_content(self):
        response = self.client.get(reverse("admin:rides_contentreport_changelist"))
        self.assertContains(response, "Pay me first")
        self.assertContains(response, "Meet at the blue door")
        self.assertContains(response, "Unsafe")
        self.assertContains(response, "Spam")

    def test_filters_for_reason_and_status(self):
        url = reverse("admin:rides_contentreport_changelist")
        response = self.client.get(url, {"reason__exact": "spam"})
        self.assertEqual(response.context["cl"].result_count, 1)
        response = self.client.get(url, {"status__exact": "closed"})
        self.assertEqual(response.context["cl"].result_count, 0)

    def test_admin_closes_a_report_with_an_outcome(self):
        report = ContentReport.objects.get(post=self.ride)
        url = reverse("admin:rides_contentreport_change", args=[report.pk])
        page = self.client.get(url)
        self.assertContains(page, "Asked for my address")
        self.client.post(
            reverse("admin:rides_contentreport_changelist"),
            {"action": "no_action_needed", "_selected_action": report.pk},
        )
        report.refresh_from_db()
        self.assertEqual(report.status, ContentReport.CLOSED)
        self.assertEqual(report.outcome, ContentReport.NO_ACTION)
        self.assertEqual(report.closed_by, "admin@example.com")
        self.assertIsNotNone(report.closed_at)

    def test_removing_a_post_closes_all_reports_and_hides_its_page(self):
        second = ContentReport.objects.create(
            reporter=self.stranger, post=self.ride, reason=ContentReport.SPAM
        )
        report = ContentReport.objects.get(reporter=self.rider, post=self.ride)
        self.client.post(
            reverse("admin:rides_contentreport_changelist"),
            {"action": "remove_posts", "_selected_action": report.pk},
        )
        self.ride.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(self.ride.status, RidePost.REMOVED)
        self.assertEqual(self.ride.note, "")
        self.assertEqual(
            interest.blocked_reason(self.ride, self.rider, timezone.now()),
            interest.REMOVED,
        )
        conversation = messaging.conversation_for(
            self.rider, self.ride.pk, self.rider.pk
        )
        self.assertEqual(
            conversation.read_only_reason(timezone.now()), messaging.REMOVED
        )
        self.assertEqual(second.outcome, ContentReport.CONTENT_REMOVED)
        self.assertEqual(second.closed_by, "admin@example.com")
        self.client.force_login(self.rider)
        self.assertEqual(self.client.get(self.detail(self.ride)).status_code, 404)
        self.assertContains(
            self.client.get(reverse("rides:my_rides")), "Removed by a moderator"
        )

    def test_hiding_a_message_keeps_it_but_replaces_its_text(self):
        report = ContentReport.objects.get(message=self.to_rider)
        self.client.post(
            reverse("admin:rides_contentreport_changelist"),
            {"action": "hide_messages", "_selected_action": report.pk},
        )
        self.to_rider.refresh_from_db()
        self.assertTrue(self.to_rider.hidden)
        self.assertEqual(self.to_rider.text, "Pay me first")
        self.client.force_login(self.rider)
        page = self.client.get(self.chat())
        self.assertContains(page, "This message was removed by a moderator")
        self.assertNotContains(page, "Pay me first")
        self.assertEqual(self.client.get(self.message_url()).status_code, 404)
        updates = self.client.get(
            reverse("rides:conversation_updates", args=[self.ride.pk, self.rider.pk]),
            {"after": self.to_rider.pk},
        ).json()
        self.assertIn(self.to_rider.pk, updates["hidden_ids"])
