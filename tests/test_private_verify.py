import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from private_verify import compare, result_section


def simulated_input():
    return {
        "mode": "simulation",
        "phone": {"expected": "138****0417", "observed": "138****0417"},
        "transfer": {
            "expected": {"time": "2091-04-17T09:21:37+08:00", "amount": "947.51", "status": "completed"},
            "observed": {"time": "2091-04-17T01:21:37Z", "amount": "947.52", "status": "completed"},
        },
    }


class PrivateVerificationTest(unittest.TestCase):
    def test_compares_visible_phone_digits_and_independent_transfer_fields(self):
        data = simulated_input()
        self.assertEqual(compare(data), {"手机号可见位": True, "银证转账时间": True, "银证转账金额": False, "银证转账状态": True})
        data["phone"]["observed"] = "138****0418"
        data["transfer"]["observed"]["status"] = "pending"
        self.assertFalse(compare(data)["手机号可见位"])
        self.assertFalse(compare(data)["银证转账状态"])

    def test_report_omits_all_input_values(self):
        data = simulated_input()
        section = result_section(data)
        self.assertIn("| 银证转账金额 | 不一致 |", section)
        for value in (*data["phone"].values(), *(v for row in data["transfer"].values() for v in row.values())):
            self.assertNotIn(value, section)

    def test_rejects_unmasked_or_out_of_scope_fields(self):
        data = simulated_input()
        data["phone"]["observed"] = "138" + "0000" + "0417"
        with self.assertRaises(ValueError):
            result_section(data)
        data = simulated_input()
        data["transfer"]["expected"]["account_number"] = "demo-extra-field"
        with self.assertRaises(ValueError):
            result_section(data)
        data = simulated_input()
        data["transfer"]["expected"]["time"] = "2091-04-17T09:21:37"
        with self.assertRaises(ValueError):
            result_section(data)
