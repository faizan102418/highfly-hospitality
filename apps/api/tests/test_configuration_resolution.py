import unittest

from app.configuration_schema import resolve_effective_settings


class EffectiveConfigurationResolutionTests(unittest.TestCase):
    def test_property_override_wins_over_organization_default(self):
        resolved = resolve_effective_settings(
            {
                "default_language": "ur",
                "default_check_in_time": "15:00",
            },
            {
                "language": "en",
            },
        )

        self.assertEqual(resolved["settings"]["language"], "en")
        self.assertEqual(resolved["sources"]["language"], "property")
        self.assertEqual(resolved["settings"]["check_in_time"], "15:00")
        self.assertEqual(resolved["sources"]["check_in_time"], "organization")

    def test_null_property_value_falls_back_to_organization_then_platform(self):
        resolved = resolve_effective_settings(
            {
                "default_language": "ur",
            },
            {
                "language": None,
                "currency": None,
            },
        )

        self.assertEqual(resolved["settings"]["language"], "ur")
        self.assertEqual(resolved["sources"]["language"], "organization")
        self.assertEqual(resolved["settings"]["currency"], "PKR")
        self.assertEqual(resolved["sources"]["currency"], "platform")
        self.assertNotIn("language", resolved["overrides"])
        self.assertNotIn("currency", resolved["overrides"])

    def test_platform_defaults_are_used_when_no_tenant_value_exists(self):
        resolved = resolve_effective_settings({}, {})

        self.assertEqual(resolved["settings"]["check_in_time"], "14:00")
        self.assertEqual(resolved["sources"]["check_in_time"], "platform")
        self.assertEqual(resolved["settings"]["currency"], "PKR")
        self.assertEqual(resolved["sources"]["currency"], "platform")


if __name__ == "__main__":
    unittest.main()
