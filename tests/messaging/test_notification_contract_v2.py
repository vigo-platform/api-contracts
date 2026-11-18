"""Structural v2 checks; runtime obligations are specified in README.v2.md."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "messaging/notification"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


class NotificationV2ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schema = read_json(CONTRACT / "notification-requested.v2.schema.json")
        Draft202012Validator.check_schema(schema)
        cls.validator = Draft202012Validator(schema, format_checker=FormatChecker())
        cls.example = read_json(CONTRACT / "examples/v2/valid/coach-approved.both.fa.json")

    def check_value(self, path, value, valid=False):
        command = deepcopy(self.example)
        obj = command
        for key in path[:-1]:
            obj = obj[key]
        obj[path[-1]] = value
        self.assertEqual(self.validator.is_valid(command), valid, str(path))

    def test_checked_in_fixtures(self):
        for folder, valid, count in (("valid", True, 3), ("invalid", False, 11)):
            paths = sorted((CONTRACT / "examples/v2" / folder).glob("*.json"))
            self.assertEqual(len(paths), count)
            for path in paths:
                with self.subTest(fixture=path.name):
                    self.assertEqual(self.validator.is_valid(read_json(path)), valid)

    def test_all_channel_locale_and_scenario_combinations(self):
        for indices in ((0,), (1,), (0, 1), (1, 0)):
            for locale in ("fa", "en"):
                for scenario in ("approved", "rejected"):
                    command = deepcopy(self.example)
                    command["data"].update(
                        deliveries=[command["data"]["deliveries"][i] for i in indices],
                        locale=locale,
                        template_id=f"notification.coach_application.{scenario}.v1",
                    )
                    with self.subTest(channels=indices, locale=locale, scenario=scenario):
                        self.validator.validate(command)

    def test_required_fields(self):
        for path, fields in (
            ((), ("event_id", "event_type", "event_version", "occurred_at", "producer", "correlation_id", "data")),
            (("data",), ("locale", "template_id", "template_parameters", "deliveries")),
            (("data", "deliveries", 0), ("channel", "recipient")),
            (("data", "deliveries", 1), ("channel", "recipient")),
            (("data", "deliveries", 0, "recipient"), ("destination",)),
            (("data", "deliveries", 1, "recipient"), ("user_id",)),
        ):
            for field in fields:
                command = deepcopy(self.example)
                obj = command
                for key in path:
                    obj = obj[key]
                del obj[field]
                with self.subTest(path=path, field=field):
                    self.assertFalse(self.validator.is_valid(command))

    def test_closed_objects_and_notification_owned_state(self):
        for path in ((), ("data",), ("data", "deliveries", 0),
                     ("data", "deliveries", 1), ("data", "deliveries", 0, "recipient"),
                     ("data", "deliveries", 1, "recipient")):
            for field in ("unexpected", "read", "read_at", "status", "persist", "subject", "html"):
                with self.subTest(path=path, field=field):
                    self.check_value((*path, field), "not-allowed")

    def test_recipient_types_and_channel_uniqueness(self):
        user_path = ("data", "deliveries", 1, "recipient", "user_id")
        for value in ("1", "9007199254740993", "9223372036854775807"):
            self.check_value(user_path, value, True)
        for value in (1, 1.5, True, None, "", "0", "-1", "01", "1.0", " 1", "1\n",
                      "+1", "1e3", "1 ", "۱۲۳", "١٢٣", "１２３", "9223372036854775808",
                      "9999999999999999999",
                      "12345678901234567890", "coach@example.invalid", self.example["event_id"]):
            self.check_value(user_path, value)
        for value in ("invalid", "Name <a@example.invalid>", "a@example.invalid,b@example.invalid",
                      "a..b@example.invalid", "a@example.invalid\n", "a" * 65 + "@example.invalid"):
            self.check_value(("data", "deliveries", 0, "recipient", "destination"), value)
        for channel in ("SMS", "PUSH", "email", None):
            self.check_value(("data", "deliveries", 0, "channel"), channel)
        for i in (0, 1):
            deliveries = [deepcopy(self.example["data"]["deliveries"][i]) for _ in range(2)]
            # Different recipients still cannot repeat a channel.
            key = "destination" if i == 0 else "user_id"
            deliveries[1]["recipient"][key] = "other@example.invalid" if i == 0 else "999"
            self.check_value(("data", "deliveries"), deliveries)
        self.check_value(("data", "deliveries"), self.example["data"]["deliveries"] * 2)

    def test_user_id_int64_boundaries(self):
        maximum = 2**63 - 1
        # Exercise every decimal-prefix boundary against arithmetic, not a copy
        # of the schema's range regex, including 18/19/20-digit transitions.
        boundaries = {0, 1, maximum, 10**18, 10**19}
        for power in range(19):
            scale = 10**power
            boundaries.add(maximum // scale * scale)
            boundaries.add((maximum // scale + 1) * scale)
        for boundary in sorted(boundaries):
            for value in (boundary - 1, boundary, boundary + 1):
                with self.subTest(user_id=str(value)):
                    self.check_value(("data", "deliveries", 1, "recipient", "user_id"),
                                     str(value), 1 <= value <= maximum)

    def test_parameter_bounds_and_secret_field_names(self):
        path = ("data", "template_parameters")
        for value in ({}, {"label": "فارسی"}, {"label": "x" * 256},
                      {f"key_{i}": "text" for i in range(16)}):
            self.check_value(path, value, True)
        for value in (None, [], {"label": ""}, {"label": "x" * 257},
                      {"label": "line\nbreak"}, {"label": "\x00"}, {"label": "<script>"},
                      {"label": {}}, {"label": []}, {"label": 123},
                      {"BadKey": "text"}, {"a" * 65: "text"},
                      {f"key_{i}": "text" for i in range(17)}):
            self.check_value(path, value)
        for key in ("password", "plaintext_password", "token", "access_token", "refresh_token",
                    "credential", "credentials", "secret", "api_key", "otp", "otp_code"):
            self.check_value(path, {key: "synthetic-placeholder"})

    def test_identity_and_template_syntax(self):
        for producer in ("user-service", "order-service", "payment-service"):
            self.check_value(("producer",), producer, True)
        for producer in ("", "User-service", "user-service\n", "x" * 65 + "-service"):
            self.check_value(("producer",), producer)
        for path, values in (
            (("event_version",), (1, 3, "2", True)),
            (("event_type",), ("CoachApplicationApproved", "NotificationSent")),
            (("event_id",), ("invalid", self.example["event_id"].upper())),
            (("correlation_id",), ("invalid",)),
            (("data", "locale"), ("", "ar", None)),
            (("data", "template_id"), ("auth.login_otp.email.v1", "unknown", "notification.notice.v0", "notification.notice.v1\n")),
        ):
            for value in values:
                self.check_value(path, value)

    def test_time_profile_and_optional_expiration(self):
        command = deepcopy(self.example)
        del command["data"]["expires_at"]
        self.validator.validate(command)
        for path in (("occurred_at",), ("data", "expires_at")):
            for value in ("2026-01-01T12:00:00Z", "2026-01-01t12:00:59z", "2026-01-01T12:00:00.123+00:00"):
                self.check_value(path, value, True)
            for value in (None, "invalid", "2026-02-30T12:00:00Z", "2026-01-01T12:00:60Z",
                          "2026-01-01T12:00:00+03:30", "2026-01-01T12:00:00-00:00",
                          "2026-01-01T12:00:00", "2026-01-01T12:00:00Z\n"):
                self.check_value(path, value)

    def test_runtime_checks_are_not_claimed_as_schema_guarantees(self):
        # These must be rejected by semantic/catalog/authorization checks, not this schema.
        for path, value in (
            (("producer",), "unregistered-service"),
            (("data", "template_id"), "notification.unregistered.v1"),
            (("data", "template_parameters"), {"innocent_key": "synthetic-secret-placeholder"}),
            (("data", "expires_at"), "2000-01-01T00:00:00Z"),
        ):
            self.check_value(path, value, True)

    def test_version_isolation(self):
        v1 = Draft202012Validator(read_json(CONTRACT / "notification-requested.v1.schema.json"),
                                  format_checker=FormatChecker())
        old = read_json(CONTRACT / "examples/notification-requested.v1.email-otp.json")
        v1.validate(old)
        self.assertFalse(self.validator.is_valid(old))
        self.assertFalse(v1.is_valid(self.example))
        old["event_version"] = 2
        self.assertFalse(self.validator.is_valid(old))
        command = deepcopy(self.example)
        command["event_version"] = 1
        self.assertFalse(v1.is_valid(command))

    def test_v1_artifacts_unchanged(self):
        # LF normalization makes these guards portable across Git autocrlf settings.
        expected = {
            "messaging/notification/notification-requested.v1.schema.json": "367ab8f1f01522fb406a6e945e3d0b82728eb83c4d5b19ac824529ccc08b9cc8",
            "messaging/notification/examples/notification-requested.v1.email-otp.json": "6717be1a924d71fb504efef92540c38844ae776e9b41088ba2ff232617dea2c0",
            "messaging/notification/README.md": "aeb1302563b4bb44a46f5bcca4e03d0afb2c7bb3d20b01bad61ddf6b39a89ed2",
            "tests/messaging/test_notification_contract.py": "357b0cb47da33ae5e052e3af174546f8fcfaf3f72498d74afa2975962b8acab7",
        }
        for name, digest in expected.items():
            with self.subTest(file=name):
                content = (ROOT / name).read_bytes().replace(b"\r\n", b"\n")
                self.assertEqual(hashlib.sha256(content).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
