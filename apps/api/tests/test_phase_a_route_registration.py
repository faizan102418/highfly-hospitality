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
        expected_handlers = {"transfer_deposit", "refund_deposit", "apply_deposit"}
        completion_routes = [
            route
            for route in app.routes
            if isinstance(route, APIRoute)
            and route.endpoint.__module__ == "app.phase_a_completion"
            and route.endpoint.__name__ in expected_handlers
            and "POST" in route.methods
        ]
        self.assertEqual(
            {route.endpoint.__name__ for route in completion_routes},
            expected_handlers,
            "Expected all completion deposit handlers to be mounted; deposit routes="
            + repr([
                (route.path, sorted(route.methods), route.endpoint.__module__, route.endpoint.__name__)
                for route in app.routes
                if isinstance(route, APIRoute) and "deposit" in route.path
            ]),
        )

        for completion_route in completion_routes:
            with self.subTest(path=completion_route.path):
                first_matching_route = next(
                    route
                    for route in app.routes
                    if isinstance(route, APIRoute)
                    and route.path == completion_route.path
                    and "POST" in route.methods
                )
                self.assertEqual(
                    first_matching_route.endpoint.__module__,
                    "app.phase_a_completion",
                    f"{completion_route.path} must resolve to the completion implementation first",
                )


if __name__ == "__main__":
    unittest.main()
