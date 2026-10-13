import unittest

from app.main import app


class SecurityGateRouteRegistrationTests(unittest.TestCase):
    def test_overlapping_stay_and_deposit_paths_have_one_authoritative_handler(self):
        expected = {
            ("GET", "/api/stays/{stay_id}/deposits"): "app.pms_domain",
            ("POST", "/api/stays/{stay_id}/occupants"): "app.pms_domain",
            ("POST", "/api/reservations/{reservation_id}/split"): "app.pms_domain",
            ("POST", "/api/stays/{stay_id}/deposits/refund"): "app.phase_a_completion",
            ("POST", "/api/stays/{stay_id}/deposits/transfer"): "app.phase_a_completion",
            ("POST", "/api/stays/{stay_id}/deposits/apply"): "app.phase_a_completion",
        }
        for (method, path), expected_module in expected.items():
            with self.subTest(method=method, path=path):
                matches = [
                    route for route in app.routes
                    if getattr(route, "path", None) == path
                    and method in (getattr(route, "methods", set()) or set())
                ]
                self.assertEqual(len(matches), 1, f"{method} {path} should be registered exactly once")
                self.assertEqual(matches[0].endpoint.__module__, expected_module)

    def test_unledgered_legacy_receive_url_is_not_registered(self):
        legacy_path = "/api/stays/{stay_id}/deposits/receive"
        self.assertFalse(
            any(
                getattr(route, "path", None) == legacy_path
                and "POST" in (getattr(route, "methods", set()) or set())
                for route in app.routes
            ),
            "Use the ledger-backed /api/stays/{stay_id}/deposits endpoint for deposit receipt",
        )


if __name__ == "__main__":
    unittest.main()
