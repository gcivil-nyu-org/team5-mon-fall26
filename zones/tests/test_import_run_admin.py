"""US40 #114: staff view and filter the import history in the admin, newest
first, and nobody can add, change or delete it there. (Guests and riders
are refused on every admin URL by accounts/tests/test_admin_access.py.)"""

from datetime import timedelta

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from zones.admin import ImportRunAdmin, ReadOnlyModelAdmin
from zones.models import ImportRun

PASSWORD = "taxi-route-7319"
CHANGELIST = reverse("admin:zones_importrun_changelist")


def make_run(**fields):
    values = {
        "dataset": ImportRun.Dataset.TAXI,
        "months": ["2026-03"],
        "run_by": "po",
        "status": ImportRun.Status.SUCCEEDED,
        "started_at": timezone.now(),
        "min_trip_count": 5,
        "cleaning_limits": {"MAX_FARE_CENTS": 50_000},
        **fields,
    }
    return ImportRun.objects.create(**values)


class ImportRunAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.staff = User.objects.create_superuser(
            "staff@example.com", "staff@example.com", PASSWORD
        )
        cls.rider = User.objects.create_user(
            "rider@example.com", "rider@example.com", PASSWORD
        )
        now = timezone.now()
        cls.oldest = make_run(
            started_at=now - timedelta(days=2),
            finished_at=now - timedelta(days=2) + timedelta(seconds=95),
            rows_read=6,
            rows_removed=2,
            rows_kept=4,
            removed_by_rule={"bad_distance": 1, "pickup_outside_month": 1},
            zone_cells=3,
            route_cells=3,
            small_zone_cells=3,
            small_route_cells=3,
            zones_loaded=265,
            report="Months loaded: 2026-03\n\n  Rows read  6",
        )
        cls.failed = make_run(
            dataset=ImportRun.Dataset.RIDESHARE,
            status=ImportRun.Status.FAILED,
            started_at=now - timedelta(days=1),
            finished_at=now - timedelta(days=1),
            error="Cannot read data/raw/fhvhv_tripdata_2026-03.parquet: bad file",
        )
        cls.newest = make_run(
            dataset=ImportRun.Dataset.RIDESHARE,
            months=["2026-03", "2026-04", "2026-05"],
            started_at=now,
            rows_read=8,
            removed_by_rule={"shared_ride": 1, "retired_rule": 2},
            waits_left_out=1,
        )

    def setUp(self):
        self.client.force_login(self.staff)

    def results(self, response):
        return list(response.context["cl"].result_list)

    def test_history_is_registered_read_only(self):
        model_admin = admin.site._registry[ImportRun]

        self.assertIsInstance(model_admin, ImportRunAdmin)
        self.assertIsInstance(model_admin, ReadOnlyModelAdmin)

    def test_staff_see_the_history_on_the_admin_index(self):
        response = self.client.get(reverse("admin:index"))

        self.assertContains(response, "Import history")

    def test_list_is_newest_first(self):
        response = self.client.get(CHANGELIST)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.results(response), [self.newest, self.failed, self.oldest]
        )
        self.assertContains(response, "2026-03, 2026-04, 2026-05")
        self.assertContains(response, "Rideshare (Uber and Lyft)")
        self.assertContains(response, "1 min 35 s")

    def test_list_shows_the_start_of_the_error(self):
        response = self.client.get(CHANGELIST)

        self.assertContains(response, "Cannot read data/raw/fhvhv_tripdata_2026-03")

    def test_long_error_is_shortened_in_the_list_only(self):
        long_error = "RuntimeError: " + "x" * 200
        run = make_run(status=ImportRun.Status.FAILED, error=long_error)
        model_admin = admin.site._registry[ImportRun]

        self.assertEqual(model_admin.error_start(run), long_error[:80] + "…")
        detail = self.client.get(reverse("admin:zones_importrun_change", args=[run.pk]))
        self.assertContains(detail, long_error)

    def test_filter_by_dataset_and_status(self):
        taxi = self.client.get(CHANGELIST, {"dataset__exact": "taxi"})
        failed = self.client.get(CHANGELIST, {"status__exact": "failed"})
        both = self.client.get(
            CHANGELIST, {"dataset__exact": "rideshare", "status__exact": "succeeded"}
        )

        self.assertEqual(self.results(taxi), [self.oldest])
        self.assertEqual(self.results(failed), [self.failed])
        self.assertEqual(self.results(both), [self.newest])

    def test_detail_page_shows_the_numbers_limits_and_report(self):
        response = self.client.get(
            reverse("admin:zones_importrun_change", args=[self.oldest.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Distance &lt;= 0 or &gt; 100 miles")
        self.assertContains(response, "Pickup outside the file&#x27;s month")
        self.assertContains(response, "MAX_FARE_CENTS")
        self.assertContains(response, "<pre>Months loaded: 2026-03")
        self.assertContains(response, "265")
        self.assertNotContains(response, 'name="run_by"')

    def test_rideshare_detail_uses_rideshare_rule_labels(self):
        response = self.client.get(
            reverse("admin:zones_importrun_change", args=[self.newest.pk])
        )

        self.assertContains(response, "Shared ride (requested or matched)")
        # A rule key the code no longer has is still shown, by its key.
        self.assertContains(response, "retired_rule")
        page = response.content.decode()
        self.assertLess(page.index("Shared ride"), page.index("retired_rule"))

    def test_removed_rows_are_listed_in_rule_order(self):
        response = self.client.get(
            reverse("admin:zones_importrun_change", args=[self.oldest.pk])
        )

        page = response.content.decode()
        self.assertLess(page.index("Pickup outside"), page.index("Distance &lt;="))

    def test_failed_run_detail_shows_the_error(self):
        response = self.client.get(
            reverse("admin:zones_importrun_change", args=[self.failed.pk])
        )

        self.assertContains(response, "bad file")
        self.assertContains(response, "Failed")

    def test_cannot_add_a_run(self):
        response = self.client.get(reverse("admin:zones_importrun_add"))
        posted = self.client.post(
            reverse("admin:zones_importrun_add"),
            {"dataset": "taxi", "months": '["2026-03"]', "run_by": "x"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(posted.status_code, 403)
        self.assertEqual(ImportRun.objects.count(), 3)

    def test_cannot_change_a_run(self):
        url = reverse("admin:zones_importrun_change", args=[self.failed.pk])

        self.client.post(url, {"status": "succeeded", "error": "", "run_by": "x"})

        self.failed.refresh_from_db()
        self.assertEqual(self.failed.status, ImportRun.Status.FAILED)
        self.assertEqual(self.failed.run_by, "po")

    def test_cannot_delete_a_run(self):
        delete = self.client.post(
            reverse("admin:zones_importrun_delete", args=[self.oldest.pk]),
            {"post": "yes"},
        )
        bulk = self.client.post(
            CHANGELIST,
            {
                "action": "delete_selected",
                "_selected_action": [self.oldest.pk],
                "post": "yes",
            },
        )

        self.assertEqual(delete.status_code, 403)
        self.assertNotEqual(bulk.status_code, 500)
        self.assertEqual(ImportRun.objects.count(), 3)
        self.assertNotContains(self.client.get(CHANGELIST), "delete_selected")

    def test_riders_and_guests_cannot_see_the_history(self):
        self.client.force_login(self.rider)
        rider = self.client.get(CHANGELIST)
        self.client.logout()
        guest = self.client.get(CHANGELIST)

        for response in (rider, guest):
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response["Location"].startswith(reverse("admin:login")))

    def test_running_and_unfinished_runs_show_dashes(self):
        running = make_run(status=ImportRun.Status.RUNNING)
        model_admin = admin.site._registry[ImportRun]

        self.assertEqual(model_admin.duration_text(running), "-")
        self.assertEqual(model_admin.error_start(running), "-")
        self.assertEqual(model_admin.removed_table(running), "-")
        self.assertEqual(model_admin.report_text(running), "-")
