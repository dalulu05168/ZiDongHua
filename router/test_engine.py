import unittest
from engine import Rule, Event, Router, can_send

class RouterTests(unittest.TestCase):
    def setUp(self):
        self.enabled = Rule("r1", "tg01", "-1001", "wa01", "group01", True)
        self.event = Event("tg01", "-1001", "42", "Test message")

    def test_enabled_matching_route(self):
        records = Router([self.enabled]).prepare(self.event)
        self.assertEqual(1, len(records))
        self.assertEqual("pending_approval", records[0]["status"])

    def test_disabled_route(self):
        self.assertEqual([], Router([Rule("r2", "tg01", "-1001", "wa01", "g")]).prepare(self.event))

    def test_wrong_source(self):
        self.assertEqual([], Router([self.enabled]).prepare(Event("tg02", "-1001", "42", "Test")))

    def test_dedup(self):
        router = Router([self.enabled])
        self.assertEqual(1, len(router.prepare(self.event)))
        self.assertEqual([], router.prepare(self.event))

    def test_default_safety_gate(self):
        self.assertFalse(can_send(dry_run=True, backend_enabled=True, bridge_enabled=True, approved=True, rule_enabled=True))
        self.assertFalse(can_send(dry_run=False, backend_enabled=True, bridge_enabled=True, approved=False, rule_enabled=True))
        self.assertFalse(can_send(dry_run=False, backend_enabled=True, bridge_enabled=True, approved=True, rule_enabled=False))

    def test_opt_in_only(self):
        self.assertTrue(can_send(dry_run=False, backend_enabled=True, bridge_enabled=True, approved=True, rule_enabled=True))

if __name__ == "__main__":
    unittest.main()
