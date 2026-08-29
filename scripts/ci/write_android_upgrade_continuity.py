#!/usr/bin/env python3
"""Write package/data continuity evidence after an Android install -r."""

import argparse
import json
import os
import re


def package_facts(text):
    def value(name):
        match = re.search(rf"^\s*{re.escape(name)}=([^\s]+)", text, re.MULTILINE)
        return match.group(1) if match else None
    return {
        "first_install_time": value("firstInstallTime"),
        "last_update_time": value("lastUpdateTime"),
        "data_dir": value("dataDir"),
        "version_name": value("versionName"),
        "version_code": value("versionCode"),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--verify-result", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args(argv)
    for path in (args.before, args.after, args.state, args.verify_result):
        if not os.path.isfile(path):
            raise SystemExit(f"FAIL: continuity input missing: {path}")
    before = package_facts(open(args.before).read())
    after = package_facts(open(args.after).read())
    state = json.load(open(args.state))
    verify = json.load(open(args.verify_result))
    marker = state.get("marker_question")
    if verify.get("result") != "PASS" or not marker:
        raise SystemExit("FAIL: continuity requires a PASS verify result and marker")
    if not after.get("data_dir") or after.get("data_dir") != before.get("data_dir"):
        raise SystemExit("FAIL: package data directory continuity was not proven")
    payload = {
        "schema": "android-upgrade-continuity-v1",
        "migration_success": True,
        "install_mode": "adb install -r",
        "pre_upgrade_package": before,
        "post_upgrade_package": after,
        "same_data_dir": before.get("data_dir") == after.get("data_dir"),
        "first_install_time_preserved": before.get("first_install_time") == after.get("first_install_time"),
        "last_update_time_changed_or_observed": before.get("last_update_time") != after.get("last_update_time"),
        "marker_question_present_in_state": True,
        "verify_result": verify.get("result"),
    }
    with open(args.output, "w") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
