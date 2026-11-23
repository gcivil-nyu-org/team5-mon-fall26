"""US48 #122: Data-Quality Dashboard."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from reports.models import FareReport
from rides.models import ContentReport, RidePost
from zones import dashboard
from zones.importer import rules
from zones.importer.clean import DEFAULT_LIMITS
from zones.models import ImportRun, RideshareZoneHourStats, Zone, ZoneHourStats

PASSWORD = "dashboard-test-password-48"
URL = reverse("data_quality")


def make_run(started, **fields):
    values = {
        "dataset": ImportRun.Dataset.TAXI,
        "months": ["2026-03"],
        "run_by": "po",
        "status": ImportRun.Status.SUCCEEDED,
        "started_at": started,
        "finished_at": started + timedelta(minutes=5),
        "min_trip_count": 5,
        "cleaning_limits": rules.saved_limits(DEFAULT_LIMITS),
        "rows_read": 1000,
        "rows_removed": 100,
        "rows_kept": 900,
        "removed_by_rule": {"voided": 50, "bad_distance": 50},
        "zone_cells": 200,
        "route_cells": 800,
        "small_zone_cells": 20,
        "small_route_cells": 230,
        "zones_loaded": 265,
        **fields,
    }
    return ImportRun.objects.create(**values)


class DashboardTestData(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.staff = users.create_superuser("staff@example.com", password=PASSWORD)
        cls.rider = users.create_user("rider@example.com", password=PASSWORD)
        cls.midtown = Zone.objects.create(
            zone_id=161, name="Midtown Center", borough="Manhattan"
        )
        cls.jfk = Zone.objects.create(zone_id=132, name="JFK Airport", borough="Queens")
        cls.empty = Zone.objects.create(zone_id=1, name="Newark Airport", borough="EWR")
        # Cleaning removes every trip in these two, so they never have trips.
        cls.unknown = Zone.objects.create(
            zone_id=264, name="Unknown", borough="Unknown"
        )
        cls.outside = Zone.objects.create(
            zone_id=265, name="Outside of NYC", borough="N/A"
        )

    def setUp(self):
        self.client.force_login(self.staff)
        self.now = timezone.now()

    def page(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        return response

    def section(self, response, dataset=ImportRun.Dataset.TAXI):
        return next(d for d in response.context["datasets"] if d.dataset == dataset)


class AccessTests(DashboardTestData):
    """Only staff can open the dashboard."""

    def test_url(self):
        self.assertEqual(URL, "/admin/data-quality/")

    def test_staff_can_open_it(self):
        self.assertContains(self.page(), "Data quality")

    def test_guests_and_riders_are_sent_to_the_admin_sign_in(self):
        self.client.logout()
        response = self.client.get(URL)
        self.assertRedirects(
            response,
            f"{reverse('admin:login')}?next={URL}",
            fetch_redirect_response=False,
        )
        self.client.force_login(self.rider)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("admin:login")))
        self.assertNotIn(b"Rows read", response.content)

    def test_inactive_staff_are_refused(self):
        self.staff.is_active = False
        self.staff.save()
        self.assertEqual(self.client.get(URL).status_code, 302)

    def test_admin_home_links_to_it(self):
        home = self.client.get(reverse("admin:index"))
        self.assertContains(home, f'href="{URL}"')
        self.assertContains(home, "Data-quality dashboard")


class LatestImportTests(DashboardTestData):
    """Its numbers match the latest ImportRun records."""

    def setUp(self):
        super().setUp()
        self.previous = make_run(self.now - timedelta(days=30))
        self.latest = make_run(
            self.now - timedelta(days=1),
            months=["2026-04"],
            rows_read=2000,
            rows_removed=300,
            rows_kept=1700,
            removed_by_rule={"voided": 60, "bad_distance": 240},
            zone_cells=250,
            route_cells=750,
            small_zone_cells=25,
            small_route_cells=150,
        )

    def test_uses_the_latest_and_previous_successful_runs(self):
        taxi = self.section(self.page())
        self.assertEqual((taxi.latest, taxi.previous), (self.latest, self.previous))

    def test_rows_and_small_cells_match_the_record(self):
        response = self.page()
        taxi = self.section(response)
        self.assertEqual(taxi.kept_share, 85.0)  # 1700 / 2000
        self.assertEqual(taxi.removed_share, 15.0)
        self.assertEqual(taxi.previous_removed_share, 10.0)  # 100 / 1000
        self.assertEqual(taxi.small_cell_share, 17.5)  # (25 + 150) / (250 + 750)
        self.assertEqual(taxi.previous_small_cell_share, 25.0)  # 250 / 1000
        self.assertEqual(taxi.small_zone_share, 10.0)
        self.assertEqual(taxi.small_route_share, 20.0)
        self.assertContains(response, "2,000")
        self.assertContains(response, "1,700 (85.00%)")
        self.assertContains(
            response, '300 (15.00%) <span class="dq-note">(previous 10.00%)</span>'
        )
        self.assertContains(response, "17.50%")

    def test_rows_removed_by_each_rule_match_the_record(self):
        rows = {row.key: row for row in self.section(self.page()).rules}
        self.assertEqual(set(rows), {"voided", "bad_distance"})
        self.assertEqual((rows["voided"].removed, rows["voided"].share), (60, 3.0))
        self.assertEqual(rows["voided"].previous_share, 5.0)  # 50 / 1000
        self.assertEqual(rows["bad_distance"].removed, 240)
        self.assertEqual(rows["bad_distance"].share, 12.0)

    def test_rules_are_in_rule_order_with_the_runs_labels(self):
        rows = self.section(self.page()).rules
        labels = dict(rules.rules_for(ImportRun.Dataset.TAXI, DEFAULT_LIMITS))
        self.assertEqual([r.key for r in rows], ["voided", "bad_distance"])
        self.assertEqual(rows[1].label, labels["bad_distance"])

    def test_a_newer_failed_run_is_ignored_but_mentioned(self):
        failed = make_run(
            self.now,
            status=ImportRun.Status.FAILED,
            rows_read=None,
            removed_by_rule=None,
            error="boom",
        )
        response = self.page()
        taxi = self.section(response)
        self.assertEqual(taxi.latest, self.latest)
        self.assertTrue(taxi.last_attempt_failed)
        self.assertContains(response, f"#{failed.pk}</a>, is failed")

    def test_the_other_dataset_is_separate(self):
        rideshare = make_run(
            self.now - timedelta(days=2),
            dataset=ImportRun.Dataset.RIDESHARE,
            removed_by_rule={"bad_wait": 10},
            cleaning_limits={},
        )
        response = self.page()
        self.assertEqual(self.section(response, "rideshare").latest, rideshare)
        self.assertIsNone(self.section(response, "rideshare").previous)
        self.assertEqual(self.section(response).latest, self.latest)


class ChangeHighlightTests(DashboardTestData):
    """A change of more than 2 percentage points between imports is highlighted."""

    def rows(self, before, after):
        make_run(self.now - timedelta(days=30), removed_by_rule=before)
        make_run(self.now - timedelta(days=1), removed_by_rule=after)
        response = self.page()
        return response, {row.key: row for row in self.section(response).rules}

    def test_more_than_two_points_is_highlighted_both_ways(self):
        # rows_read is 1000 in both: 10 rows = 1 point.
        response, rows = self.rows(
            {"voided": 50, "bad_distance": 100, "bad_duration": 10},
            {"voided": 75, "bad_distance": 60, "bad_duration": 20},
        )
        self.assertAlmostEqual(rows["voided"].change, 2.5)
        self.assertTrue(rows["voided"].flagged)
        self.assertAlmostEqual(rows["bad_distance"].change, -4.0)
        self.assertTrue(rows["bad_distance"].flagged)
        self.assertAlmostEqual(rows["bad_duration"].change, 1.0)
        self.assertFalse(rows["bad_duration"].flagged)
        self.assertContains(response, '<tr class="dq-rule dq-flag" data-rule="voided">')
        self.assertContains(response, '<tr class="dq-rule" data-rule="bad_duration">')
        self.assertContains(
            response, "2 rules changed by more than 2 percentage points"
        )
        self.assertContains(response, "+2.50 pp")
        self.assertContains(response, "-4.00 pp")

    def test_exactly_two_points_is_not_highlighted(self):
        # 0.1 steps in floats: 7.3 - 5.3 is not exactly 2.
        make_run(
            self.now - timedelta(days=30),
            rows_read=1000,
            removed_by_rule={"voided": 53},
        )
        make_run(
            self.now - timedelta(days=1),
            rows_read=1000,
            removed_by_rule={"voided": 73},
        )
        row = self.section(self.page()).rules[0]
        self.assertAlmostEqual(row.change, 2.0)
        self.assertFalse(row.flagged)

    def test_compares_shares_not_counts(self):
        # Twice the rows and twice the removals: the same share, no highlight.
        make_run(
            self.now - timedelta(days=30),
            rows_read=1000,
            removed_by_rule={"voided": 100},
        )
        make_run(
            self.now - timedelta(days=1),
            rows_read=2000,
            removed_by_rule={"voided": 200},
        )
        row = self.section(self.page()).rules[0]
        self.assertEqual(row.change, 0)
        self.assertFalse(row.flagged)

    def test_a_rule_in_only_one_run_has_no_comparison(self):
        _, rows = self.rows({"voided": 50}, {"voided": 50, "bad_duration": 90})
        self.assertIsNone(rows["bad_duration"].previous_share)
        self.assertIsNone(rows["bad_duration"].change)
        self.assertFalse(rows["bad_duration"].flagged)

    def test_a_rule_that_removed_nothing_this_time(self):
        _, rows = self.rows({"voided": 50, "bad_distance": 40}, {"voided": 50})
        self.assertIsNone(rows["bad_distance"].removed)
        self.assertIsNone(rows["bad_distance"].change)

    def test_first_import_has_nothing_to_compare(self):
        make_run(self.now - timedelta(days=1))
        response = self.page()
        self.assertContains(response, "No earlier successful import to compare with.")
        self.assertIsNone(self.section(response).previous_removed_share)
        self.assertFalse(any(row.flagged for row in self.section(response).rules))


class EmptyAndZonesTests(DashboardTestData):
    def test_no_import_yet(self):
        response = self.page()
        self.assertContains(response, "No successful yellow taxi import yet.")
        self.assertContains(
            response, "No successful rideshare (uber and lyft) import yet."
        )

    def test_no_import_yet_but_a_failed_one(self):
        make_run(self.now, status=ImportRun.Status.FAILED, rows_read=None)
        self.assertContains(self.page(), "No successful yellow taxi import yet.")

    def stats(self, model, zone):
        fields = dict(
            zone=zone,
            day_of_week=0,
            hour=8,
            trip_count=12,
            avg_duration_min=14.0,
            fare_min=Decimal("10"),
            fare_avg=Decimal("20"),
            fare_max=Decimal("30"),
        )
        if model is RideshareZoneHourStats:
            fields.update(avg_wait_min=4.0, wait_count=12, fare_per_mile=Decimal("3"))
        model.objects.create(**fields)

    def test_zones_with_no_trips(self):
        make_run(self.now)
        make_run(
            self.now,
            dataset=ImportRun.Dataset.RIDESHARE,
            cleaning_limits={},
            removed_by_rule={},
        )
        self.stats(ZoneHourStats, self.midtown)
        self.stats(ZoneHourStats, self.jfk)
        self.stats(RideshareZoneHourStats, self.midtown)
        response = self.page()
        self.assertEqual(self.section(response).zones_without_trips, [self.empty])
        self.assertEqual(
            self.section(response, "rideshare").zones_without_trips,
            [self.empty, self.jfk],
        )
        self.assertContains(response, "1 Newark Airport (EWR)")
        self.assertNotContains(response, "264 Unknown")
        self.assertNotContains(response, "265 Outside of NYC")

    def test_every_zone_has_trips(self):
        make_run(self.now)
        for zone in (self.midtown, self.jfk, self.empty):
            self.stats(ZoneHourStats, zone)
        self.assertContains(self.page(), "Every zone has trips.")

    def test_no_rows_removed(self):
        make_run(self.now, removed_by_rule={}, rows_removed=0, rows_kept=1000)
        self.assertContains(self.page(), "No rows removed.")

    def test_shares_without_rows_or_cells(self):
        self.assertIsNone(dashboard.share(5, 0))
        self.assertIsNone(dashboard.share(None, 10))
        run = make_run(
            self.now,
            zone_cells=None,
            route_cells=None,
            small_zone_cells=None,
            small_route_cells=None,
        )
        self.assertIsNone(dashboard.small_cell_share(run))


class ReviewCountTests(DashboardTestData):
    """The held-report and open-report counts link to the right admin lists."""

    def setUp(self):
        super().setUp()
        post = RidePost.objects.create(
            owner=self.rider,
            pickup_zone=self.midtown,
            dropoff_zone=self.jfk,
            departure_at=self.now + timedelta(days=1),
            seats=2,
        )
        for status in (
            FareReport.HELD,
            FareReport.HELD,
            FareReport.VISIBLE,
            FareReport.REMOVED,
        ):
            FareReport.objects.create(
                user=self.rider,
                pickup_zone=self.midtown,
                dropoff_zone=self.jfk,
                ride_at=self.now - timedelta(days=1),
                taxi_fare=Decimal("20.00"),
                status=status,
            )
        ContentReport.objects.create(reporter=self.staff, post=post, reason="spam")
        ContentReport.objects.create(
            reporter=self.rider, post=post, reason="unsafe", status=ContentReport.CLOSED
        )

    def counts(self):
        return {c["label"]: c for c in self.page().context["review_counts"]}

    def test_counts(self):
        counts = self.counts()
        self.assertEqual(counts["Fare reports held for review"]["count"], 2)
        self.assertEqual(counts["Open content reports"]["count"], 1)

    def test_links_open_the_matching_admin_lists(self):
        counts = self.counts()
        for label, expected in (
            ("Fare reports held for review", 2),
            ("Open content reports", 1),
        ):
            with self.subTest(label=label):
                url = counts[label]["url"]
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["cl"].result_count, expected)
        self.assertTrue(
            counts["Fare reports held for review"]["url"].startswith(
                reverse("admin:reports_farereport_changelist")
            )
        )
        self.assertTrue(
            counts["Open content reports"]["url"].startswith(
                reverse("admin:rides_contentreport_changelist")
            )
        )

    def test_links_are_on_the_page(self):
        response = self.page()
        held = reverse("admin:reports_farereport_changelist") + "?status__exact=held"
        open_ = reverse("admin:rides_contentreport_changelist") + "?status__exact=open"
        self.assertContains(response, f'<a href="{held}">2</a>', html=True)
        self.assertContains(response, f'<a href="{open_}">1</a>', html=True)
