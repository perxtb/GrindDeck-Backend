import hmac, hashlib, json, time, sqlite3, os
from urllib.parse import parse_qsl
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

BOT_TOKEN = os.environ.get("BOT_TOKEN", "ТВОЙ_ТОКЕН_СЮДА")
DB = "/data/mtt.db"
os.makedirs("/data", exist_ok=True)

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

with db() as c:
    c.executescript("""
    CREATE TABLE IF NOT EXISTS state(
      tg_id INTEGER PRIMARY KEY,
      username TEXT, first_name TEXT,
      mtt1 TEXT, tours_idx TEXT, hall TEXT, camp TEXT, daily TEXT, settings TEXT,
      updated_at INTEGER
    );
    CREATE TABLE IF NOT EXISTS tours(
      tg_id INTEGER, tour_id INTEGER,
      name TEXT, kind TEXT, opp TEXT, n INTEGER, prize INTEGER,
      place INTEGER, hands INTEGER, state TEXT, updated_at INTEGER,
      PRIMARY KEY(tg_id, tour_id)
    );
    CREATE TABLE IF NOT EXISTS stats(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      tg_id INTEGER, ts INTEGER, mode TEXT, phase TEXT,
      pos TEXT, stack INTEGER, scenario TEXT,
      action TEXT, gto TEXT, ok INTEGER, hand TEXT,
      UNIQUE(tg_id, ts, hand, pos, action)
    );
    CREATE INDEX IF NOT EXISTS i_stats_user ON stats(tg_id, mode, phase);
    """)

def validate(init_data: str) -> dict:
    p = dict(parse_qsl(init_data, keep_blank_values=True))
    got = p.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(p.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, got):
        raise HTTPException(401, "bad initData")
    if time.time() - int(p.get("auth_date", 0)) > 86400:
        raise HTTPException(401, "expired")
    return json.loads(p["user"])

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class Sync(BaseModel):
    initData: str
    mtt1: str | None = None
    idx: str | None = None
    hall: str | None = None
    camp: str | None = None
    daily: str | None = None
    settings: str | None = None
    tours: dict[str, str] = {}

class Who(BaseModel):
    initData: str

@app.post("/api/sync")
def sync(p: Sync):
    u = validate(p.initData)
    tg_id = u["id"]
    with db() as c:
        c.execute("""INSERT INTO state(tg_id,username,first_name,mtt1,tours_idx,hall,camp,daily,settings,updated_at)
                     VALUES(?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(tg_id) DO UPDATE SET
                       username=excluded.username, first_name=excluded.first_name,
                       mtt1=excluded.mtt1, tours_idx=excluded.tours_idx,
                       hall=excluded.hall, camp=excluded.camp,
                       daily=excluded.daily, settings=excluded.settings,
                       updated_at=excluded.updated_at""",
                  (tg_id, u.get("username"), u.get("first_name"), p.mtt1, p.idx, p.hall, p.camp, p.daily, p.settings, int(time.time())))
        if p.mtt1:
            data = json.loads(p.mtt1)
            for e in data.get("stats", []):
                c.execute("""INSERT OR IGNORE INTO stats (tg_id,ts,mode,phase,pos,stack,scenario,action,gto,ok,hand)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                          (tg_id, e.get("ts"), e.get("m"), e.get("ph"), e.get("pos"), e.get("st"), e.get("sc"), e.get("a"), e.get("g"), 1 if e.get("ok") else 0, e.get("h")))
        for tid, raw in p.tours.items():
            if not raw: continue
            t = json.loads(raw)
            if not t: continue
            res = t.get("res") or {}
            c.execute("""INSERT OR REPLACE INTO tours (tg_id,tour_id,name,kind,opp,n,prize,place,hands,state,updated_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                      (tg_id, int(tid), t.get("name"), t.get("kind"), t.get("opp"), t.get("n"), t.get("prize"), res.get("place"), t.get("hands"), raw, int(time.time())))
    return {"ok": True}

@app.post("/api/load")
def load(p: Who):
    u = validate(p.initData)
    tg_id = u["id"]
    with db() as c:
        row = c.execute("SELECT * FROM state WHERE tg_id=?", (tg_id,)).fetchone()
        tours = c.execute("SELECT tour_id, state FROM tours WHERE tg_id=?", (tg_id,)).fetchall()
        if not row:
            return {"empty": True}
        return {
            "mtt1": row["mtt1"], "idx": row["tours_idx"], "hall": row["hall"], "camp": row["camp"],
            "daily": row["daily"], "settings": row["settings"],
            "tours": {str(t["tour_id"]): t["state"] for t in tours}
        }

@app.get("/api/health")
def health():
    return {"ok": True}