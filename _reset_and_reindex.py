"""Reset data and re-index 6 papers with new chunk size."""
from dotenv import load_dotenv; load_dotenv('.env')
import os, sys, uuid
sys.path.insert(0, '.')

from sqlalchemy import create_engine, text
from engine.app.ingestion.pipeline import ingest_item
from pymilvus import connections, Collection
import time

PAPER_IDS = [
    'c5f89f1f-fd12-4a0c-8f89-171696a0a620',
    '3f11ebc6-896d-4150-afe4-57464e395c23',
    '397509cf-25ad-4fd3-b53c-5af2e1af1ebf',
    '430254e3-cf42-4d7d-9906-0f25669c97e5',
    '91be4c32-d302-4b31-aaad-3616bc00c4be',
    'c1bb57c9-57d1-483e-a574-131a11c669ba',
]
KB_UID = '9141b989-ee70-42f7-bcd3-c2c5ffed68db'

engine = create_engine(os.environ['DATABASE_URL'], pool_pre_ping=True)
db = engine.connect()

# Step 1: Clean old chunks
total = 0
for pid in PAPER_IDS:
    total += db.execute(text('DELETE FROM knowledge_chunk WHERE item_id=:id'), {'id': pid}).rowcount

# Step 2: New generation
new_gen = str(uuid.uuid4())
db.execute(text('UPDATE knowledge_topic SET active_index_generation=:g WHERE kb_uid=:k'),
           {'g': new_gen, 'k': KB_UID})
db.commit()
print(f'Cleaned {total} chunks, new generation: {new_gen}')

# Step 3: Re-ingest
for i, pid in enumerate(PAPER_IDS):
    t0 = time.time()
    n = ingest_item(pid)
    print(f'[{i+1}/6] Ingested {pid[:8]} -> {n} children ({time.time()-t0:.0f}s)')

# Step 4: Copy vectors between Milvus collections
connections.connect('default', host='localhost', port='19530')
src = Collection('prism_knowledge'); src.load(timeout=10)
dst = Collection('prism_kb_26b71d12b026785d'); dst.load(timeout=10)

rows = db.execute(text(
    "SELECT kc.id,kc.item_id,kc.chunk_text,kc.kb_uid,kf.file_uid,kf.media_type "
    "FROM knowledge_chunk kc LEFT JOIN knowledge_file kf ON kf.item_id=kc.item_id "
    "WHERE kc.chunk_type='child' AND kc.kb_uid=:kb"
), {'kb': KB_UID}).fetchall()

src_rows = src.query(expr='', output_fields=['chunk_id','embedding'], limit=2000)
emb_map = {r['chunk_id']: r['embedding'] for r in src_rows}

ts = str(int(time.time()))
payload = []
for r in rows:
    if r.id not in emb_map:
        continue
    payload.append({
        'id': f'{r.id}:{new_gen}',
        'tenant_id': 'default-user', 'kb_uid': r.kb_uid,
        'file_uid': r.file_uid or r.id, 'item_id': r.item_id,
        'chunk_uid': r.id, 'source_type': r.media_type or 'document',
        'generation': new_gen, 'embedding_model_version': 'bge-m3',
        'indexed_at': ts, 'content': (r.chunk_text or '')[:200],
        'embedding': emb_map[r.id],
    })

if payload:
    dst.insert(payload, timeout=60)
    print(f'Copied {len(payload)} vectors to retrieval collection')

db.close()
print(f'\nDONE. New generation: {new_gen}')
