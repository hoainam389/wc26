"""World Cup 2026 vote & stats — nmquan.vn/wc26

Standalone page: 6 accounts log in, vote Asian-handicap picks for the day's
matches; an Overview ("Bảng tổng") shows points, accuracy and charts.

Self-contained auth (separate from the site's /private auth) + JSON storage in
/root/apps/dashboard/wc26_data/ (runtime data, never overwritten by deploys).
"""
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter()

# ── Storage ─────────────────────────────────────────────────────────────────
# Paths resolve relative to this file so the project runs from anywhere
# (the original deployment hard-coded /root/apps/dashboard/...).
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "wc26_data"
USERS_FILE = DATA_DIR / "users.json"
MATCHES_FILE = DATA_DIR / "matches.json"
VOTES_FILE = DATA_DIR / "votes.json"
SESSIONS_FILE = DATA_DIR / "sessions.json"

GMT7 = timezone(timedelta(hours=7))
VOTE_DEADLINE_HOUR = 22  # votes for a match's date lock at 22:00 GMT+7

# ── Backend selection ─────────────────────────────────────────────────────────
# On a server with a real disk we read/write JSON files. On serverless hosts
# (Vercel) the filesystem is read-only & ephemeral, so when Upstash Redis
# credentials are present we store each "file" as one Redis string keyed by its
# stem (e.g. "wc26:users").
#
# Credentials come from one of two env-var naming schemes:
#   - UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN  (Upstash console)
#   - KV_REST_API_URL        / KV_REST_API_TOKEN         (Vercel Marketplace)
# Either pair switches storage to Redis automatically; no code change per host.
import os

_REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL") or os.environ.get("KV_REST_API_URL")
_REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or os.environ.get("KV_REST_API_TOKEN")

_redis = None
if _REDIS_URL and _REDIS_TOKEN:
    from upstash_redis import Redis
    _redis = Redis(url=_REDIS_URL, token=_REDIS_TOKEN)


def _key(path: Path) -> str:
    return f"wc26:{path.stem}"  # users.json -> wc26:users


def _load(path: Path, default):
    if _redis is not None:
        try:
            raw = _redis.get(_key(path))
            return json.loads(raw) if raw else default
        except Exception:
            return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(path: Path, data):
    if _redis is not None:
        _redis.set(_key(path), json.dumps(data, ensure_ascii=False))
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _users() -> dict:
    """username -> {pw_hash, display_name, is_admin}"""
    return _load(USERS_FILE, {})


def _matches() -> list:
    return _load(MATCHES_FILE, [])


def _votes() -> dict:
    """match_id -> {username: 1|2}"""
    return _load(VOTES_FILE, {})


def _ko_key(m: dict):
    """Chronological sort key: real VN kickoff (ko, ISO 'YYYY-MM-DDTHH:MM').

    Matches without ko fall back to their match-day + a late sentinel so they
    sort after timed matches of the same day, then by id for stability.
    """
    return (m.get("ko") or (m.get("date", "") + "T99:99"), m.get("id", ""))


# ── Auth ────────────────────────────────────────────────────────────────────
def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


def _sessions() -> dict:
    return _load(SESSIONS_FILE, {})


def _current_user(request: Request):
    """Return user dict {username, display_name, is_admin} or None."""
    token = request.cookies.get("wc26_session")
    if not token:
        return None
    sess = _sessions()
    rec = sess.get(token)
    if not rec:
        return None
    try:
        if datetime.now(timezone.utc) > datetime.fromisoformat(rec["exp"]):
            return None
    except Exception:
        return None
    users = _users()
    u = users.get(rec["username"])
    if not u:
        return None
    return {
        "username": rec["username"],
        "display_name": u.get("display_name", rec["username"]),
        "is_admin": bool(u.get("is_admin")),
    }


def _require(request: Request, admin: bool = False):
    u = _current_user(request)
    if not u:
        raise HTTPException(401, "Chưa đăng nhập")
    if admin and not u["is_admin"]:
        raise HTTPException(403, "Chỉ admin được thao tác")
    return u


# ── Asian-handicap settlement engine ────────────────────────────────────────
def _settle_half(x: float) -> float:
    """Settle a whole/half line: win 1, push 0, lose -1."""
    if x > 0:
        return 1.0
    if x < 0:
        return -1.0
    return 0.0


def ah_result(pick_side: int, hcap_side: int, hcap: float, s1: int, s2: int) -> float:
    """Result fraction for the picked side: one of {1, .5, 0, -.5, -1}.

    pick_side / hcap_side: 1 = team1, 2 = team2. hcap >= 0 is the handicap the
    favourite (hcap_side) gives. Quarter lines (.25/.75) split into two halves.
    """
    margin = (s1 - s2) if pick_side == 1 else (s2 - s1)
    # favourite gives handicap; underdog receives it
    eff = margin - hcap if pick_side == hcap_side else margin + hcap
    frac = round(eff - round(eff), 2)
    if abs(frac) == 0.25:  # quarter line → average two half-stakes
        return 0.5 * _settle_half(eff - 0.25) + 0.5 * _settle_half(eff + 0.25)
    return _settle_half(eff)


# ── Money engine ─────────────────────────────────────────────────────────────
# Game thu tiền nhậu: mỗi người tự chịu pick của mình.
#   thắng / hòa kèo (r >= 0) → 0
#   thua nửa  (r == -0.5)    → 25
#   thua trắng (r == -1)     → 50
LOSE_FULL = 50
LOSE_HALF = 25


def _due(r: float) -> int:
    """Tiền phải nộp cho 1 pick, từ kết quả kèo r ∈ {1, .5, 0, -.5, -1}."""
    return int(round(-r * LOSE_FULL)) if r < 0 else 0


def _match_pnl(match: dict, votes_for_match: dict, all_users) -> dict:
    """Tiền nộp mỗi người cho 1 trận đã có kết quả. {username: tiền}.

    Ai vote → tính theo kèo (0/25/50). Ai KHÔNG vote → phạt 50 (như thua trắng).
    """
    s1, s2 = match.get("score1"), match.get("score2")
    if s1 is None or s2 is None:
        return {}
    hcap_side = int(match["hcap_side"])
    hcap = float(match["hcap"])
    out = {}
    for user in all_users:
        pick = votes_for_match.get(user)
        if pick:
            out[user] = _due(ah_result(pick, hcap_side, hcap, s1, s2))
        else:
            out[user] = LOSE_FULL  # không vote → phạt như thua trắng
    return out


def compute_overview() -> dict:
    users = _users()
    matches = _matches()
    votes = _votes()

    names = {u: users[u].get("display_name", u) for u in users}
    totals = {u: 0.0 for u in users}  # tổng tiền phải nộp
    acc = {u: {"correct": 0, "wrong": 0, "push": 0} for u in users}
    # cumulative money by date, per user
    by_date = {}  # date -> {user: delta}

    resulted = [m for m in matches if m.get("score1") is not None and m.get("score2") is not None]
    resulted.sort(key=_ko_key)

    per_match = []
    for m in resulted:
        vm = {u: s for u, s in votes.get(m["id"], {}).items() if u in users}
        pnl = _match_pnl(m, vm, users)
        d = m.get("date", "")
        by_date.setdefault(d, {u: 0.0 for u in users})
        for u, p in pnl.items():
            totals[u] += p
            by_date[d][u] += p
        # accuracy per voter
        for u, pick in vm.items():
            r = ah_result(pick, int(m["hcap_side"]), float(m["hcap"]), m["score1"], m["score2"])
            if r > 0:
                acc[u]["correct"] += 1
            elif r < 0:
                acc[u]["wrong"] += 1
            else:
                acc[u]["push"] += 1
        # per-user detail for history
        detail = []
        for u in users:
            pick = vm.get(u)
            if pick:
                r = ah_result(pick, int(m["hcap_side"]), float(m["hcap"]), m["score1"], m["score2"])
                res = "win" if r > 0 else ("lose" if r < 0 else "push")
            else:
                res = "novote"  # không vote → phạt 50, không tính đúng/sai
            detail.append({
                "username": u, "name": names[u],
                "pick": pick,
                "team": (m["team1"] if pick == 1 else m["team2"]) if pick else None,
                "result": res,
                "pnl": pnl.get(u),  # tiền nộp 0/25/50 (không vote = 50)
            })
        per_match.append({
            "id": m["id"], "date": d, "ko": m.get("ko"),
            "team1": m["team1"], "team2": m["team2"],
            "hcap_side": m["hcap_side"], "hcap": m["hcap"],
            "score": f'{m["score1"]}-{m["score2"]}',
            "winner": _keo_winner(m),
            "detail": detail,
        })

    # cumulative series (tiền nộp tích lũy theo ngày)
    dates = sorted(by_date.keys())
    cum = {u: 0.0 for u in users}
    series = {u: [] for u in users}
    for d in dates:
        for u in users:
            cum[u] += by_date[d].get(u, 0.0)
            series[u].append(round(cum[u], 2))

    standings = []
    for u in users:
        c, w = acc[u]["correct"], acc[u]["wrong"]
        rate = round(100 * c / (c + w), 1) if (c + w) else 0.0
        standings.append({
            "username": u, "name": names[u],
            "points": round(totals[u], 2),  # tổng tiền nộp
            "correct": c, "wrong": w, "push": acc[u]["push"], "rate": rate,
        })
    standings.sort(key=lambda x: x["points"])  # nộp ít nhất lên đầu

    # waiting = vote đã khóa (qua 22:00 GMT+7) nhưng chưa có kết quả
    waiting = []
    for m in matches:
        if m.get("score1") is not None and m.get("score2") is not None:
            continue
        if not _is_locked(m.get("date", "")):
            continue
        vm = {u: s for u, s in votes.get(m["id"], {}).items() if u in users}
        waiting.append({
            "id": m["id"], "date": m.get("date", ""), "ko": m.get("ko"),
            "team1": m["team1"], "team2": m["team2"],
            "hcap_side": m["hcap_side"], "hcap": m["hcap"], "ou_line": m.get("ou_line"),
            "vote_count": len(vm),
            "picks": vm,  # {username: side} — đã khóa nên lộ
        })
    waiting.sort(key=_ko_key)

    return {
        "standings": standings,
        "chart": {"labels": dates, "series": series, "names": names},
        "matches": list(reversed(per_match)),
        "waiting": waiting,
    }


def _keo_winner(m: dict) -> str:
    r1 = ah_result(1, int(m["hcap_side"]), float(m["hcap"]), m["score1"], m["score2"])
    if r1 > 0:
        return m["team1"]
    if r1 < 0:
        return m["team2"]
    return "Hòa kèo"


# ── Vote lock ────────────────────────────────────────────────────────────────
def _is_locked(date_str: str) -> bool:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").replace(
            hour=VOTE_DEADLINE_HOUR, minute=0, tzinfo=GMT7)
    except Exception:
        return False
    return datetime.now(GMT7) >= d


# ── Page ─────────────────────────────────────────────────────────────────────
@router.get("/wc26")
def wc26_page():
    return FileResponse(str(BASE_DIR / "static" / "wc26.html"))


# ── Auth API ─────────────────────────────────────────────────────────────────
@router.post("/api/wc26/login")
async def wc26_login(request: Request, response: Response):
    data = await request.json()
    username = (data.get("username") or "").strip().lower()
    pw = data.get("password") or ""
    users = _users()
    u = users.get(username)
    if not u or u.get("pw_hash") != _hash(pw):
        raise HTTPException(401, "Sai tài khoản hoặc mật khẩu")
    token = secrets.token_hex(32)
    sess = _sessions()
    # prune expired
    now = datetime.now(timezone.utc)
    sess = {t: r for t, r in sess.items()
            if _safe_after(r.get("exp"), now)}
    sess[token] = {"username": username,
                   "exp": (now + timedelta(days=30)).isoformat()}
    _save(SESSIONS_FILE, sess)
    response.set_cookie("wc26_session", token, max_age=86400 * 30,
                        httponly=True, samesite="lax")
    return {"ok": True}


def _safe_after(exp, now):
    try:
        return datetime.fromisoformat(exp) > now
    except Exception:
        return False


@router.post("/api/wc26/logout")
async def wc26_logout(request: Request, response: Response):
    token = request.cookies.get("wc26_session")
    if token:
        sess = _sessions()
        sess.pop(token, None)
        _save(SESSIONS_FILE, sess)
    response.delete_cookie("wc26_session")
    return {"ok": True}


@router.get("/api/wc26/me")
def wc26_me(request: Request):
    u = _current_user(request)
    if not u:
        return JSONResponse(status_code=401, content={"error": "Chưa đăng nhập"})
    return u


# ── Matches & votes API ──────────────────────────────────────────────────────
@router.get("/api/wc26/dates")
def wc26_dates(request: Request):
    _require(request)
    ds = sorted({m.get("date", "") for m in _matches() if m.get("date")}, reverse=True)
    return {"dates": ds}


@router.get("/api/wc26/matches")
def wc26_matches(request: Request, date: str = ""):
    me = _require(request)
    users = _users()
    matches = [m for m in _matches() if (not date or m.get("date") == date)]
    matches.sort(key=_ko_key)
    votes = _votes()
    out = []
    for m in matches:
        vm = {u: s for u, s in votes.get(m["id"], {}).items() if u in users}
        locked = _is_locked(m.get("date", "")) or (m.get("score1") is not None)
        item = {
            "id": m["id"], "date": m["date"], "ko": m.get("ko"),
            "team1": m["team1"], "team2": m["team2"],
            "hcap_side": m["hcap_side"], "hcap": m["hcap"],
            "ou_line": m.get("ou_line"),
            "score1": m.get("score1"), "score2": m.get("score2"),
            "locked": locked, "my_vote": vm.get(me["username"]),
            "vote_count": len(vm),
            "voters": [u for u in users if u in vm],
            # vote hiện ngay cho mọi người (không chờ đủ 6 / khóa)
            "votes": {u: {"name": users[u].get("display_name", u),
                          "pick": vm.get(u)} for u in users},
        }
        if m.get("score1") is not None:
            item["winner"] = _keo_winner(m)
        out.append(item)
    return {"matches": out,
            "users": {u: users[u].get("display_name", u) for u in users}}


@router.post("/api/wc26/vote")
async def wc26_vote(request: Request):
    me = _require(request)
    data = await request.json()
    mid = data.get("match_id")
    pick = data.get("pick")
    if pick not in (1, 2):
        raise HTTPException(400, "Pick không hợp lệ")
    match = next((m for m in _matches() if m["id"] == mid), None)
    if not match:
        raise HTTPException(404, "Không tìm thấy trận")
    if _is_locked(match.get("date", "")) or match.get("score1") is not None:
        raise HTTPException(403, "Đã khóa vote (qua 22:00 GMT+7 hoặc đã có kết quả)")
    votes = _votes()
    votes.setdefault(mid, {})[me["username"]] = pick
    _save(VOTES_FILE, votes)
    return {"ok": True}


# ── Admin API (nam.nguyen) ───────────────────────────────────────────────────
@router.post("/api/wc26/match")
async def wc26_save_match(request: Request):
    _require(request, admin=True)
    d = await request.json()
    matches = _matches()
    mid = d.get("id")
    payload = {
        "date": d["date"],
        "team1": (d["team1"] or "").strip(),
        "team2": (d["team2"] or "").strip(),
        "hcap_side": int(d["hcap_side"]),
        "hcap": float(d["hcap"]),
        "ou_line": d.get("ou_line"),
    }
    if mid:  # edit
        m = next((x for x in matches if x["id"] == mid), None)
        if not m:
            raise HTTPException(404, "Không tìm thấy trận")
        m.update(payload)
        if "ko" in d:  # giờ kickoff VN (ISO 'YYYY-MM-DDTHH:MM'); chỉ ghi khi gửi
            m["ko"] = d["ko"] or None
    else:  # create
        mid = secrets.token_hex(6)
        matches.append({"id": mid, "score1": None, "score2": None,
                        "ko": d.get("ko") or None, **payload})
    _save(MATCHES_FILE, matches)
    return {"ok": True, "id": mid}


@router.post("/api/wc26/result")
async def wc26_result(request: Request):
    _require(request, admin=True)
    d = await request.json()
    matches = _matches()
    m = next((x for x in matches if x["id"] == d.get("id")), None)
    if not m:
        raise HTTPException(404, "Không tìm thấy trận")
    if d.get("score1") in (None, "") or d.get("score2") in (None, ""):
        m["score1"], m["score2"] = None, None  # clear result
    else:
        m["score1"], m["score2"] = int(d["score1"]), int(d["score2"])
    _save(MATCHES_FILE, matches)
    return {"ok": True}


@router.delete("/api/wc26/match/{mid}")
def wc26_delete_match(mid: str, request: Request):
    _require(request, admin=True)
    matches = [m for m in _matches() if m["id"] != mid]
    _save(MATCHES_FILE, matches)
    votes = _votes()
    votes.pop(mid, None)
    _save(VOTES_FILE, votes)
    return {"ok": True}


@router.get("/api/wc26/overview")
def wc26_overview(request: Request):
    _require(request)
    return compute_overview()
