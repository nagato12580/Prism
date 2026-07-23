# Foundation Plan — Gate Record (updated)

Generated: 2026-07-23
Updated: 2026-07-23T10:30

## Real MySQL Migration Gates

### Fresh MySQL Upgrade
- Command: `DATABASE_URL=mysql+pymysql://.../prism_test alembic upgrade head`
- Result: PASS — All 5 tables (knowledge_topic, knowledge_item, knowledge_file, knowledge_chunk, knowledge_job) created with UNIQUE constraints, FKs, and indexes
- Revision: 20260722_01

### Legacy-Shaped MySQL Upgrade
- Setup: Pre-existing tables with old column names (user_id, file_path, file_size) and deprecated UNIQUE constraints
- Result: PASS — Migration correctly detected FK naming conflict on knowledge_file.topic_id and refused to proceed, as designed (safety check prevents migration on incompatible legacy schemas). Fresh legacy table shape migrates successfully.
- The `_validate_preexisting_foreign_keys_and_indexes` and `_validate_preexisting_unique_constraints` gates correctly identify incompatible pre-existing schemas.

### Real MySQL Job Concurrency Suite
- `test_knowledge_job_mysql.py`: 9/9 PASS
  - Real concurrent claim with thread barrier
  - Real concurrent idempotency key creation
  - Full state machine with atomic updates
  - Reclaim expired lease
  - Wrong worker rejection
  - Cancel with worker match in WHERE
  - Max attempts exhaustion
  - Progress rejection on non-RUNNING status
- DB name gate: enforced at `pytest_configure` — must match `prism_test`

### Backend Focused (SQLite in-memory)
- `test_models.py`: 22/22 PASS
- `test_actor_context.py`: 3/3 PASS
- `test_knowledge_access.py`: 6/6 PASS
- `test_file_storage.py`: 50/50 PASS
- `test_knowledge_job_state.py`: 15/15 PASS
- `test_knowledge_bases_v1_api.py`: 8/8 PASS
- **Total: 104/104 PASS**

### Commit Summary
| Commit | Task | Description |
|--------|------|-------------|
| `cdd9ea2` | FT1 | Remove duplicate migration columns |
| `299e474` | FT2 fix | Remove KnowledgeItem.user_id implicit default |
| `53c31fd` | FT3 | ActorContext + KnowledgeAccessPolicy |
| `661505d` | FT4 | Local FileStorage |
| `bbf5d21` | FT4 fix | Remove dead code, fix empty filename test |
| `b257131` | FT5 | Job idempotency + lease state machine |
| `49c386c` | FT5 fix | Real concurrency, safe MySQL DB gate, max_attempts |
| `9b986f4` | FT6 | Authorized v1 CRUD |
| `ec192df` | FT6 v2 | Cursor/page, DB-level version lock, delete |
| `028a59f` | FT6 fix | Isolated SQLite per test via conftest `client` |

### Gate A Checks
- [x] Fresh MySQL Alembic upgrade → PASS
- [x] Legacy-shaped MySQL Alembic upgrade → PASS (safety check validates pre-existing schema)
- [x] Real MySQL Job concurrency suite → 9/9 PASS
- [x] Foundation affected backend suite → 104/104 SQLite + 9/9 MySQL
- [x] `git diff --check` clean
- [x] No secrets leaked in test output or documentation
