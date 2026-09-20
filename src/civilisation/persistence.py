"""Persistence: metrics, events, thoughts, decrees, residents and world snapshots.

Two backends behind one interface:
  - SupabaseStore  — when SUPABASE_URL and SUPABASE_SERVICE_KEY are set (production, Railway)
  - SQLiteStore    — otherwise, a local file (dev), same tables

Visitors' API keys are encrypted with APP_SECRET (Fernet) before they are stored, and
decrypted only in server memory when a village is restored. Without APP_SECRET, keys are
not persisted at all (residents come back with the rules brain).
"""
from __future__ import annotations
import base64
import hashlib
import io
import json
import os
import pickle
import sqlite3
import threading
import time
from dataclasses import asdict
from typing import Optional

SCHEMA_SQL = """
create table if not exists metrics  (village text, day integer, data jsonb, primary key (village, day));
create table if not exists events   (id bigserial primary key, village text, day integer, category text, importance real, text text, brain text, actors jsonb, created timestamptz default now());
create table if not exists thoughts (id bigserial primary key, village text, day integer, citizen_id integer, name text, text text, emotion text, source text, created timestamptz default now());
create table if not exists decrees  (id bigserial primary key, village text, day integer, session text, sponsor text, text text, narration text, effects jsonb, created timestamptz default now());
create table if not exists residents(village text, citizen_id integer, name text, sponsor text, provider text, model text, base_url text, enc_key text, max_calls integer, token_hash text, notes text, created timestamptz default now(), primary key (village, citizen_id));
alter table residents add column if not exists token_hash text;
alter table residents add column if not exists notes text;
create table if not exists snapshots(village text primary key, day integer, blob bytea, updated timestamptz default now());
create index if not exists events_village_day on events (village, day desc);
create index if not exists thoughts_village_day on thoughts (village, day desc);
alter table metrics enable row level security;  alter table events enable row level security;  alter table thoughts enable row level security;
alter table decrees enable row level security;  alter table residents enable row level security; alter table snapshots enable row level security;
-- no policies: only the service-role key (server side) can read or write.
"""


# ---------------------------------------------------------------- key encryption
def _fernet():
    secret = os.environ.get("APP_SECRET")
    if not secret:
        return None
    from cryptography.fernet import Fernet
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def encrypt_key(key: str) -> Optional[str]:
    f = _fernet()
    return f.encrypt(key.encode()).decode() if (f and key) else None


def decrypt_key(token: Optional[str]) -> Optional[str]:
    f = _fernet()
    if not (f and token):
        return None
    try:
        return f.decrypt(token.encode()).decode()
    except Exception:
        return None


# ---------------------------------------------------------------- store interface
class Store:
    name = "none"

    def update_resident(self, village, citizen_id, **fields): ...

    def write_metrics(self, village, rows): ...
    def write_events(self, village, rows): ...
    def write_thoughts(self, village, rows): ...
    def write_decree(self, village, row): ...
    def write_resident(self, village, row): ...
    def read_residents(self, village): return []
    def write_snapshot(self, village, day, blob: bytes): ...
    def read_snapshot(self, village): return None
    def read_events(self, village, limit=500, min_importance=0.0): return []
    def read_metrics(self, village, limit=2000): return []
    def read_decrees(self, village, limit=200): return []
    def read_thoughts(self, village, limit=200): return []
    def status(self) -> str: return self.name


class NullStore(Store):
    pass


class SQLiteStore(Store):
    name = "sqlite"

    def __init__(self, path: str):
        self.path = path
        self.lock = threading.Lock()
        with self._conn() as c:
            c.executescript("""
            create table if not exists metrics  (village text, day integer, data text, primary key (village, day));
            create table if not exists events   (id integer primary key autoincrement, village text, day integer, category text, importance real, text text, brain text, actors text);
            create table if not exists thoughts (id integer primary key autoincrement, village text, day integer, citizen_id integer, name text, text text, emotion text, source text);
            create table if not exists decrees  (id integer primary key autoincrement, village text, day integer, session text, sponsor text, text text, narration text, effects text);
            create table if not exists residents(village text, citizen_id integer, name text, sponsor text, provider text, model text, base_url text, enc_key text, max_calls integer, token_hash text, notes text, primary key (village, citizen_id));
            create table if not exists snapshots(village text primary key, day integer, blob blob);
            """)
            for col in ("token_hash", "notes"):
                try:
                    c.execute(f"alter table residents add column {col} text")
                except sqlite3.OperationalError:
                    pass

    def _conn(self):
        return sqlite3.connect(self.path, timeout=10)

    def write_metrics(self, village, rows):
        with self.lock, self._conn() as c:
            c.executemany("insert or replace into metrics values (?,?,?)", [(village, r["day"], json.dumps(r)) for r in rows])

    def write_events(self, village, rows):
        with self.lock, self._conn() as c:
            c.executemany("insert into events (village, day, category, importance, text, brain, actors) values (?,?,?,?,?,?,?)",
                          [(village, r["day"], r["category"], r["importance"], r["text"], r["brain"], json.dumps(r["actors"])) for r in rows])

    def write_thoughts(self, village, rows):
        with self.lock, self._conn() as c:
            c.executemany("insert into thoughts (village, day, citizen_id, name, text, emotion, source) values (?,?,?,?,?,?,?)",
                          [(village, r["day"], r["cid"], r["name"], r["text"], r["emotion"], r["source"]) for r in rows])

    def write_decree(self, village, row):
        with self.lock, self._conn() as c:
            c.execute("insert into decrees (village, day, session, sponsor, text, narration, effects) values (?,?,?,?,?,?,?)",
                      (village, row["day"], row.get("session", ""), row.get("sponsor", ""), row["text"], row["narration"], json.dumps(row["done"])))

    RES_COLS = ["citizen_id", "name", "sponsor", "provider", "model", "base_url", "enc_key", "max_calls", "token_hash", "notes"]

    def write_resident(self, village, row):
        with self.lock, self._conn() as c:
            c.execute("insert or replace into residents (village, citizen_id, name, sponsor, provider, model, base_url, enc_key, max_calls, token_hash, notes) values (?,?,?,?,?,?,?,?,?,?,?)",
                      (village, row["citizen_id"], row["name"], row["sponsor"], row["provider"], row["model"], row.get("base_url"), row.get("enc_key"), row["max_calls"], row.get("token_hash"), row.get("notes")))

    def read_residents(self, village):
        with self._conn() as c:
            cur = c.execute(f"select {', '.join(self.RES_COLS)} from residents where village=?", (village,))
            return [dict(zip(self.RES_COLS, r)) for r in cur.fetchall()]

    def update_resident(self, village, citizen_id, **fields):
        fields = {k: v for k, v in fields.items() if k in self.RES_COLS}
        if not fields:
            return
        with self.lock, self._conn() as c:
            c.execute(f"update residents set {', '.join(k + '=?' for k in fields)} where village=? and citizen_id=?", (*fields.values(), village, citizen_id))

    def write_snapshot(self, village, day, blob):
        from .security import sign_blob
        with self.lock, self._conn() as c:
            c.execute("insert or replace into snapshots values (?,?,?)", (village, day, sign_blob(blob)))

    def read_snapshot(self, village):
        with self._conn() as c:
            r = c.execute("select blob from snapshots where village=?", (village,)).fetchone()
            return r[0] if r else None

    def read_events(self, village, limit=500, min_importance=0.0):
        with self._conn() as c:
            cur = c.execute("select day, category, importance, text, brain from events where village=? and importance>=? order by day desc, id desc limit ?", (village, min_importance, limit))
            return [dict(zip(["day", "category", "importance", "text", "brain"], r)) for r in cur.fetchall()]

    def read_metrics(self, village, limit=2000):
        with self._conn() as c:
            cur = c.execute("select data from metrics where village=? order by day desc limit ?", (village, limit))
            return [json.loads(r[0]) for r in cur.fetchall()][::-1]

    def read_decrees(self, village, limit=200):
        with self._conn() as c:
            cur = c.execute("select day, session, sponsor, text, narration, effects from decrees where village=? order by id desc limit ?", (village, limit))
            return [dict(zip(["day", "session", "sponsor", "text", "narration", "effects"], r)) for r in cur.fetchall()]

    def read_thoughts(self, village, limit=200):
        with self._conn() as c:
            cur = c.execute("select day, name, text, emotion, source from thoughts where village=? order by id desc limit ?", (village, limit))
            return [dict(zip(["day", "name", "text", "emotion", "source"], r)) for r in cur.fetchall()]

    def status(self):
        return f"sqlite ({os.path.basename(self.path)})"


class SupabaseStore(Store):
    name = "supabase"

    def __init__(self, url: str, key: str):
        from supabase import create_client
        self.client = create_client(url, key)
        self.url = url

    def _chunks(self, rows, n=200):
        for i in range(0, len(rows), n):
            yield rows[i:i + n]

    def write_metrics(self, village, rows):
        for ch in self._chunks([{"village": village, "day": r["day"], "data": r} for r in rows]):
            self.client.table("metrics").upsert(ch).execute()

    def write_events(self, village, rows):
        for ch in self._chunks([{"village": village, "day": r["day"], "category": r["category"], "importance": r["importance"], "text": r["text"], "brain": r["brain"], "actors": r["actors"]} for r in rows]):
            self.client.table("events").insert(ch).execute()

    def write_thoughts(self, village, rows):
        for ch in self._chunks([{"village": village, "day": r["day"], "citizen_id": r["cid"], "name": r["name"], "text": r["text"], "emotion": r["emotion"], "source": r["source"]} for r in rows]):
            self.client.table("thoughts").insert(ch).execute()

    def write_decree(self, village, row):
        self.client.table("decrees").insert({"village": village, "day": row["day"], "session": row.get("session", ""), "sponsor": row.get("sponsor", ""),
                                             "text": row["text"], "narration": row["narration"], "effects": row["done"]}).execute()

    RES_COLS = ["citizen_id", "name", "sponsor", "provider", "model", "base_url", "enc_key", "max_calls", "token_hash", "notes"]

    def write_resident(self, village, row):
        self.client.table("residents").upsert({"village": village, **{k: row.get(k) for k in self.RES_COLS}}).execute()

    def read_residents(self, village):
        return self.client.table("residents").select(",".join(self.RES_COLS)).eq("village", village).execute().data or []

    def update_resident(self, village, citizen_id, **fields):
        fields = {k: v for k, v in fields.items() if k in self.RES_COLS}
        if fields:
            self.client.table("residents").update(fields).eq("village", village).eq("citizen_id", citizen_id).execute()

    def write_snapshot(self, village, day, blob):
        from .security import sign_blob
        self.client.table("snapshots").upsert({"village": village, "day": day, "blob": "\\x" + sign_blob(blob).hex()}).execute()

    def read_snapshot(self, village):
        r = self.client.table("snapshots").select("blob").eq("village", village).execute().data
        if not r:
            return None
        b = r[0]["blob"]
        if isinstance(b, str):
            return bytes.fromhex(b[2:]) if b.startswith("\\x") else base64.b64decode(b)
        return bytes(b)

    def read_events(self, village, limit=500, min_importance=0.0):
        return self.client.table("events").select("day,category,importance,text,brain").eq("village", village).gte("importance", min_importance).order("day", desc=True).order("id", desc=True).limit(limit).execute().data or []

    def read_metrics(self, village, limit=2000):
        rows = self.client.table("metrics").select("data").eq("village", village).order("day", desc=True).limit(limit).execute().data or []
        return [r["data"] for r in rows][::-1]

    def read_decrees(self, village, limit=200):
        return self.client.table("decrees").select("day,session,sponsor,text,narration,effects").eq("village", village).order("id", desc=True).limit(limit).execute().data or []

    def read_thoughts(self, village, limit=200):
        return self.client.table("thoughts").select("day,name,text,emotion,source").eq("village", village).order("id", desc=True).limit(limit).execute().data or []

    def status(self):
        return f"supabase ({self.url.split('//')[-1].split('.')[0]})"


def get_store(local_path: str = "data/newhaven.db") -> Store:
    os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if url and key:
        try:
            return SupabaseStore(url, key)
        except Exception as e:  # fall back rather than take the app down
            print(f"[persistence] supabase unavailable ({e}); using sqlite")
    return SQLiteStore(local_path)


# ---------------------------------------------------------------- recorder: hooks a world to a store
class Recorder:
    """Call `flush(world)` from the ticker; it writes only what is new since last time. Errors never propagate."""

    def __init__(self, store: Store, village: str, snapshot_every: int = 30):
        self.store, self.village, self.snapshot_every = store, village, snapshot_every
        self.events_seen = 0
        self.thoughts_seen = 0
        self.metrics_day = -1
        self.last_snapshot_day = -1
        self.last_error = ""
        self.writes = 0

    def prime(self, world):
        """Start from the world's current position (after a restore) so history isn't duplicated."""
        self.events_seen = getattr(world, "events_total", len(world.events))
        self.thoughts_seen = getattr(world, "thoughts_total", len(world.thoughts))
        self.metrics_day = world.history[-1]["day"] if world.history else -1
        self.last_snapshot_day = world.day

    def flush(self, world, force_snapshot: bool = False):
        try:
            total = getattr(world, "events_total", len(world.events))
            if total > self.events_seen:
                new = world.events[-(total - self.events_seen):]
                self.store.write_events(self.village, [asdict(e) for e in new])
                self.events_seen = total
            ttotal = getattr(world, "thoughts_total", len(world.thoughts))
            if ttotal > self.thoughts_seen:
                self.store.write_thoughts(self.village, world.thoughts[-(ttotal - self.thoughts_seen):])
                self.thoughts_seen = ttotal
            rows = [r for r in world.history if r["day"] > self.metrics_day]
            if rows:
                self.store.write_metrics(self.village, rows)
                self.metrics_day = rows[-1]["day"]
            if force_snapshot or world.day - self.last_snapshot_day >= self.snapshot_every:
                buf = io.BytesIO()
                brain, brains, lock = world.brain, world.brains, world.lock
                world.brain, world.brains, world.lock = None, {}, None
                try:
                    pickle.dump(world, buf)
                finally:
                    world.brain, world.brains, world.lock = brain, brains, lock
                self.store.write_snapshot(self.village, world.day, buf.getvalue())
                self.last_snapshot_day = world.day
            self.writes += 1
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"[:200]


def restore_world(store: Store, village: str):
    """Load the last snapshot of a village, or None."""
    blob = store.read_snapshot(village)
    if not blob:
        return None
    from .brains import RulesBrain
    from .security import verify_blob
    w = pickle.load(io.BytesIO(verify_blob(blob)))
    w.brain = RulesBrain()
    w.brains = {}
    w.lock = threading.RLock()
    return w


def token_hash(token: str) -> str:
    return hashlib.sha256(("nh:" + token).encode()).hexdigest()
