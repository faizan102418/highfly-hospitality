from decimal import Decimal
import unittest

from app.reservation_workflows import allocate_reservation_deposit


class ReservationDepositAllocationTests(unittest.TestCase):
    def test_equal_room_requirements_split_partial_deposit_evenly(self):
        allocations = allocate_reservation_deposit(
            [Decimal("100.00"), Decimal("100.00"), Decimal("100.00")],
            Decimal("100.00"),
        )
        self.assertEqual(allocations, [Decimal("33.33"), Decimal("33.34"), Decimal("33.33")])
        self.assertEqual(sum(allocations), Decimal("100.00"))

    def test_unequal_requirements_are_allocated_proportionally(self):
        allocations = allocate_reservation_deposit(
            [Decimal("100.00"), Decimal("200.00"), Decimal("300.00")],
            Decimal("120.00"),
        )
        self.assertEqual(allocations, [Decimal("20.00"), Decimal("40.00"), Decimal("60.00")])

    def test_full_deposit_is_capped_at_each_stay_requirement(self):
        allocations = allocate_reservation_deposit(
            [Decimal("80.00"), Decimal("120.00"), Decimal("50.00")],
            Decimal("250.00"),
        )
        self.assertEqual(allocations, [Decimal("80.00"), Decimal("120.00"), Decimal("50.00")])

    def test_zero_and_negative_requirements_do_not_receive_deposit(self):
        allocations = allocate_reservation_deposit(
            [Decimal("0.00"), Decimal("100.00"), Decimal("100.00")],
            Decimal("50.00"),
        )
        self.assertEqual(allocations, [Decimal("0.00"), Decimal("25.00"), Decimal("25.00")])

    def test_rejects_deposit_above_required_total(self):
        with self.assertRaises(ValueError):
            allocate_reservation_deposit([Decimal("100.00")], Decimal("100.01"))


if __name__ == "__main__":
    unittest.main()
