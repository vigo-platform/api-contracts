#!/usr/bin/env python3
"""Build grpc/<name>.proto dynamically and protect immutable versions/latest."""

import argparse
import base64
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[1]
VERSION = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
CONTRACT = r"[a-z][a-z0-9-]*"
TAG = re.compile(rf"grpc/({CONTRACT})/v({VERSION})")
GROUP_ID = "ir.vigoapp.contracts"
MAVEN_NS = "http://maven.apache.org/POM/4.0.0"
NS = {"m": MAVEN_NS}


def version_key(value):
    if not re.fullmatch(VERSION, value):
        raise ValueError("Version must be a stable MAJOR.MINOR.PATCH, e.g. 1.3.0")
    return tuple(int(part) for part in value.split("."))


def resolve(tag=None, contract=None, version=None):
    if tag:
        match = TAG.fullmatch(tag)
        if not match:
            raise ValueError("Expected tag grpc/<contract>/v<MAJOR.MINOR.PATCH>")
        contract, version = match.group(1, 2)
    if not contract or not version:
        raise ValueError("Both contract and version are required")
    version_key(version)
    if not re.fullmatch(CONTRACT, contract):
        raise ValueError("Contract name must use lowercase letters, digits or hyphens and start with a letter")
    proto = ROOT / "grpc" / f"{contract}.proto"
    if not proto.is_file():
        raise ValueError(f"Missing proto: {proto.relative_to(ROOT)}")
    return {
        "contract": contract,
        "version": version,
        "proto": f"grpc/{contract}.proto",
        "module": f"target/grpc/{contract}",
        "artifact_id": f"{contract}-grpc-contract",
        "tag": f"grpc/{contract}/v{version}",
    }


def local_protos(proto):
    """Stage only this contract and its transitive local imports, preserving paths."""
    source = (ROOT / "grpc").resolve()
    pending = [proto]
    selected = {}
    # Preserve quoted strings while removing comments so commented imports are ignored.
    tokens = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.S)
    imports = re.compile(r'\bimport\s+(?:(?:public|weak)\s+)?["\']([^"\']+)["\']\s*;')
    while pending:
        relative = pending.pop()
        path = (source / relative).resolve()
        if not path.is_relative_to(source):
            raise ValueError(f"Proto path must stay inside grpc/: {relative}")
        if relative in selected:
            continue
        data = path.read_bytes()
        selected[relative] = data
        text = tokens.sub(lambda match: " " if match[0].startswith(("//", "/*")) else match[0], data.decode())
        for dependency in imports.findall(text):
            dependency_path = (source / dependency).resolve()
            if not dependency_path.is_relative_to(source):
                raise ValueError(f"Proto import must stay inside grpc/: {dependency}")
            # External imports (e.g. google/protobuf) are resolved by protoc from
            # Maven dependencies; unresolved imports fail during compilation.
            if dependency_path.is_file():
                pending.append(dependency_path.relative_to(source).as_posix())
    return selected


def prepare(contract, version):
    target = resolve(contract=contract, version=version)
    protos = local_protos(f"{contract}.proto")
    pom = ET.parse(ROOT / "build-support/grpc-pom.xml")
    root = pom.getroot()
    root.find("m:artifactId", NS).text = target["artifact_id"]
    root.find("m:name", NS).text = f"Vigo {contract} gRPC Contract"
    root.find("m:properties/m:revision", NS).text = version
    module = ROOT / target["module"]
    if module.is_symlink() or not module.resolve().is_relative_to(ROOT / "target"):
        raise ValueError("Generated module must stay inside target/")
    if module.exists():
        shutil.rmtree(module)
    for relative, data in protos.items():
        destination = module / "proto" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    ET.register_namespace("", MAVEN_NS)
    ET.indent(pom, space="    ")
    pom.write(module / "pom.xml", encoding="utf-8", xml_declaration=True)
    return target


def verify_all():
    protos = sorted((ROOT / "grpc").glob("*.proto"))
    if not protos:
        raise ValueError("No grpc/*.proto files found")
    wrapper = ROOT / ("mvnw.cmd" if os.name == "nt" else "mvnw")
    for proto in protos:
        target = prepare(proto.stem, "0.0.0")
        subprocess.run([str(wrapper), "--batch-mode", "--no-transfer-progress", "-f",
                        str(ROOT / target["module"] / "pom.xml"),
                        "-Drevision=0.0.0-SNAPSHOT", "clean", "verify"],
                       cwd=ROOT, check=True)


def fetch(url):
    """Return bytes or None for 404; fail closed on auth/server/network errors."""
    actor, token = os.environ.get("GITHUB_ACTOR"), os.environ.get("GITHUB_TOKEN")
    if not actor or not token:
        raise ValueError("GITHUB_ACTOR and GITHUB_TOKEN are required for registry access")
    auth = base64.b64encode(f"{actor}:{token}".encode()).decode()
    request = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            error.close()
            if error.code == 404:
                return None
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise ValueError(f"Registry returned HTTP {error.code} for {url}") from error
        except urllib.error.URLError as error:
            if attempt == 2:
                raise ValueError(f"Cannot reach registry: {url}") from error
        time.sleep(2 ** attempt)


def release_plan(version, metadata, existing_jar, existing_pom, source_revision):
    """Pure decision logic; snapshots never participate in release ordering."""
    candidate = version_key(version)
    published = []
    if metadata is not None:
        root = ET.fromstring(metadata)
        for element in root.findall("./versioning/versions/version"):
            if element.text and re.fullmatch(VERSION, element.text):
                published.append(version_key(element.text))
    exists = existing_jar is not None
    if exists:
        with zipfile.ZipFile(io.BytesIO(existing_jar)) as archive:
            manifest = archive.read("META-INF/MANIFEST.MF").decode()
        # A rerun may finish latest after the numbered release was already deployed.
        # A different commit must never silently reuse the same version.
        manifest = manifest.replace("\r\n", "\n").replace("\n ", "")
        attributes = dict(line.split(": ", 1) for line in manifest.splitlines() if ": " in line)
        if attributes.get("Source-Revision") != source_revision:
            raise ValueError("This release version already exists for another commit; bump the version")
        if attributes.get("Contract-Version") != version or existing_pom is None:
            raise ValueError("Existing release is incomplete or has unexpected metadata")
    elif existing_pom is not None or candidate in published:
        raise ValueError("Release is partially published; inspect the package before retrying")
    return {
        "release_exists": exists,
        "update_latest": candidate >= max([candidate, *published]),
    }


def plan(contract, version):
    entry = resolve(contract=contract, version=version)
    repository = os.environ.get("GITHUB_REPOSITORY", "vigo-platform/api-contracts").lower()
    if not re.fullmatch(r"[a-z0-9_.-]+/[a-z0-9_.-]+", repository):
        raise ValueError("Invalid GitHub repository")
    revision = os.environ.get("GITHUB_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("GITHUB_SHA must identify the checked-out release commit")
    artifact = entry["artifact_id"]
    base = f"https://maven.pkg.github.com/{repository}/{GROUP_ID.replace('.', '/')}/{artifact}"
    metadata = fetch(f"{base}/maven-metadata.xml")
    jar = fetch(f"{base}/{version}/{artifact}-{version}.jar")
    pom = fetch(f"{base}/{version}/{artifact}-{version}.pom")
    return release_plan(version, metadata, jar, pom, revision)


def emit(values):
    print(json.dumps(values, indent=2))
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            for key, value in values.items():
                text = str(value).lower() if isinstance(value, bool) else str(value)
                if "\n" in text or "\r" in text:
                    raise ValueError("Multiline workflow outputs are not allowed")
                stream.write(f"{key}={text}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    target = commands.add_parser("resolve")
    target.add_argument("--tag")
    target.add_argument("--contract")
    target.add_argument("--version")
    stage = commands.add_parser("prepare")
    stage.add_argument("--contract", required=True)
    stage.add_argument("--version", default="0.0.0")
    commands.add_parser("verify-all")
    check = commands.add_parser("plan")
    check.add_argument("--contract", required=True)
    check.add_argument("--version", required=True)
    args = parser.parse_args()
    try:
        if args.command == "resolve":
            emit(resolve(args.tag, args.contract, args.version))
        elif args.command == "prepare":
            emit(prepare(args.contract, args.version))
        elif args.command == "verify-all":
            verify_all()
        else:
            emit(plan(args.contract, args.version))
    except (ValueError, OSError, ET.ParseError, zipfile.BadZipFile, KeyError, subprocess.CalledProcessError) as error:
        print(f"Release error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
