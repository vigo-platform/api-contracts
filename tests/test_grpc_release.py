import io
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import zipfile
import xml.etree.ElementTree as ET

from scripts.grpc_release import ROOT, NS, fetch, prepare, release_plan, resolve, verify_all, version_key


SHA = "a" * 40


def metadata(*versions):
    values = "".join(f"<version>{version}</version>" for version in versions)
    return f"<metadata><versioning><versions>{values}</versions></versioning></metadata>".encode()


def jar(revision=SHA, version="1.3.0"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "META-INF/MANIFEST.MF",
            f"Manifest-Version: 1.0\r\nContract-Version: {version}\r\nSource-Revision: {revision}\r\n",
        )
    return buffer.getvalue()


class TargetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / "grpc").mkdir()
        (self.root / "grpc/users.proto").write_text('syntax = "proto3";\n')
        (self.root / "build-support").mkdir()
        shutil.copyfile(ROOT / "build-support/grpc-pom.xml", self.root / "build-support/grpc-pom.xml")
        patcher = patch("scripts.grpc_release.ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_tag_selects_user_proto_and_version(self):
        target = resolve(tag="grpc/users/v1.3.0")
        self.assertEqual(target["artifact_id"], "users-grpc-contract")
        self.assertEqual(target["proto"], "grpc/users.proto")
        self.assertEqual(target["module"], "target/grpc/users")
        self.assertEqual(target["version"], "1.3.0")

    def test_manual_and_tag_targets_match(self):
        self.assertEqual(resolve(tag="grpc/users/v1.3.0"), resolve(contract="users", version="1.3.0"))

    def test_new_proto_is_discovered_without_registration(self):
        (self.root / "grpc/namex.proto").write_text('syntax = "proto3";\n')
        target = resolve(tag="grpc/namex/v1.1.1")
        self.assertEqual(target["proto"], "grpc/namex.proto")
        self.assertEqual(target["artifact_id"], "namex-grpc-contract")
        self.assertEqual(target["version"], "1.1.1")

    @patch("subprocess.run")
    def test_verify_all_discovers_new_protos_without_configuration(self, run):
        (self.root / "grpc/namex.proto").write_text('syntax = "proto3";\n')
        verify_all()
        self.assertEqual(run.call_count, 2)
        poms = {call.args[0][4] for call in run.call_args_list}
        self.assertEqual(poms, {str(self.root / "target/grpc/namex/pom.xml"),
                                str(self.root / "target/grpc/users/pom.xml")})

    def test_rejects_missing_proto(self):
        with self.assertRaisesRegex(ValueError, "Missing proto: grpc/storage.proto"):
            resolve(tag="grpc/storage/v1.3.0")

    def test_rejects_unsafe_manual_names(self):
        for name in ("../users", "/users", "users.proto", "users;echo unsafe", "Users", "-users", "users\n"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                resolve(contract=name, version="1.3.0")

    def test_prepare_generates_standalone_coordinates_and_only_selected_proto(self):
        (self.root / "grpc/namex.proto").write_text('syntax = "proto3";\n')
        target = prepare("namex", "1.1.1")
        module = self.root / target["module"]
        pom = ET.parse(module / "pom.xml").getroot()
        self.assertEqual(pom.findtext("m:artifactId", namespaces=NS), "namex-grpc-contract")
        self.assertEqual(pom.findtext("m:properties/m:revision", namespaces=NS), "1.1.1")
        self.assertIsNone(pom.find("m:parent", NS))
        self.assertEqual([p.name for p in (module / "proto").rglob("*.proto")], ["namex.proto"])
        self.assertEqual((module / "proto/namex.proto").read_bytes(), (self.root / "grpc/namex.proto").read_bytes())

    def test_prepare_includes_transitive_local_imports_and_ignores_comments(self):
        (self.root / "grpc/common").mkdir()
        (self.root / "grpc/users.proto").write_text('''syntax = "proto3";
import "common/types.proto";
// import "unrelated.proto";
/* import "also-unrelated.proto"; */
import "google/protobuf/timestamp.proto";
''')
        (self.root / "grpc/common/types.proto").write_text('import public "common/ids.proto";')
        (self.root / "grpc/common/ids.proto").write_text('import "common/types.proto";')
        for name in ("unrelated", "also-unrelated"):
            (self.root / f"grpc/{name}.proto").write_text('syntax = "proto3";')
        target = prepare("users", "1.3.0")
        stage = self.root / target["module"] / "proto"
        paths = {path.relative_to(stage).as_posix() for path in stage.rglob("*.proto")}
        self.assertEqual(paths, {"users.proto", "common/types.proto", "common/ids.proto"})

    def test_prepare_removes_stale_inputs_without_touching_other_contracts(self):
        target = prepare("users", "1.3.0")
        module = self.root / target["module"]
        (module / "proto/stale.proto").write_text("stale")
        other = self.root / "target/grpc/other"
        other.mkdir()
        (other / "keep").write_text("keep")
        prepare("users", "1.4.0")
        self.assertFalse((module / "proto/stale.proto").exists())
        self.assertTrue((other / "keep").exists())

    def test_prepare_rejects_import_escape(self):
        (self.root / "outside.proto").write_text('syntax = "proto3";')
        (self.root / "grpc/users.proto").write_text('import "../outside.proto";')
        with self.assertRaisesRegex(ValueError, "inside grpc/"):
            prepare("users", "1.3.0")

    def test_prepare_rejects_symlinked_proto_outside_grpc(self):
        outside = self.root / "outside.proto"
        outside.write_text('syntax = "proto3";')
        (self.root / "grpc/namex.proto").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "inside grpc/"):
            prepare("namex", "1.1.1")

    def test_rejects_invalid_tags(self):
        for tag in ("v1.3.0", "grpc/users/1.3.0", "grpc/users/v1.3.0-rc.1", "grpc/users/v1.03.0",
                    "grpc/../v1.3.0", "grpc/users/v1.3.0\n", "grpc/users/v1.3.0;echo unsafe"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                resolve(tag=tag)

    def test_manual_version_is_strict(self):
        for version in ("latest", "v1.3.0", "1.3", "1.3.0-SNAPSHOT", "-1.3.0", "1.3.0\n"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                resolve(contract="users", version=version)


class ReleasePlanTests(unittest.TestCase):
    def test_first_release_updates_latest(self):
        self.assertEqual(release_plan("1.3.0", None, None, None, SHA),
                         {"release_exists": False, "update_latest": True})

    def test_new_release_updates_latest(self):
        plan = release_plan("1.3.0", metadata("1.2.0", "latest-SNAPSHOT"), None, None, SHA)
        self.assertTrue(plan["update_latest"])

    def test_old_release_cannot_downgrade_latest(self):
        plan = release_plan("1.2.0", metadata("1.3.0", "latest-SNAPSHOT"), None, None, SHA)
        self.assertFalse(plan["update_latest"])

    def test_numeric_order_instead_of_lexicographic_order(self):
        self.assertGreater(version_key("1.10.0"), version_key("1.9.0"))
        plan = release_plan("1.9.0", metadata("1.10.0"), None, None, SHA)
        self.assertFalse(plan["update_latest"])

    def test_same_commit_rerun_can_finish_latest_without_overwriting_release(self):
        plan = release_plan("1.3.0", metadata("1.3.0"), jar(), b"pom", SHA)
        self.assertEqual(plan, {"release_exists": True, "update_latest": True})

    def test_old_release_rerun_does_not_touch_latest(self):
        plan = release_plan("1.3.0", metadata("1.3.0", "2.0.0"), jar(), b"pom", SHA)
        self.assertEqual(plan, {"release_exists": True, "update_latest": False})

    def test_cannot_reuse_version_from_another_commit(self):
        with self.assertRaisesRegex(ValueError, "another commit"):
            release_plan("1.3.0", metadata("1.3.0"), jar(revision="b" * 40), b"pom", SHA)

    def test_partial_release_is_rejected(self):
        cases = [(metadata("1.3.0"), None, None), (None, None, b"pom"), (None, jar(), None)]
        for meta, existing_jar, pom in cases:
            with self.subTest(meta=meta, pom=pom), self.assertRaises(ValueError):
                release_plan("1.3.0", meta, existing_jar, pom, SHA)

    def test_inconsistent_jar_version_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unexpected metadata"):
            release_plan("1.3.0", None, jar(version="1.2.0"), b"pom", SHA)


class RegistryTests(unittest.TestCase):
    @patch.dict("os.environ", {"GITHUB_ACTOR": "actor", "GITHUB_TOKEN": "test-token"})
    @patch("urllib.request.urlopen")
    def test_404_is_the_only_missing_package_response(self, request):
        request.side_effect = urllib.error.HTTPError("https://example.test", 404, "missing", {}, None)
        self.assertIsNone(fetch("https://example.test"))

    @patch.dict("os.environ", {"GITHUB_ACTOR": "actor", "GITHUB_TOKEN": "test-token"})
    @patch("urllib.request.urlopen")
    def test_auth_errors_fail_closed(self, request):
        for code in (401, 403):
            request.side_effect = urllib.error.HTTPError("https://example.test", code, "denied", {}, None)
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, str(code)):
                fetch("https://example.test")

    @patch.dict("os.environ", {"GITHUB_ACTOR": "actor", "GITHUB_TOKEN": "test-token"})
    @patch("time.sleep")
    @patch("urllib.request.urlopen")
    def test_server_error_is_retried_and_never_treated_as_missing(self, request, sleep):
        request.side_effect = urllib.error.HTTPError("https://example.test", 503, "unavailable", {}, None)
        with self.assertRaisesRegex(ValueError, "503"):
            fetch("https://example.test")
        self.assertEqual(request.call_count, 3)
        self.assertEqual(sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
