import unittest

from app.main import app


class SecurityGateRouteRegistrationTests(unittest.TestCase):
    def test_overlapping_stay_and_deposit_paths_have_one_authoritative_handler(self):
        expected = {
            ("GET", "/stays/{stay_id}/deposits"): "app.pms_domain",
            ("POST", "/stays/{stay_id}/occupants"): "app.pms_domain",
            ("POST", "/reservations/{reservation_id}/split"): "app.pms_domain",
            ("POST", "/stays/{stay_id}/deposits/refund"): "app.phase_a_completion",
            ("POST", "/stays/{stay_id}/deposits/transfer"): "app.phase_a_completion",
            ("POST", "/stays/{stay_id}/deposits/apply"): "app.phase_a_completion",
        }
        for (method, suffix), expected_module in expected.items():
            with self.subTest(method=method, suffix=suffix):
                matches = [
                    route for route in app.routes
                    if getattr(route, "path", "").endswith(suffix)
                    and method in (getattr(route, "methods", set()) or set())
                ]
                self.assertEqual(len(matches), 1, f"{method} *{suffix} should be registered exactly once")
                self.assertEqual(matches[0].endpoint.__module__, expected_module)

    def test_unledgered_legacy_receive_url_is_not_registered(self):
        legacy_suffix = "/stays/{stay_id}/deposits/receive"
        self.assertFalse(
            any(
                getattr(route, "path", "").endswith(legacy_suffix)
                and "POST" in (getattr(route, "methods", set()) or set())
                for route in app.routes
            ),
            "Use the ledger-backed /api/stays/{stay_id}/deposits endpoint for deposit receipt",
        )


if __name__ == "__main__":
    unittest.main()
