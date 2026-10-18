from django.test import SimpleTestCase

from zones.importer.read import read_zone_lookup


class ReadZoneLookupTests(SimpleTestCase):
    def setUp(self):
        self.lookup = read_zone_lookup()

    def test_has_every_zone_once(self):
        self.assertEqual(list(self.lookup.columns), ["zone_id", "name", "borough"])
        self.assertEqual(len(self.lookup), 265)
        self.assertEqual(sorted(self.lookup["zone_id"]), list(range(1, 266)))

    def test_zone_fields_are_read(self):
        row = self.lookup.set_index("zone_id").loc[1]

        self.assertEqual(row["name"], "Newark Airport")
        self.assertEqual(row["borough"], "EWR")

    def test_unknown_zones_keep_their_na_text(self):
        # pandas would read "N/A" as missing without keep_default_na=False.
        rows = self.lookup.set_index("zone_id")

        self.assertEqual(rows.loc[264, "name"], "N/A")
        self.assertEqual(rows.loc[264, "borough"], "Unknown")
        self.assertEqual(rows.loc[265, "name"], "Outside of NYC")
        self.assertEqual(rows.loc[265, "borough"], "N/A")
        self.assertFalse(self.lookup.isna().any().any())
