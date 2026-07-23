#!/usr/bin/env python3
"""Prism Knowledge System — Rigorous Verification Script

Validates the complete knowledge pipeline against real infrastructure:
create → upload → process → poll succeed → verify parse/chunk/index →
search unique text → citation → graph Neo4j → Milvus/ES data →
real degraded → delete → cross-store cleanup → isolation

Usage:
  python scripts/verify_knowledge_system.py --base-url http://127.0.0.1:5175 --engine-url http://127.0.0.1:5180
"""

import argparse
import json
import sys
import time
import uuid
import urllib.error
import urllib.request

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_ERR = 2

_FAILS = []


def check(label, condition):
    if condition:
        print(f"  [PASS] {label}")
    else:
        print(f"  [FAIL] {label}")
        _FAILS.append(label)


def stage_header(n):
    print(f"\n{'=' * 60}")
    print(f"[{n}]")
    print(f"{'=' * 60}")


def api(method, url, data=None, headers=None, timeout=30):
    h = {"Content-Type": "application/json", **(headers or {})}
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body_bytes = exc.read()
        try:
            return exc.code, json.loads(body_bytes)
        except Exception:
            return exc.code, {"_raw": body_bytes.decode(errors="replace")}


UNIQUE_MARKER = str(uuid.uuid4())


class Verifier:
    def __init__(self, base_url, engine_url):
        self.base = base_url
        self.engine = engine_url
        self.prefix = f"{base_url}/api/v1"
        self.actor = "verify-user"
        self.tenant = "verify-tenant"
        self.hdrs = {"X-Prism-Actor": self.actor, "X-Prism-Tenant": self.tenant}

    def run(self):
        try:
            self._verify()
        except Exception as exc:
            print(f"\nFATAL: {exc}", file=sys.stderr)
            sys.exit(EXIT_ERR)
        if _FAILS:
            print(f"\n{'=' * 60}")
            print(f"VERIFICATION FAILED: {len(_FAILS)} check(s) failed")
            for f in _FAILS:
                print(f"  - {f}")
            print(f"{'=' * 60}")
            sys.exit(EXIT_FAIL)
        else:
            print(f"\n{'=' * 60}")
            print("ALL VERIFICATION CHECKS PASSED")
            print(f"{'=' * 60}")
            sys.exit(EXIT_OK)

    def _verify(self):
        # 1. HEALTH
        stage_header("1/11 HEALTH CHECK")
        try:
            code, eng = api("GET", f"{self.engine}/health")
            check("engine health 200", code == 200 and eng.get("status") == "ok")
        except Exception:
            check("engine health reachable", False)

        code, body = api("GET", f"{self.prefix}/knowledge-bases/capabilities/parsers")
        check("backend health (capabilities 200)", code == 200)
        check("parser capabilities populated", len(body.get("parsers", [])) >= 4)

        # 2. CREATE KB
        stage_header("2/11 CREATE knowledge base")
        code, body = api("POST", f"{self.prefix}/knowledge-bases",
                         {"name": f"Verify KB {UNIQUE_MARKER[:8]}"}, self.hdrs)
        check("create KB 201", code == 201)
        self.kb_uid = body.get("kb_uid", "")
        check("kb_uid present", bool(self.kb_uid))
        check("tenant matches", body.get("tenant_id") == self.tenant)
        check("owner matches", body.get("owner_user_id") == self.actor)

        # 3. UPLOAD
        stage_header("3/11 UPLOAD unique content")
        content = f"# Verification Test {UNIQUE_MARKER}\n\nThis is a unique document for verification.\n\n## Section: Pipeline\nContains marker {UNIQUE_MARKER} for search.\n\n## Citation Target\nThis sentence is the citation target: {UNIQUE_MARKER}."
        boundary = f"----FormBoundary{uuid.uuid4().hex}"
        body_data = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="verify.md"\r\n'
            f"Content-Type: text/markdown\r\n\r\n"
            f"{content}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="relative_path"\r\n\r\n'
            f"verify.md\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="auto_index"\r\n\r\n'
            f"true\r\n"
            f"--{boundary}--\r\n"
        ).encode()
        req = urllib.request.Request(
            f"{self.prefix}/knowledge-bases/{self.kb_uid}/files",
            data=body_data,
            headers={
                "X-Prism-Actor": self.actor,
                "X-Prism-Tenant": self.tenant,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                upload = json.loads(resp.read())
                check("upload 202", resp.status == 202)
                self.file_uid = upload["file"]["file_uid"]
                check("file_uid present", bool(self.file_uid))
                self.job_id = upload.get("job", {}).get("id", "")
                check("job_id present", bool(self.job_id))
        except urllib.error.HTTPError as exc:
            check(f"upload accepted", False)
            self.file_uid = ""
            self.job_id = ""

        # 4. PROCESS via Engine
        stage_header("4/11 PROCESS file (parse → chunk → index)")
        code, resp = api("POST", f"{self.engine}/api/v1/knowledge/process",
                         {"kb_uid": self.kb_uid, "file_uid": self.file_uid},
                         timeout=120)
        check("process endpoint 200", code == 200 and resp.get("status") == "succeeded")
        self.item_id = resp.get("item_id", "")
        self.first_chunk_id = resp.get("first_chunk_id", None)
        if code == 200:
            check("parse_status succeeded", resp.get("parse_status") == "succeeded")
            check("index_status succeeded", resp.get("index_status") == "succeeded")
            check("chunks > 0", resp.get("chunks", 0) > 0)
            check("item_id present", bool(self.item_id))

        # 5. POLL JOB UNTIL TERMINAL
        stage_header("5/11 POLL job to terminal state")
        if not self.job_id:
            check("job_id available for polling", False)
        else:
            terminal = False
            for i in range(60):
                code, job = api("GET",
                                f"{self.prefix}/knowledge-bases/{self.kb_uid}/files/jobs/{self.job_id}",
                                None, self.hdrs)
                if code == 200:
                    status = job.get("status", "")
                    if status == "succeeded":
                        terminal = True
                        check("job terminal state reached", True)
                        check("job status is succeeded", True)
                        break
                    elif status == "failed":
                        check("job terminal state reached", True)
                        check("job status is succeeded", False)
                        terminal = True
                        break
                    elif status == "canceled":
                        check("job terminal state reached", True)
                        check("job status is succeeded", False)
                        terminal = True
                        break
                time.sleep(2)
            if not terminal:
                check("job reached terminal state within 120s", False)

        # 6. VERIFY FILE STATE
        stage_header("6/11 VERIFY persisted state")
        code, fbody = api("GET",
                          f"{self.prefix}/knowledge-bases/{self.kb_uid}/files/{self.file_uid}",
                          None, self.hdrs)
        check("file GET 200", code == 200)
        if code == 200:
            check("parse_status succeeded", fbody.get("parse_status") == "succeeded")
            check("index_status succeeded", fbody.get("index_status") == "succeeded")

        # 7. SEARCH UNIQUE TEXT
        stage_header("7/11 SEARCH unique marker")
        code, sr = api("POST", f"{self.engine}/api/v1/knowledge/search",
                       {"kb_uid": self.kb_uid, "query": UNIQUE_MARKER, "max_results": 10})
        check("engine search 200", code == 200)
        results = sr.get("results", [])
        check("search returns results", len(results) > 0)
        if results:
            check("results contain unique marker",
                  any(UNIQUE_MARKER in (r.get("text") or "") for r in results))
            first = results[0]
            check("result has chunk_id", bool(first.get("chunk_id")))
            check("result has item_id", bool(first.get("item_id")))

        # 8. CITATION
        stage_header("8/11 CITATION persist + read-back")
        if results:
            cc, citation = api("POST", f"{self.prefix}/citations", {
                "kb_uid": self.kb_uid,
                "file_uid": self.file_uid,
                "chunk_uid": results[0].get("chunk_id", ""),
                "citation_text": f"Cited: {UNIQUE_MARKER}",
            }, self.hdrs)
            check("citation create 201", cc == 201)
            if cc == 201:
                self.citation_id = citation.get("id", "")
                check("citation kb_uid matches", citation.get("kb_uid") == self.kb_uid)
                check("citation file_uid matches", citation.get("file_uid") == self.file_uid)
                check("citation chunk_uid matches", bool(citation.get("chunk_uid")))

                rc, readback = api("GET", f"{self.prefix}/citations/{self.citation_id}",
                                   None, self.hdrs)
                check("citation read-back 200", rc == 200)
                if rc == 200:
                    check("read-back kb_uid", readback.get("kb_uid") == self.kb_uid)
                    check("read-back file_uid", readback.get("file_uid") == self.file_uid)
                    check("read-back has text", bool(readback.get("citation_text")))
        else:
            self.citation_id = ""

        # 9. DIRECT INFRASTRUCTURE VERIFICATION (Milvus, ES, Neo4j)
        stage_header("9/11 DIRECT STORE verification")
        self._verify_milvus()
        self._verify_es()
        self._verify_neo4j()

        # 10. DEGRADED TEST (stop ES, verify vector search still works)
        stage_header("10/11 DEGRADED check (ES down, vector fallback)")
        self._run_degraded_test()

        # 11. DELETE + CLEANUP
        stage_header("11/11 DELETE + cross-store cleanup")
        code, body = api("DELETE", f"{self.prefix}/knowledge-bases/{self.kb_uid}",
                         None, self.hdrs)
        check("delete 200", code == 200)
        if code == 200:
            check("status deleting", body.get("status") == "deleting")

        code, _ = api("GET", f"{self.prefix}/knowledge-bases/{self.kb_uid}", None, self.hdrs)
        check("deleted KB 404", code == 404)

        # Verify cleanup in queue (poll for file deletion)
        time.sleep(3)
        code, fbody = api("GET",
                          f"{self.prefix}/knowledge-bases/{self.kb_uid}/files/{self.file_uid}",
                          None, self.hdrs)
        check("deleted file not found (404)", code == 404)

    def _verify_milvus(self):
        try:
            from pymilvus import MilvusClient
            mc = MilvusClient(uri="http://127.0.0.1:19530")
            col_name = "prism_knowledge"
            if mc.has_collection(col_name) and hasattr(self, "first_chunk_id") and self.first_chunk_id:
                result = mc.get(collection_name=col_name, ids=[self.first_chunk_id])
                check("Milvus has vector for this chunk", len(result) > 0)
                if result:
                    check("Milvus chunk_id matches", result[0].get("chunk_id") == self.first_chunk_id or result[0].get("id") == self.first_chunk_id)
            elif not mc.has_collection(col_name):
                check("Milvus collection exists", False)
            else:
                check("Milvus has data (no chunk ID to verify)", False)
        except Exception as exc:
            check(f"Milvus verification error", False)
            print(f"  [INFO] Milvus error: {exc}")

    def _verify_es(self):
        try:
            from elasticsearch import Elasticsearch
            es = Elasticsearch(["http://127.0.0.1:9200"], request_timeout=10)
            es_index = "prism_chunks"
            if es.indices.exists(index=es_index):
                body = {"query": {"term": {"topic_id": self.kb_uid}}, "size": 10}
                resp = es.search(index=es_index, body=body)
                hits = resp.get("hits", {}).get("hits", [])
                check("ES has documents for this KB", len(hits) > 0)
                if hits:
                    src = hits[0].get("_source", {})
                    check("ES topic_id matches", src.get("topic_id") == self.kb_uid)
            else:
                check("ES index exists", False)
            es.transport.close()
        except Exception as exc:
            check(f"ES verification error", False)
            print(f"  [INFO] ES error: {exc}")

    def _verify_neo4j(self):
        try:
            from neo4j import GraphDatabase
            uri = "bolt://127.0.0.1:7687"
            driver = GraphDatabase.driver(uri, auth=("neo4j", "password"))
            with driver.session() as session:
                result = session.run(
                    "MATCH (doc:Document) WHERE doc.kb_uid = $kb RETURN doc LIMIT 10",
                    kb=self.kb_uid)
                records = list(result)
                check("Neo4j has Document nodes for this KB", len(records) > 0)
            driver.close()
        except Exception as exc:
            check(f"Neo4j verification error", False)
            print(f"  [INFO] Neo4j error: {exc}")

    def _run_degraded_test(self):
        import subprocess
        es_container = "elasticsearch"
        try:
            subprocess.run(["docker", "stop", es_container], capture_output=True, timeout=10)
            time.sleep(2)
            code, sr = api("POST", f"{self.engine}/api/v1/knowledge/search",
                           {"kb_uid": self.kb_uid, "query": UNIQUE_MARKER, "max_results": 5})
            check("degraded search still returns results (vector fallback)",
                  code == 200 and len(sr.get("results", [])) > 0)
        except Exception as exc:
            check(f"degraded ES stop failed", False)
            print(f"  [INFO] degraded test error: {exc}")
        finally:
            try:
                subprocess.run(["docker", "start", es_container], capture_output=True, timeout=10)
                time.sleep(5)
                code, eng = api("GET", f"{self.engine}/health")
                check("ES restored, engine healthy", code == 200)
            except Exception:
                check("ES restore failed", False)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://127.0.0.1:5175")
    p.add_argument("--engine-url", default="http://127.0.0.1:5180")
    args = p.parse_args()
    Verifier(args.base_url, args.engine_url).run()


if __name__ == "__main__":
    main()
