from .test_campaigns import CampaignTests, atlas, proposal
from .models import LineReview, ReviewEvent
from .review import is_current


class AutomaticTests(CampaignTests):
    def automatic(self, **changes):
        row = atlas()
        return self.load(inventory=[row], proposals=[proposal([row], rule="MATCH_EXACT",
            auto_validation={"source": "AUTO", "rule": "MATCH_EXACT", "state": "VALIDATED"}, **changes)])

    def test_automatic_lifecycle(self):
        first = self.automatic()
        line = LineReview.objects.get()
        self.assertEqual(line.state, "VALIDATED")
        self.assertEqual(line.validation_source, "AUTO")
        self.assertTrue(is_current(line))
        self.assertEqual(ReviewEvent.objects.count(), 1)
        self.automatic()
        self.assertEqual(ReviewEvent.objects.count(), 1)
        self.load()
        line.refresh_from_db()
        self.assertFalse(is_current(line))
        self.assertEqual(first.reviews.get().decision["validation_source"], "AUTO")

    def test_human_priority(self):
        self.automatic()
        self.validate(state="REJECTED")
        self.automatic()
        line = LineReview.objects.get()
        self.assertEqual(line.state, "REJECTED")
        self.assertEqual(line.validation_source, "MANUAL")

    def test_identical_file_is_idempotent(self):
        from .review_import import import_bundle
        from .models import Campaign
        row = atlas()
        path = self.bundle(inventory=[row], proposals=[proposal([row], rule="MATCH_EXACT",
            auto_validation={"source": "AUTO", "rule": "MATCH_EXACT", "state": "VALIDATED"})])
        import_bundle(path)
        campaigns, events = Campaign.objects.count(), ReviewEvent.objects.count()
        import_bundle(path)
        self.assertEqual(Campaign.objects.count(), campaigns)
        self.assertEqual(ReviewEvent.objects.count(), events)
