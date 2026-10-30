import unittest

from app.db import Base
from app.pms_core import FolioWindow
from app.stay_lifecycle import StayFolioWindow


class FolioWindowSchemaContractTests(unittest.TestCase):
    def test_legacy_group_folio_window_and_stay_window_are_distinct_tables(self):
        legacy = FolioWindow.__table__
        stay = StayFolioWindow.__table__

        self.assertEqual(legacy.name, "folio_windows")
        self.assertEqual(stay.name, "stay_folio_windows")
        self.assertIsNot(legacy, stay)
        self.assertIs(Base.metadata.tables[legacy.name], legacy)
        self.assertIs(Base.metadata.tables[stay.name], stay)

    def test_stay_window_has_stay_parent_while_legacy_window_does_not(self):
        legacy_columns = set(FolioWindow.__table__.columns.keys())
        stay_columns = set(StayFolioWindow.__table__.columns.keys())

        self.assertNotIn("stay_id", legacy_columns)
        self.assertIn("stay_id", stay_columns)
        self.assertEqual(
            {fk.target_fullname for fk in StayFolioWindow.__table__.c.stay_id.foreign_keys},
            {"stays.id"},
        )
        self.assertIn("folio_id", legacy_columns)
        self.assertIn("folio_id", stay_columns)


if __name__ == "__main__":
    unittest.main()
