"""Regression contract for the check-in/out times exposed to front-desk clients.

These tests deliberately cover configuration resolution only. They do not claim
that check-in/out timestamps or reservation dates are automatically changed by
these settings; front-desk runtime consumption remains a separate integration
task.
"""
import unittest

from app.configuration_schema import resolve_effective_settings, validate_setting


class FrontDeskTimeConfigurationContractTests(unittest.TestCase):
    def test_organization_check_in_and_check_out_defaults_are_inherited(self):
        resolved = resolve_effective_settings(
            {
                "default_check_in_time": "15:30",
                "default_check_out_time": "11:00",
            },
            {},
        )

        self.assertEqual(resolved["settings"]["check_in_time"], "15:30")
        self.assertEqual(resolved["sources"]["check_in_time"], "organization")
        self.assertEqual(resolved["settings"]["check_out_time"], "11:00")
        self.assertEqual(resolved["sources"]["check_out_time"], "organization")

    def test_property_time_overrides_win_independently(self):
        resolved = resolve_effective_settings(
            {
                "default_check_in_time": "15:00",
                "default_check_out_time": "11:00",
            },
            {
                "check_in_time": "16:00",
                "check_out_time": None,
            },
        )

        self.assertEqual(resolved["settings"]["check_in_time"], "16:00")
        self.assertEqual(resolved["sources"]["check_in_time"], "property")
        self.assertEqual(resolved["settings"]["check_out_time"], "11:00")
        self.assertEqual(resolved["sources"]["check_out_time"], "organization")
        self.assertEqual(resolved["overrides"], {"check_in_time": "16:00"})

    def test_platform_time_defaults_apply_when_tenant_values_are_absent(self):
        resolved = resolve_effective_settings({}, {})

        self.assertEqual(resolved["settings"]["check_in_time"], "14:00")
        self.assertEqual(resolved["sources"]["check_in_time"], "platform")
        self.assertEqual(resolved["settings"]["check_out_time"], "12:00")
        self.assertEqual(resolved["sources"]["check_out_time"], "platform")

    def test_time_settings_reject_invalid_clock_values(self):
        for scope, key in (
            ("organization", "default_check_in_time"),
            ("organization", "default_check_out_time"),
            ("property", "check_in_time"),
            ("property", "check_out_time"),
        ):
            with self.subTest(scope=scope, key=key):
                with self.assertRaises(ValueError):
                    validate_setting(scope, key, "25:61")


if __name__ == "__main__":
    unittest.main()
