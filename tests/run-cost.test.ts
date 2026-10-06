import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { test } from "node:test";

test("memo spend decodes compressed calls through the shipped Agent Index client", () => {
  const result = execFileSync("/opt/plow/pt-venv/bin/python3", ["-c", `
import ctypes, ctypes.util, json, os, sqlite3, sys, tempfile
from pathlib import Path
sys.path.insert(0, '/opt/plow/skills/memo-shared/scripts')
import run_cost
with tempfile.TemporaryDirectory() as root:
    os.environ['OPENCLAW_STATE_DIR'] = root
    store = Path(root) / 'agents/main/agent/openclaw-agent.sqlite'
    store.parent.mkdir(parents=True)
    event = {'timestamp': '2026-10-01T01:00:00Z', 'message': {'role': 'assistant',
        'provider': 'plow', 'model': 'writer', 'responseId': 'first',
        'usage': {'input': 1000000, 'output': 0}}}
    raw = json.dumps(event).encode()
    zstd = ctypes.CDLL(ctypes.util.find_library('zstd'))
    zstd.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
    zstd.ZSTD_compressBound.restype = ctypes.c_size_t
    zstd.ZSTD_compress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int]
    zstd.ZSTD_compress.restype = ctypes.c_size_t
    buffer = ctypes.create_string_buffer(zstd.ZSTD_compressBound(len(raw)))
    length = zstd.ZSTD_compress(buffer, len(buffer), raw, len(raw), 1)
    with sqlite3.connect(store) as db:
        db.execute('CREATE TABLE transcript_events (session_id TEXT, event_json TEXT, event_zstd BLOB, event_utf8_bytes INTEGER, created_at INTEGER)')
        db.execute('INSERT INTO transcript_events VALUES (?, NULL, ?, ?, ?)', ('resumed', buffer.raw[:length], len(raw), 1790816400000))
        event['message']['responseId'] = 'second'
        db.execute('INSERT INTO transcript_events VALUES (?, ?, NULL, NULL, ?)', ('resumed', json.dumps(event), 1790816400000))
    rows = run_cost.events(1790816400000, 1790816400001)
    result = run_cost.summary(rows, {'writer': {'input': 5, 'output': 25}})
    assert result == {'usd': 10.0, 'sessions': 1, 'unpriced': 0}, result
    # The same real decoder must refuse corruption rather than returning a partial sum.
    with sqlite3.connect(store) as db:
        db.execute('UPDATE transcript_events SET event_zstd = ? WHERE event_zstd IS NOT NULL', (b'bad zstd',))
    try:
        run_cost.events(1790816400000, 1790816400001)
        raise AssertionError('corrupt compressed usage was accepted')
    except RuntimeError:
        pass
    print(json.dumps(result))
`], { encoding: "utf8" });
  assert.deepEqual(JSON.parse(result), { usd: 10, sessions: 1, unpriced: 0 });
});
