import unittest

from app.main import app
from app.financial_ops import router as financial_ops_router
from app.pms_domain import router as pms_domain_router
from app.phase_a_completion import router as phase_a_completion_router
from app.phase_a_workflows import router as legacy_phase_a_router


class SecurityGateRouteRegistrationTests(unittest.TestCase):
    def test_overlapping_stay_and_deposit_paths_have_one_authoritative_handler(self):
        expected = [
            (financial_ops_router, "POST", "/stays/{stay_id}/deposits", "app.financial_ops"),
            (pms_domain_router, "GET", "/stays/{stay_id}/deposits", "app.pms_domain"),
            (pms_domain_router, "POST", "/stays/{stay_id}/occupants", "app.pms_domain"),
            (pms_domain_router, "POST", "/reservations/{reservation_id}/split", "app.pms_domain"),
            (phase_a_completion_router, "POST", "/stays/{stay_id}/deposits/refund", "app.phase_a_completion"),
            (phase_a_completion_router, "POST", "/stays/{stay_id}/deposits/transfer", "app.phase_a_completion"),
            (phase_a_completion_router, "POST", "/stays/{stay_id}/deposits/apply", "app.phase_a_completion"),
        ]
        for router, method, path, expected_module in expected:
            with self.subTest(method=method, path=path):
                matches = [
                    route for route in router.routes
                    if getattr(route, "path", None) == path
                    and method in (getattr(route, "methods", set()) or set())
                ]
                self.assertEqual(len(matches), 1, f"{method} {path} should be registered exactly once on its canonical router")
                self.assertEqual(matches[0].endpoint.__module__, expected_module)
                if path in {
                    "/stays/{stay_id}/deposits/refund",
                    "/stays/{stay_id}/deposits/transfer",
                    "/stays/{stay_id}/deposits/apply",
                }:
                    self.assertIn(
                        "idempotency_key",
                        matches[0].endpoint.__code__.co_varnames,
                        f"{method} {path} must accept an Idempotency-Key for safe replay",
                    )

    def test_non_ledger_deposit_receipt_is_not_registered(self):
        duplicate_path = "/stays/{stay_id}/deposits"
        self.assertFalse(
            any(
                getattr(route, "path", None) == duplicate_path
                and "POST" in (getattr(route, "methods", set()) or set())
                for route in pms_domain_router.routes
            ),
            "Only the ledger-backed financial_ops route may register deposit receipt",
        )

    def test_unledgered_legacy_receive_url_is_not_registered(self):
        legacy_path = "/stays/{stay_id}/deposits/receive"
        self.assertFalse(
            any(
                getattr(route, "path", None) == legacy_path
                and "POST" in (getattr(route, "methods", set()) or set())
                for route in legacy_phase_a_router.routes
            ),
            "Use the ledger-backed /stays/{stay_id}/deposits endpoint for deposit receipt",
        )
        self.assertFalse(any(path.endswith(legacy_path) for path in app.openapi().get("paths", {})))


if __name__ == "__main__":
    unittest.main()
