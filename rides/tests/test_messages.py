"""US36 #98: Message Riders About a Shared Ride."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.urls import reverse

from accounts.models import Profile
from rides import messaging
from rides.forms import MESSAGE_EMPTY, MESSAGE_TOO_LONG
from rides.models import RideInterest, RideMessage, RidePost

from .test_show_interest import NOW, PASSWORD, TOMORROW, InterestTestData, at


class MessageTestData(InterestTestData):
    """self.owner posts; self.rider (Night Owl) shows interest; the owner is
    Early Bird. The client starts signed in as self.rider."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        users = get_user_model().objects
        cls.stranger = users.create_user("stranger@example.com", password=PASSWORD)
        Profile.objects.create(user=cls.stranger, display_name="Stranger")
        cls.rider2 = users.create_user("r2@example.com", password=PASSWORD)
        Profile.objects.create(user=cls.rider2, display_name="Second Rider")

    def setUp(self):
        super().setUp()
        self.ride = self.post(seats=2)
        self.rider_interest = self.interest(self.ride)

    def url(self, post=None, rider=None):
        post = post or self.ride
        rider = rider or self.rider
        return reverse("rides:conversation", args=[post.pk, rider.pk])

    def poll_url(self, post=None, rider=None, after=None):
        post = post or self.ride
        rider = rider or self.rider
        url = reverse("rides:conversation_updates", args=[post.pk, rider.pk])
        return url if after is None else f"{url}?after={after}"

    def send(self, text, post=None, rider=None):
        return self.client.post(self.url(post, rider), {"text": text})

    def message(self, sender, receiver, text="Hi", post=None):
        return RideMessage.objects.create(
            post=post or self.ride, sender=sender, receiver=receiver, text=text
        )


class SendAndReadTests(MessageTestData):
    """The owner and an interested rider can send each other messages."""

    def test_rider_messages_the_owner(self):
        response = self.send("  Meet by the info desk?  ")
        self.assertRedirects(
            response, self.url() + "#latest", fetch_redirect_response=False
        )
        message = RideMessage.objects.get()
        self.assertEqual(message.sender, self.rider)
        self.assertEqual(message.receiver, self.owner)
        self.assertEqual(message.text, "Meet by the info desk?")
        self.assertEqual(message.sent_at, NOW)
        self.assertIsNone(message.read_at)

    def test_owner_replies_to_the_rider(self):
        self.client.force_login(self.owner)
        self.send("Sure, see you there")
        message = RideMessage.objects.get()
        self.assertEqual(message.sender, self.owner)
        self.assertEqual(message.receiver, self.rider)

    def test_page_shows_messages_oldest_first_with_names(self):
        self.message(self.rider, self.owner, "first")
        self.message(self.owner, self.rider, "second")
        response = self.client.get(self.url())
        self.assertContains(response, "Messages with Early Bird")
        body = response.content.decode()
        self.assertLess(body.index("first"), body.index("second"))
        self.assertContains(response, 'class="chat-row mine"')
        self.assertContains(response, 'class="chat-row theirs"')
        self.assertContains(response, "You:")
        self.assertContains(response, "Early Bird:")

    def test_page_has_the_safety_reminder_and_the_polling_script(self):
        response = self.client.get(self.url())
        self.assertContains(response, "Don't share addresses or phone numbers.")
        self.assertContains(response, "Meet in a public place.")
        self.assertContains(response, "rides/js/conversation.js")
        self.assertContains(response, 'data-poll-ms="15000"')

    def test_messages_are_escaped(self):
        self.message(self.owner, self.rider, "<script>alert(1)</script>")
        response = self.client.get(self.url())
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;")

    def test_opening_the_page_marks_received_messages_read(self):
        to_me = self.message(self.owner, self.rider, "to me")
        from_me = self.message(self.rider, self.owner, "from me")
        self.client.get(self.url())
        to_me.refresh_from_db()
        from_me.refresh_from_db()
        self.assertEqual(to_me.read_at, NOW)
        self.assertIsNone(from_me.read_at)

    def test_conversations_with_different_riders_are_separate(self):
        self.interest(self.ride, rider=self.rider2)
        self.message(self.rider2, self.owner, "from the second rider")
        self.client.force_login(self.owner)
        response = self.client.get(self.url())
        self.assertNotContains(response, "from the second rider")

    def test_no_email_address_on_the_page_or_in_json(self):
        self.message(self.owner, self.rider, "hello")
        for url in (self.url(), self.poll_url()):
            with self.subTest(url=url):
                self.assertNotContains(self.client.get(url), "@example.com")

    def test_message_label_has_no_text_or_email(self):
        message = self.message(self.rider, self.owner, "private words")
        self.assertEqual(str(message), f"Message {message.pk} on post {self.ride.pk}")

    def test_post_page_links_both_sides_to_the_conversation(self):
        response = self.client.get(self.detail(self.ride))
        self.assertContains(response, f'href="{self.url()}"')
        self.client.force_login(self.owner)
        response = self.client.get(self.detail(self.ride))
        self.assertContains(response, f'href="{self.url()}"')
        self.assertContains(response, "Messages with Night Owl")


class AccessTests(MessageTestData):
    """Nobody else can open the conversation (they get 404)."""

    def assert_404_everywhere(self, post=None, rider=None):
        for response in (
            self.client.get(self.url(post, rider)),
            self.send("hi", post, rider),
            self.client.get(self.poll_url(post, rider)),
        ):
            self.assertEqual(response.status_code, 404)
        self.assertFalse(RideMessage.objects.exists())

    def test_another_rider_gets_404(self):
        self.client.force_login(self.stranger)
        self.assert_404_everywhere()

    def test_an_interested_rider_cannot_open_another_riders_conversation(self):
        self.interest(self.ride, rider=self.rider2)
        self.client.force_login(self.rider2)
        self.assert_404_everywhere()

    def test_the_owner_cannot_message_themselves(self):
        self.client.force_login(self.owner)
        self.assert_404_everywhere(rider=self.owner)

    def test_no_conversation_without_interest(self):
        self.client.force_login(self.owner)
        self.assert_404_everywhere(rider=self.stranger)
        self.client.force_login(self.stranger)
        self.assert_404_everywhere(rider=self.stranger)

    def test_unknown_post_or_rider_gets_404(self):
        self.assertEqual(
            self.client.get(
                reverse("rides:conversation", args=[999999, self.rider.pk])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("rides:conversation", args=[self.ride.pk, 999999])
            ).status_code,
            404,
        )

    def test_guests_are_sent_to_sign_in(self):
        self.client.logout()
        for url in (self.url(), self.poll_url()):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("accounts:signin"), response["Location"])

    def test_a_rider_without_a_display_name_chooses_one_first(self):
        Profile.objects.filter(user=self.rider).delete()
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:display_name"), response["Location"])


class ValidationTests(MessageTestData):
    """Empty and over-length messages are rejected."""

    def test_empty_and_blank_messages_are_rejected(self):
        for text in ("", "   \n  "):
            with self.subTest(text=text):
                response = self.send(text)
                self.assertContains(response, MESSAGE_EMPTY)
        self.assertFalse(RideMessage.objects.exists())

    def test_over_500_characters_is_rejected(self):
        response = self.send("x" * 501)
        self.assertContains(response, MESSAGE_TOO_LONG)
        self.assertFalse(RideMessage.objects.exists())

    def test_exactly_500_characters_is_fine(self):
        self.send("x" * 500)
        self.assertEqual(RideMessage.objects.get().text, "x" * 500)

    def test_the_database_refuses_empty_and_self_messages(self):
        for fields in (
            {"sender": self.rider, "receiver": self.owner, "text": ""},
            {"sender": self.rider, "receiver": self.rider, "text": "hi"},
        ):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    RideMessage.objects.create(post=self.ride, **fields)

    def test_get_only_on_the_polling_endpoint(self):
        response = self.client.post(self.poll_url())
        self.assertEqual(response.status_code, 405)


class PollingTests(MessageTestData):
    """New messages appear within 15 seconds without reloading the page."""

    def test_returns_only_newer_messages(self):
        old = self.message(self.owner, self.rider, "old")
        self.message(self.owner, self.rider, "new")
        data = self.client.get(self.poll_url(after=old.pk)).json()
        self.assertEqual([m["text"] for m in data["messages"]], ["new"])
        self.assertIsNone(data["read_only"])

    def test_message_fields(self):
        mine = self.message(self.rider, self.owner, "mine")
        theirs = self.message(self.owner, self.rider, "theirs")
        data = self.client.get(self.poll_url(after=0)).json()
        self.assertEqual(
            data["messages"],
            [
                {
                    "id": mine.pk,
                    "mine": True,
                    "sender": "You",
                    "text": "mine",
                    "sent_at": "Wed 11 Nov, 8:00 AM",
                },
                {
                    "id": theirs.pk,
                    "mine": False,
                    "sender": "Early Bird",
                    "text": "theirs",
                    "sent_at": "Wed 11 Nov, 8:00 AM",
                },
            ],
        )

    def test_a_bad_after_value_returns_everything(self):
        self.message(self.owner, self.rider, "hi")
        for after in ("abc", "-5"):
            with self.subTest(after=after):
                data = self.client.get(self.poll_url(after=after)).json()
                self.assertEqual(len(data["messages"]), 1)

    def test_polling_marks_new_received_messages_read(self):
        message = self.message(self.owner, self.rider, "hi")
        self.client.get(self.poll_url(after=0))
        message.refresh_from_db()
        self.assertEqual(message.read_at, NOW)


class ReadOnlyTests(MessageTestData):
    """After the time limit, the conversation is read-only."""

    def assert_read_only(self, reason, rider=None):
        response = self.client.get(self.url(rider=rider))
        self.assertContains(response, reason.replace("'", "&#x27;"))
        self.assertNotContains(response, 'id="conversation-form"')
        response = self.send("still there?", rider=rider)
        self.assertContains(response, reason.replace("'", "&#x27;"))
        self.assertEqual(
            self.client.get(self.poll_url(rider=rider)).json()["read_only"], reason
        )

    def test_still_open_just_before_24_hours_after_departure(self):
        RidePost.objects.filter(pk=self.ride.pk).update(
            departure_at=NOW - timedelta(hours=23, minutes=45)
        )
        self.send("Thanks for the ride")
        self.assertTrue(RideMessage.objects.exists())

    def test_read_only_24_hours_after_departure(self):
        RidePost.objects.filter(pk=self.ride.pk).update(
            departure_at=NOW - timedelta(hours=24)
        )
        self.message(self.owner, self.rider, "earlier message")
        self.assert_read_only(messaging.DEPARTED)
        self.assertContains(self.client.get(self.url()), "earlier message")
        self.assertEqual(RideMessage.objects.count(), 1)

    def test_read_only_when_the_post_is_deleted(self):
        RidePost.objects.filter(pk=self.ride.pk).update(status=RidePost.DELETED)
        self.message(self.owner, self.rider, "earlier message")
        self.assert_read_only(messaging.DELETED)
        self.assertNotContains(self.client.get(self.url()), "View ride")
        self.assertEqual(RideMessage.objects.count(), 1)

    def test_read_only_when_the_owner_declined_the_rider(self):
        self.rider_interest.status = RideInterest.DECLINED
        self.rider_interest.save()
        self.assert_read_only(messaging.DECLINED)

    def test_withdrawn_rider_keeps_earlier_messages_read_only(self):
        self.message(self.owner, self.rider, "earlier message")
        self.rider_interest.delete()
        self.assert_read_only(messaging.WITHDRAWN)

    def test_closed_post_can_still_be_messaged(self):
        RidePost.objects.filter(pk=self.ride.pk).update(status=RidePost.CLOSED)
        self.send("Still on for tomorrow?")
        self.assertTrue(RideMessage.objects.exists())

    def test_deleted_ride_update_links_to_the_conversation(self):
        RidePost.objects.filter(pk=self.ride.pk).update(status=RidePost.DELETED)
        response = self.client.get(reverse("rides:find_rides"))
        self.assertContains(response, f'href="{self.url()}"')


class RateLimitTests(MessageTestData):
    """At most 30 messages per user per hour."""

    def fill(self, count, sent_at=NOW):
        RideMessage.objects.bulk_create(
            RideMessage(
                post=self.ride, sender=self.rider, receiver=self.owner, text="hi"
            )
            for _ in range(count)
        )
        RideMessage.objects.update(sent_at=sent_at)

    def test_31st_message_in_an_hour_is_refused(self):
        self.fill(messaging.MAX_PER_HOUR)
        response = self.send("one more")
        self.assertContains(response, "messages in the last hour")
        self.assertEqual(RideMessage.objects.count(), messaging.MAX_PER_HOUR)

    def test_30th_message_is_fine(self):
        self.fill(messaging.MAX_PER_HOUR - 1)
        self.send("the 30th")
        self.assertEqual(RideMessage.objects.count(), messaging.MAX_PER_HOUR)

    def test_messages_older_than_an_hour_do_not_count(self):
        self.fill(messaging.MAX_PER_HOUR, sent_at=NOW - timedelta(hours=1))
        self.send("a new hour")
        self.assertEqual(RideMessage.objects.count(), messaging.MAX_PER_HOUR + 1)

    def test_the_limit_counts_every_conversation(self):
        other = self.post(seats=1, departure=at(TOMORROW, 11))
        self.interest(other)
        self.fill(messaging.MAX_PER_HOUR)
        self.send("on another ride", post=other)
        self.assertFalse(RideMessage.objects.filter(post=other).exists())

    def test_the_other_person_is_not_limited_by_my_messages(self):
        self.fill(messaging.MAX_PER_HOUR)
        self.client.force_login(self.owner)
        self.send("I can still reply")
        self.assertTrue(RideMessage.objects.filter(sender=self.owner).exists())


class AccountDeletionTests(MessageTestData):
    """Deleting an account deletes the messages that user sent."""

    def test_deleting_the_sender_deletes_their_messages(self):
        self.message(self.rider, self.owner, "from the rider")
        kept = self.message(self.owner, self.rider2, "to someone else", post=self.ride)
        self.rider.delete()
        self.assertEqual(list(RideMessage.objects.all()), [kept])

    def test_deleting_the_post_row_deletes_its_messages(self):
        self.message(self.rider, self.owner)
        self.ride.delete()
        self.assertFalse(RideMessage.objects.exists())
