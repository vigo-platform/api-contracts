"""Structural contract checks only; no wall-clock or service behavior tests."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker


CONTRACT = Path(__file__).resolve().parents[2] / "messaging" / "notification"
TEMPLATES = {
    "LOGIN_OTP": "auth.login_otp.email.v1",
    "REGISTRATION_OTP": "auth.registration_otp.email.v1",
    "PASSWORD_CHANGE_OTP": "auth.password_change_otp.email.v1",
    "PASSWORD_RESET_OTP": "auth.password_reset_otp.email.v1",
}


class NotificationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schema = json.loads((CONTRACT / "notification-requested.v1.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        cls.validator = Draft202012Validator(schema, format_checker=FormatChecker())
        cls.example = json.loads(
            (CONTRACT / "examples/notification-requested.v1.email-otp.json").read_text()
        )

    def test_checked_in_example(self):
        self.validator.validate(self.example)
        self.assertEqual(self.example["data"]["template_parameters"]["otp_code"], "012345")

    def test_all_purposes_and_locales(self):
        for purpose, template in TEMPLATES.items():
            for locale in ("fa", "en"):
                with self.subTest(purpose=purpose, locale=locale):
                    command = deepcopy(self.example)
                    command["data"].update(purpose=purpose, template_id=template, locale=locale)
                    self.validator.validate(command)

    def test_single_mailbox_syntax(self):
        for destination in ("user@example.com", "first.last+tag@example.co.uk"):
            with self.subTest(destination=destination):
                command = deepcopy(self.example)
                command["data"]["recipient"]["destination"] = destination
                self.validator.validate(command)
        for destination in (
            "Saghar <user@example.com>",
            "user1@example.com,user2@example.com",
            "user@[192.0.2.1]",
            "\u0633\u0627\u0631\u0627@example.invalid",
            '"first,last"@example.invalid',
            '"user"@example.invalid',
            "a..b@example.invalid", ".user@example.invalid", "user.@example.invalid",
            "a@-example.invalid", "a@example..invalid", "a(comment)@example.invalid",
        ):
            with self.subTest(destination=destination):
                command = deepcopy(self.example)
                command["data"]["recipient"]["destination"] = destination
                self.assertFalse(self.validator.is_valid(command))

    def test_mailbox_length_boundaries(self):
        boundary = "a" * 64 + "@" + ".".join(("b" * 63, "c" * 63, "d" * 61))
        self.assertEqual(len(boundary), 254)
        cases = (
            ("a" * 64 + "@example.invalid", True),
            ("user@" + "b" * 63 + ".invalid", True),
            (boundary, True),
            ("!#$%&'*+-/=?^_`{|}~.tag@example.invalid", True),
            ("a" * 65 + "@example.invalid", False),
            ("user@" + "b" * 64 + ".invalid", False),
            ("user@example." + "b" * 64, False),
            (boundary + "d", False),
        )
        for index, (destination, valid) in enumerate(cases):
            with self.subTest(case=index):
                command = deepcopy(self.example)
                command["data"]["recipient"]["destination"] = destination
                self.assertEqual(self.validator.is_valid(command), valid)

    def test_timestamp_seconds_boundaries(self):
        for field in ("occurred_at", "expires_at"):
            for seconds, valid in (("00", True), ("59", True), ("60", False)):
                with self.subTest(field=field, seconds=seconds):
                    command = deepcopy(self.example)
                    obj = command if field == "occurred_at" else command["data"]
                    obj[field] = f"2026-12-31T23:59:{seconds}Z"
                    self.assertEqual(self.validator.is_valid(command), valid)

    def test_required_fields(self):
        for path, fields in (
            ((), ("event_id", "event_type", "event_version", "occurred_at", "producer", "correlation_id", "data")),
            (("data",), ("channel", "purpose", "locale", "recipient", "template_id", "template_parameters", "expires_at")),
            (("data", "recipient"), ("destination",)),
            (("data", "template_parameters"), ("otp_code",)),
        ):
            for field in fields:
                with self.subTest(path=path, missing=field):
                    command = deepcopy(self.example)
                    obj = command
                    for key in path:
                        obj = obj[key]
                    del obj[field]
                    self.assertFalse(self.validator.is_valid(command))

    def test_invalid_values(self):
        cases = {
            "event_type": ["NotificationSent"],
            "event_version": [2, "1", True],
            "producer": ["user-service"],
            "event_id": ["not-a-uuid", "a" * 36],
            "correlation_id": ["not-a-uuid"],
            "aggregate_id": ["unexpected"],
            "aggregate_version": [1],
            "user_id": ["unexpected"],
            "idempotency_key": ["unexpected"],
            "data.channel": ["SMS"],
            "data.purpose": ["PASSWORD_RESET_NOTICE", "UNKNOWN"],
            "data.locale": ["de", "", None],
            "data.template_id": ["unknown", "auth.login_otp.email.v1"],
            "data.template_parameters": [{}, {"otp_code": "012345", "extra": "x"}, None],
            "data.template_parameters.otp_code": [123456, "12345", "1234567", "12345a", "۱۲۳۴۵۶", "012345\n"],
            "data.recipient": [[{"destination": "recipient@example.invalid"}], {"destination": "recipient@example.invalid", "cc": "other@example.invalid"}],
            "data.recipient.destination": [["recipient@example.invalid"], "a@example.invalid,b@example.invalid", "a@example.invalid; b@example.invalid", "Person <a@example.invalid>", "invalid", "a@example.invalid\n"],
            "data.html": ["<p>disallowed</p>"],
        }
        for field in ("occurred_at", "data.expires_at"):
            cases[field] = ["invalid", "2026-02-30T12:00:00Z", "2026-01-01T12:00:00", "2026-01-01T12:00:00+03:30", "2026-01-01T12:00:00-00:00", "2026-01-01T12:00:00Z\n"]
        for path, values in cases.items():
            for index, value in enumerate(values):
                with self.subTest(path=path, case=index):
                    command = deepcopy(self.example)
                    obj = command
                    keys = path.split(".")
                    for key in keys[:-1]:
                        obj = obj[key]
                    obj[keys[-1]] = value
                    self.assertFalse(self.validator.is_valid(command))

    def test_every_mismatched_template(self):
        for purpose, expected in TEMPLATES.items():
            for template in TEMPLATES.values():
                if template != expected:
                    with self.subTest(purpose=purpose, template=template):
                        command = deepcopy(self.example)
                        command["data"].update(purpose=purpose, template_id=template)
                        self.assertFalse(self.validator.is_valid(command))

    def test_utc_representations(self):
        for timestamp in ("2026-01-01T12:00:00Z", "2026-01-01T12:00:00.123+00:00", "2026-01-01t12:00:00z"):
            with self.subTest(timestamp=timestamp):
                command = deepcopy(self.example)
                command["occurred_at"] = timestamp
                command["data"]["expires_at"] = timestamp
                self.validator.validate(command)


if __name__ == "__main__":
    unittest.main()
