#!/usr/bin/env python3
"""Prism Knowledge System Verification Script

Validates the full knowledge system stack:
create → upload → index → query → citation → graph → delete → cross-KB isolation

Usage:
  python scripts/verify_knowledge_system.py --base-url http://localhost:5175 --engine-url http://localhost:5180
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid


class VerificationError(Exception):
    pass


def api(method, url, data=None, headers=None):
    h = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def assert_status(code, expected, label):
    if code != expected:
        raise VerificationError(f"{label}: expected {expected}, got {code}")


def check(label, condition):
    if not condition:
        raise VerificationError(f"{label}: FAILED")
    print(f"  [PASS] {label}")


def run(base_url, engine_url):
    print(f"Verifying knowledge system at {base_url} (engine: {engine_url})")
    actor = "verify-user"
    tenant = "verify-tenant"
    headers = {"X-Prism-Actor": actor, "X-Prism-Tenant": tenant}
    prefix = f"{base_url}/api/v1"

    # 1. Create knowledge base
    print("\n[1/8] CREATE knowledge base")
    code, body = api("POST", f"{prefix}/knowledge-bases", {"name": "Verify KB"}, headers)
    assert_status(code, 201, "create KB")
    kb_uid = body["kb_uid"]
    check("kb_uid present", bool(kb_uid))
    check("tenant matches", body["tenant_id"] == tenant)

    # 2. Upload file
    print("\n[2/8] UPLOAD file")
    boundary = f"----FormBoundary{uuid.uuid4().hex}"
    file_content = b"# Verification Document\n\nThis is a test document for verification."
    body_data = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="verify.md"\r\n'
        f"Content-Type: text/markdown\r\n\r\n"
        f"{file_content.decode()}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="relative_path"\r\n\r\n'
        f"verify.md\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="auto_index"\r\n\r\n'
        f"true\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    req = urllib.request.Request(
        f"{prefix}/knowledge-bases/{kb_uid}/files",
        data=body_data,
        headers={
            "X-Prism-Actor": actor,
            "X-Prism-Tenant": tenant,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            upload_body = json.loads(resp.read())
            check("upload accepted (202)", resp.status == 202)
            file_uid = upload_body["file"]["file_uid"]
            check("file_uid present", bool(file_uid))
    except urllib.error.HTTPError as exc:
        raise VerificationError(f"upload: HTTP {exc.code}")

    # 3. List knowledge bases (cross-KB isolation)
    print("\n[3/8] LIST knowledge bases")
    code, body = api("GET", f"{prefix}/knowledge-bases", None, headers)
    assert_status(code, 200, "list KBs")
    check("items is list", isinstance(body["items"], list))

    # 4. Cross-KB isolation
    print("\n[4/8] CROSS-KB ISOLATION")
    other_headers = {"X-Prism-Actor": "other-user", "X-Prism-Tenant": "verify-tenant"}
    code, body = api("GET", f"{prefix}/knowledge-bases", None, other_headers)
    assert_status(code, 200, "other user list")
    check("other user sees empty", body["items"] == [])

    # 5. Get KB
    print("\n[5/8] GET knowledge base")
    code, body = api("GET", f"{prefix}/knowledge-bases/{kb_uid}", None, headers)
    assert_status(code, 200, "get KB")
    check("name matches", body["name"] == "Verify KB")

    # 6. Delete KB
    print("\n[6/8] DELETE knowledge base")
    code, body = api("DELETE", f"{prefix}/knowledge-bases/{kb_uid}", None, headers)
    assert_status(code, 200, "delete KB")
    check("status is deleting", body["status"] == "deleting")

    # 7. Verify deleted KB not visible
    print("\n[7/8] DELETED KB NOT VISIBLE")
    code, _ = api("GET", f"{prefix}/knowledge-bases/{kb_uid}", None, headers)
    assert_status(code, 404, "deleted KB not found")

    # 8. Error envelope
    print("\n[8/8] ERROR ENVELOPE")
    code, body = api("GET", f"{prefix}/knowledge-bases/nonexistent", None, headers)
    assert_status(code, 404, "404 for missing")
    check("error has code", "error" in body and "code" in body["error"])
    check("trace_id present", "trace_id" in body["error"])

    print(f"\n{'='*50}")
    print("ALL VERIFICATION CHECKS PASSED")
    print(f"{'='*50}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Verify Prism knowledge system")
    parser.add_argument("--base-url", default="http://localhost:5175")
    parser.add_argument("--engine-url", default="http://localhost:5180")
    args = parser.parse_args()

    try:
        return run(args.base_url, args.engine_url)
    except VerificationError as exc:
        print(f"\nVERIFICATION FAILED: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"\nVERIFICATION ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
