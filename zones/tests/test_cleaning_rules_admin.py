"""US41 #115: staff change the cleaning limits in the admin; bad values are
refused with a message; every change shows who made it and when. (Guests
and riders are refused on every admin URL by
accounts/tests/test_admin_access.py.)"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from zones.models import (
    FARE_OVER_CAP,
    NEGATIVE,
    STARTING_VALUES,
    CleaningRules,
    CleaningRulesChange,
    ImportRun,
)

PASSWORD = "taxi-route-7319"
CHANGELIST = reverse("admin:zones_cleaningrules_changelist")
TAXI = ImportRun.Dataset.TAXI
RIDESHARE = ImportRun.Dataset.RIDESHARE


def change_url(rules):
    return reverse("admin:zones_cleaningrules_change", args=[rules.pk])


def form_data(for_dataset, **changes):
    """The change form as the admin posts it, starting from the record's
    starting values."""
    values = {**STARTING_VALUES[for_dataset], **changes}
    return {
        name: "" if value is None else str(value)
        for name, value in values.items()
        if for_dataset == RIDESHARE or "wait" not in name
    }


class CleaningRulesAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_superuser(
            "staff@example.com", "staff@example.com", PASSWORD
        )
        cls.taxi = CleaningRules.objects.get(dataset=TAXI)
        cls.rideshare = CleaningRules.objects.get(dataset=RIDESHARE)

    def setUp(self):
        self.client.force_login(self.staff)

    def save(self, rules, **changes):
        return self.client.post(change_url(rules), form_data(rules.dataset, **changes))

    def test_list_shows_both_imports_and_their_limits(self):
        response = self.client.get(CHANGELIST)

        self.assertContains(response, "Yellow taxi")
        self.assertContains(response, "Rideshare (Uber and Lyft)")
        self.assertContains(response, "more than 0.00, at most 100.00")
        self.assertContains(response, "1 to 180")
        self.assertContains(response, "0 to 60")
        self.assertContains(response, "Never (starting values)", count=2)

    def test_the_index_lists_cleaning_rules(self):
        self.assertContains(self.client.get(reverse("admin:index")), "Cleaning rules")

    def test_taxi_page_has_no_wait_limits_and_rideshare_has(self):
        taxi = self.client.get(change_url(self.taxi))
        rideshare = self.client.get(change_url(self.rideshare))

        self.assertContains(taxi, 'name="max_fare"')
        self.assertNotContains(taxi, 'name="min_wait_min"')
        self.assertContains(rideshare, 'name="min_wait_min"')
        self.assertContains(rideshare, 'name="max_wait_min"')
        self.assertContains(taxi, "No changes yet: these are the starting values.")

    def test_staff_change_a_limit(self):
        response = self.save(self.taxi, max_fare="450.50", max_duration_min="120")

        self.assertRedirects(response, CHANGELIST)
        self.taxi.refresh_from_db()
        self.assertEqual(str(self.taxi.max_fare), "450.50")
        self.assertEqual(self.taxi.max_duration_min, 120)
        self.rideshare.refresh_from_db()
        self.assertEqual(str(self.rideshare.max_fare), "500.00")

    def test_a_change_records_who_and_when(self):
        before = timezone.now()
        self.save(self.taxi, max_fare="450")

        change = CleaningRulesChange.objects.get()
        self.assertEqual(change.rules, self.taxi)
        self.assertEqual(change.changed_by, "staff@example.com")
        self.assertGreaterEqual(change.changed_at, before)
        self.assertEqual(change.changes, {"max_fare": ["500.00", "450.00"]})
        self.assertTrue(
            str(change).startswith(
                "Yellow taxi cleaning rules changed by staff@example.com at "
            )
        )

    def test_the_page_shows_each_change(self):
        self.save(self.rideshare, max_fare="450")
        self.save(self.rideshare, max_fare="450", min_wait_min="1", max_wait_min="45")

        response = self.client.get(change_url(self.rideshare))
        # The header's "Welcome", "Last changed" and the 2 rows.
        self.assertContains(response, "staff@example.com", count=4)
        self.assertContains(response, "Maximum fare ($): 500.00 → 450.00")
        self.assertContains(
            response,
            "Minimum wait (minutes): 0 → 1; Maximum wait (minutes): 60 → 45",
        )
        changes = list(CleaningRulesChange.objects.values_list("changes", flat=True))
        self.assertEqual(len(changes), 2)
        self.assertIn("min_wait_min", changes[0])  # newest first

    def test_last_changed_is_on_the_list(self):
        self.save(self.taxi, min_distance_mi="0.1")
        change = CleaningRulesChange.objects.get()

        response = self.client.get(CHANGELIST)
        self.assertContains(
            response, f"{change.changed_at:%Y-%m-%d %H:%M} UTC by staff@example.com"
        )
        self.assertContains(response, "Never (starting values)", count=1)

    def test_saving_without_a_change_records_nothing(self):
        self.save(self.taxi)
        self.save(self.taxi, max_fare="500")  # 500 is 500.00

        self.assertFalse(CleaningRulesChange.objects.exists())

    def test_bad_values_are_refused_with_a_message(self):
        cases = (
            (
                {"min_distance_mi": "5", "max_distance_mi": "2"},
                "The maximum distance must be more than the minimum distance.",
            ),
            (
                {"min_duration_min": "200"},
                "The maximum duration must be more than the minimum duration.",
            ),
            (
                {"min_wait_min": "70"},
                "The maximum wait must be more than the minimum wait.",
            ),
            ({"min_duration_min": "-1"}, NEGATIVE),
            ({"max_fare": "600"}, FARE_OVER_CAP),
            ({"max_wait_min": ""}, "Enter both wait limits for rideshare data."),
        )
        for changes, message in cases:
            with self.subTest(changes):
                response = self.save(self.rideshare, **changes)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, message)
                self.rideshare.refresh_from_db()
                self.assertEqual(
                    self.rideshare.max_fare, STARTING_VALUES[RIDESHARE]["max_fare"]
                )
                self.assertEqual(self.rideshare.min_duration_min, 1)
                self.assertEqual(self.rideshare.min_wait_min, 0)
        self.assertFalse(CleaningRulesChange.objects.exists())

    def test_records_cannot_be_added_or_deleted(self):
        self.assertEqual(
            self.client.get(reverse("admin:zones_cleaningrules_add")).status_code, 403
        )
        delete = reverse("admin:zones_cleaningrules_delete", args=[self.taxi.pk])
        self.assertEqual(self.client.post(delete, {"post": "yes"}).status_code, 403)
        self.assertNotContains(self.client.get(CHANGELIST), "delete_selected")
        self.assertEqual(CleaningRules.objects.count(), 2)

    def test_the_dataset_cannot_be_changed(self):
        self.save(self.taxi, dataset=RIDESHARE)

        self.taxi.refresh_from_db()
        self.assertEqual(self.taxi.dataset, TAXI)

    def test_the_page_says_when_a_change_applies(self):
        self.assertContains(
            self.client.get(change_url(self.taxi)), "The next import uses the limits"
        )
