#!/usr/bin/env python3
"""Write a compact GitHub Actions summary from actual step outcomes."""

import json
import os
from pathlib import Path


STATUS = {
    "success": "✅ Passed",
    "failure": "❌ Failed",
    "cancelled": "🛑 Cancelled",
    "skipped": "⏭ Skipped",
}


def render(env, steps):
    def outcome(step):
        return steps.get(step, {}).get("conclusion", "skipped")

    def status(step):
        return STATUS.get(outcome(step), "⏭ Not run")

    def output(step, key, default=""):
        return steps.get(step, {}).get("outputs", {}).get(key, default)

    def text(value):
        return str(value).replace("\n", " ").replace("\r", " ").replace("`", "").replace("|", "\\|")

    publishing = env.get("REPORT_KIND") == "publish"
    job = env.get("JOB_STATUS", "unknown")
    title = "gRPC package" if publishing else "gRPC verification"
    result = STATUS.get(job, "⏭ Not completed")
    lines = [f"## {title} · {result}", ""]
    if publishing:
        artifact = output("target", "artifact_id")
        version = output("target", "version")
        if artifact and version:
            lines += [f"`ir.vigoapp.contracts:{text(artifact)}:{text(version)}`", ""]
        else:
            lines += [f"Ref: `{text(env.get('GITHUB_REF_NAME', 'unknown'))}`", ""]

    rows = []
    if publishing:
        rows.append(("Select Proto / version", status("target")))
    rows += [("Java setup", status("java")), ("Tests", status("tests")),
             ("Build JARs", status("build"))]
    if publishing:
        rows += [("Save downloadable files", status("artifacts")),
                 ("Check registry versions", status("plan"))]
        release, latest = status("release"), status("latest")
        if outcome("release") == "success":
            release = "✅ Published"
        elif outcome("release") == "skipped" and outcome("plan") == "success" and output("plan", "release_exists") == "true":
            release = "⏭ Already published (same commit)"
        if outcome("latest") == "success":
            latest = "✅ Updated"
        elif outcome("latest") == "skipped" and outcome("plan") == "success" and output("plan", "update_latest") == "false":
            latest = "⏭ Newer release retained"
        if env.get("PUBLISH") != "true":
            release = latest = "— Build only"
        rows += [("Numbered package", release), ("latest-SNAPSHOT", latest)]

    lines += ["| Stage | Result |", "| --- | --- |"]
    lines += [f"| {label} | {value} |" for label, value in rows]
    repository = env.get("GITHUB_REPOSITORY", "")
    server = env.get("GITHUB_SERVER_URL", "https://github.com")
    sha = env.get("GITHUB_SHA", "")
    lines += ["", f"Source: [`{sha[:7]}`]({server}/{repository}/commit/{sha})"]
    artifact_url = output("artifacts", "artifact-url")
    if outcome("artifacts") == "success" and artifact_url:
        lines += [f"[Download JARs and POM]({artifact_url}) · retained for 14 days"]
    if job in ("failure", "cancelled"):
        run_url = f"{server}/{repository}/actions/runs/{env.get('GITHUB_RUN_ID', '')}"
        lines += [f"[Open job logs]({run_url}) for the failed or cancelled stage."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    steps = json.loads(os.environ.get("STEPS_JSON", "{}"))
    report = render(os.environ, steps)
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
        stream.write(report)
