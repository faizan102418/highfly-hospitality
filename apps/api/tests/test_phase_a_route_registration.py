"""Protect the effective FastAPI handlers for overlapping legacy Phase A routes.

The completion router is included inside billing before the legacy workflow router
is mounted by main.py. Keep this explicit: changing router order can silently
switch public endpoints to older implementations.
"""
import unittest

from fastapi.routing import APIRoute

from app.main import app


class PhaseARouteRegistrationTests(unittest.TestCase):
    def test_completion_handlers_win_for_overlapping_deposit_routes(self):
        expected_paths = {
            "/api/stays/{stay_id}/deposits/transfer",
            "/api/stays/{stay_id}/deposits/refund",
            "/api/stays/{stay_id}/deposits/apply",
        }

        first_route_by_path = {}
        for route in app.routes:
            if not isinstance(route, APIRoute) or "POST" not in route.methods:
                continue
            for expected_path in expected_paths:
                if route.path.endswith(expected_path.removeprefix("/api")):
                    first_route_by_path.setdefault(expected_path, route)

        self.assertEqual(
            set(first_route_by_path),
            expected_paths,
            "Expected all overlapping Phase A deposit routes to be registered",
        )
        for path, route in first_route_by_path.items():
            with self.subTest(path=path):
                self.assertEqual(
                    route.endpoint.__module__,
                    "app.phase_a_completion",
                    f"{path} must resolve to the completion implementation first",
                )


if __name__ == "__main__":
    unittest.main()
