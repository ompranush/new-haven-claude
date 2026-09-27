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
import time
import gzip
import sqlite3
import threading
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
-- No policies are defined, so RLS denies everything to the browser-facing roles.

-- The server uses the service_role key only; grant it explicitly so the project can keep
-- "Automatically expose new tables" switched off.
grant usage on schema public to service_role;
grant all privileges on all tables in schema public to service_role;
grant all privileges on all sequences in schema public to service_role;
alter default privileges in schema public grant all on tables to service_role;
alter default privileges in schema public grant all on sequences to service_role;

-- Nothing at all for anon / authenticated, now or in future.
revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
alter default privileges in schema public revoke all on tables from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;
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
    def transfer_resident(self, village, old_id, new_id, name): ...

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

    def transfer_resident(self, village, old_id, new_id, name):
        """Carry a claim token (and its settings) over to the heir."""
        with self.lock, self._conn() as c:
            cols = ", ".join(self.RES_COLS)
            row = c.execute(f"select {cols} from residents where village=? and citizen_id=?", (village, old_id)).fetchone()
            if not row:
                return
            d = dict(zip(self.RES_COLS, row))
            d["citizen_id"], d["name"] = new_id, name
            c.execute(f"insert or replace into residents (village, {cols}) values (?,?,?,?,?,?,?,?,?,?,?)",
                      (village, *[d[k] for k in self.RES_COLS]))
            c.execute("delete from residents where village=? and citizen_id=?", (village, old_id))

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

    def transfer_resident(self, village, old_id, new_id, name):
        rows = self.client.table("residents").select(",".join(self.RES_COLS)).eq("village", village).eq("citizen_id", old_id).execute().data
        if not rows:
            return
        d = dict(rows[0])
        d["citizen_id"], d["name"] = new_id, name
        self.client.table("residents").upsert({"village": village, **d}).execute()
        self.client.table("residents").delete().eq("village", village).eq("citizen_id", old_id).execute()

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
    """Call `flush(world)` from the ticker; it writes only what is new, and only as often as the
    intervals allow. A simulation can run far faster than a database should be written to, so both
    the row writes and the (compressed) snapshots are paced by wall-clock seconds. Errors never propagate."""

    def __init__(self, store: Store, village: str, snapshot_every: int = 30,
                 write_interval: float = 30.0, snapshot_interval: float = 900.0, max_snapshot_mb: float = 8.0,
                 min_importance: float = 0.0):
        self.store, self.village, self.snapshot_every = store, village, snapshot_every
        self.write_interval = write_interval
        self.snapshot_interval = snapshot_interval
        self.max_snapshot_mb = max_snapshot_mb
        self.min_importance = min_importance      # 0 keeps every event; raise it only to save space
        self.dropped = 0                          # rows lost to buffer overflow (should always be 0)
        self.events_seen = 0
        self.thoughts_seen = 0
        self.metrics_day = -1
        self.last_snapshot_day = -1
        self.last_write_at = 0.0
        self.last_snapshot_at = 0.0
        self.last_snapshot_mb = 0.0
        self.last_error = ""
        self.writes = 0
        self.snapshots = 0
        self.skipped = 0

    def prime(self, world, restored: bool = True):
        """Set the starting point. After a restore, skip what the store already has. For a brand-new
        village, start from zero so even its founding moment is recorded."""
        if restored:
            self.events_seen = getattr(world, "events_total", len(world.events))
            self.thoughts_seen = getattr(world, "thoughts_total", len(world.thoughts))
            hist = getattr(world, "realm_history", None) or world.history
            self.metrics_day = hist[-1]["day"] if hist else -1
        else:
            self.events_seen = self.thoughts_seen = 0
            self.metrics_day = -1
        self.last_snapshot_day = world.day
        self.last_write_at = self.last_snapshot_at = time.time()

    def flush(self, world, force_snapshot: bool = False):
        now = time.time()
        if not force_snapshot and now - self.last_write_at < self.write_interval:
            self.skipped += 1
            return
        self.last_write_at = now
        try:
            total = getattr(world, "events_total", len(world.events))
            if total > self.events_seen:
                want = total - self.events_seen
                if want > len(world.events):                 # the rolling window wrapped before we got here
                    self.dropped += want - len(world.events)
                    self.last_error = (f"{self.dropped} events scrolled out of memory before they were stored — "
                                       f"lower WRITE_INTERVAL_SECONDS or TICK_SECONDS")
                new = world.events[-min(want, len(world.events)):]
                if self.min_importance > 0:
                    new = [e for e in new if e.importance >= self.min_importance]
                if new:
                    self.store.write_events(self.village, [asdict(e) for e in new])
                self.events_seen = total
            ttotal = getattr(world, "thoughts_total", len(world.thoughts))
            if ttotal > self.thoughts_seen:
                want = ttotal - self.thoughts_seen
                if want > len(world.thoughts):
                    self.dropped += want - len(world.thoughts)
                    self.last_error = (f"{self.dropped} inner voices scrolled out of memory before they were stored — "
                                       f"lower WRITE_INTERVAL_SECONDS or TICK_SECONDS")
                self.store.write_thoughts(self.village, world.thoughts[-min(want, len(world.thoughts)):])
                self.thoughts_seen = ttotal
            rows = [r for r in (getattr(world, "realm_history", None) or world.history) if r["day"] > self.metrics_day]
            if rows:
                self.store.write_metrics(self.village, rows)
                self.metrics_day = rows[-1]["day"]
            due = world.day - self.last_snapshot_day >= self.snapshot_every and now - self.last_snapshot_at >= self.snapshot_interval
            if force_snapshot or due:
                blob = gzip.compress(self._dump(world), 6)
                self.last_snapshot_mb = len(blob) / 1e6
                if self.last_snapshot_mb > self.max_snapshot_mb:
                    self.last_error = (f"snapshot is {self.last_snapshot_mb:.1f} MB (limit {self.max_snapshot_mb} MB) — not stored. "
                                       f"Raise MAX_SNAPSHOT_MB or let the world prune further.")
                else:
                    self.store.write_snapshot(self.village, world.day, blob)
                    self.last_snapshot_day = world.day
                    self.last_snapshot_at = now
                    self.snapshots += 1
            self.writes += 1
        except Exception as e:
            from .security import scrub
            self.last_error = scrub(f"{type(e).__name__}: {e}")

    @staticmethod
    def _dump(world) -> bytes:
        buf = io.BytesIO()
        brain, brains, lock = world.brain, world.brains, world.lock
        world.brain, world.brains, world.lock = None, {}, None
        try:
            pickle.dump(world, buf)
        finally:
            world.brain, world.brains, world.lock = brain, brains, lock
        return buf.getvalue()

    def stats(self) -> dict:
        return {"writes": self.writes, "snapshots": self.snapshots, "throttled": self.skipped, "dropped": self.dropped,
                "last_snapshot_mb": round(self.last_snapshot_mb, 2), "last_error": self.last_error}


def restore_world(store: Store, village: str):
    """Load the last snapshot of a village, or None."""
    blob = store.read_snapshot(village)
    if not blob:
        return None
    from .brains import RulesBrain
    from .security import verify_blob
    raw = verify_blob(blob)
    if raw[:2] == b"\x1f\x8b":          # gzip magic — snapshots written since compression was added
        raw = gzip.decompress(raw)
    w = pickle.load(io.BytesIO(raw))
    w.brain = RulesBrain()
    w.brains = {}
    w.lock = threading.RLock()
    return w


def token_hash(token: str) -> str:
    return hashlib.sha256(("nh:" + token).encode()).hexdigest()


def migrate_single_village(store: Store, village: str, old, seed: int = 2026, population: int = 300, era: str = "medieval"):
    """v0.2 → v0.3: the old single village becomes the five-village realm.

    The old save is kept under `<village>-v02-backup`. Every living adopted person is carried across into the
    village whose temperament suits them best, keeping their name, story, money, skills, goal and recent
    memories; their resident row (claim token, stored key) is moved to their new id, so tokens keep working.
    Returns (world, number carried across)."""
    from .world import World
    from .realm import ELEMENTS
    from .security import verify_blob
    try:
        blob = store.read_snapshot(village)
        if blob:
            store.write_snapshot(f"{village}-v02-backup", getattr(old, "day", 0), verify_blob(blob))
    except Exception:
        pass
    w = World(seed=seed, population=population, name="New Haven", config={"era": era})
    moved = 0
    rows = {int(r["citizen_id"]): r for r in store.read_residents(village)}
    for oc in list(old.citizens.values()):
        if not getattr(oc, "sponsor", "") or not oc.alive:
            continue
        p = dict(oc.personality)
        # the village whose temper leans the way they do
        best = max(w.villages, key=lambda v: sum(d * (p.get(k, 0.5) - 0.5) for k, d in ELEMENTS[v.element]["temper"].items()))
        age = max(18, (old.day - oc.born_day) // 365)
        c = w.adopt(oc.name, oc.sex, age, p, backstory=getattr(oc, "backstory", ""), sponsor=oc.sponsor, money=float(oc.money), village=best.idx)
        c.skill, c.education, c.goal, c.happiness = oc.skill, oc.education, oc.goal, oc.happiness
        c.memories = list(oc.memories[-30:])
        c.remember(w.day, f"The old town is gone. I've made a new start in {best.name}, the {best.element} village.", "hope", 0.9, tag="life")
        if oc.id in rows:
            store.transfer_resident(village, oc.id, c.id, c.name)
        moved += 1
    return w, moved
