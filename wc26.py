"""World Cup 2026 vote & stats — nmquan.vn/wc26

Standalone page: 6 accounts log in, vote Asian-handicap picks for the day's
matches; an Overview ("Bảng tổng") shows points, accuracy and charts.

Self-contained auth (separate from the site's /private auth). All runtime data
lives in Vercel KV / Upstash Redis (keys `wc26:*`); there is no JSON fallback.
"""
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter()

# ── Storage ─────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent

GMT7 = timezone(timedelta(hours=7))
VOTE_DEADLINE_HOUR = 22  # votes for a match's date lock at 22:00 GMT+7

# ── Backend: Vercel KV / Upstash Redis (only) ─────────────────────────────────
# All runtime state lives in Redis, one string per logical "file" keyed by its
# stem (e.g. "wc26:users"). There is no JSON-file fallback — the app refuses to
# start without credentials so we never silently read stale local data.
#
# Credentials come from one of two env-var naming schemes:
#   - UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN  (Upstash console)
#   - KV_REST_API_URL        / KV_REST_API_TOKEN         (Vercel Marketplace)
# On Vercel these are injected automatically; locally we read them from .env.

# Logical store names → Redis keys "wc26:<name>".
USERS, MATCHES, VOTES, SESSIONS = "users", "matches", "votes", "sessions"
BRACKET = "bracket"  # sơ đồ nhánh knockout (mno 73–104)


def _load_dotenv():
    """Populate os.environ from a local .env (key=value lines) if present.

    Existing env vars win, so Vercel's injected credentials are never
    overwritten. No-op when .env is absent (e.g. on the serverless host).
    """
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

_REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL") or os.environ.get("KV_REST_API_URL")
_REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or os.environ.get("KV_REST_API_TOKEN")

if not (_REDIS_URL and _REDIS_TOKEN):
    raise RuntimeError(
        "Thiếu credential Vercel KV / Upstash Redis. Cần KV_REST_API_URL + "
        "KV_REST_API_TOKEN (hoặc UPSTASH_REDIS_REST_URL/TOKEN) trong .env hoặc "
        "biến môi trường."
    )

from upstash_redis import Redis

_redis = Redis(url=_REDIS_URL, token=_REDIS_TOKEN)


def _load(name: str, default):
    try:
        raw = _redis.get(f"wc26:{name}")
        return json.loads(raw) if raw else default
    except Exception:
        return default


def _save(name: str, data):
    _redis.set(f"wc26:{name}", json.dumps(data, ensure_ascii=False))


def _users() -> dict:
    """username -> {pw_hash, display_name, is_admin}"""
    return _load(USERS, {})


def _matches() -> list:
    return _load(MATCHES, [])


def _votes() -> dict:
    """match_id -> {username: 1|2}"""
    return _load(VOTES, {})


def _ko_key(m: dict):
    """Chronological sort key: real VN kickoff (ko, ISO 'YYYY-MM-DDTHH:MM').

    Matches without ko fall back to their match-day + a late sentinel so they
    sort after timed matches of the same day, then by id for stability.
    """
    return (m.get("ko") or (m.get("date", "") + "T99:99"), m.get("id", ""))


# ── Sơ đồ nhánh knockout ──────────────────────────────────────────────────────
# Cây 32 trận: R32 (73–88) đã biết đội; các vòng sau (89–104) suy ra từ đội
# THẮNG của 2 trận "feeder". Trận tranh hạng 3 (103) lấy 2 đội THUA bán kết.
# Khác vòng bảng: knockout KHÔNG có kèo chấp — hơn tỷ số là thắng; hòa thì so
# luân lưu (pen1/pen2). Bracket độc lập với engine tiền/điểm của vòng bảng.
KO_FEED = {
    89: [74, 77], 90: [73, 75], 91: [76, 78], 92: [79, 80],
    93: [83, 84], 94: [81, 82], 95: [86, 88], 96: [85, 87],
    97: [89, 90], 98: [93, 94], 99: [91, 92], 100: [95, 96],
    101: [97, 98], 102: [99, 100], 104: [101, 102],
}
KO_THIRD_FEED = (101, 102)  # 103 (tranh hạng 3) = đội THUA của 2 bán kết
# Thứ tự điền: vòng trước xong mới suy ra được vòng sau.
KO_FILL_ORDER = [89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103, 104]


def _ko_winner_side(m: dict):
    """Bên thắng 1 trận knockout: 1 | 2 | None (chưa đủ dữ liệu / hòa cả luân lưu)."""
    s1, s2 = m.get("score1"), m.get("score2")
    if s1 is None or s2 is None:
        return None
    if s1 > s2:
        return 1
    if s2 > s1:
        return 2
    p1, p2 = m.get("pen1"), m.get("pen2")  # hòa → so luân lưu
    if p1 is not None and p2 is not None:
        if p1 > p2:
            return 1
        if p2 > p1:
            return 2
    return None


def _ko_winner_name(m: dict):
    side = _ko_winner_side(m)
    return (m.get("team1") if side == 1 else m.get("team2") if side == 2 else None) or None


def _ko_loser_name(m: dict):
    side = _ko_winner_side(m)
    return (m.get("team2") if side == 1 else m.get("team1") if side == 2 else None) or None


def _bracket() -> list:
    """Cây thô trong KV (chỉ R32 + kết quả đã nhập); rỗng nếu chưa seed.

    Khung ban đầu nằm ở wc26_data/bracket.json, đẩy lên KV bằng seed_redis.py
    (như users/matches/votes). Runtime CHỈ đọc KV — không đọc file, nhất quán
    với nguyên tắc KV-only của app.
    """
    return _load(BRACKET, [])


def _push_result_to_bracket(mno: int, s1, s2, p1, p2):
    """Đồng bộ kết quả 1 trận (từ luồng betting) vào ô tương ứng trong cây."""
    stored = _bracket()
    bm = next((x for x in stored if x.get("mno") == mno), None)
    if not bm:
        return
    bm["score1"], bm["score2"] = s1, s2
    bm["pen1"], bm["pen2"] = p1, p2
    _save(BRACKET, stored)


def _compute_bracket(stored: list) -> list:
    """Suy ra đội + 'ready' + winner cho mọi vòng từ R32 + các kết quả đã nhập.

    Nguồn sự thật = đội R32 (cố định) + score/pen từng trận. Đội các vòng sau
    được tính lại mỗi lần đọc nên thắng đâu tự nhảy lên đó, không lưu dư.
    """
    by = {m["mno"]: dict(m) for m in stored}
    for mno in KO_FILL_ORDER:
        m = by.get(mno)
        if not m:
            continue
        if mno == 103:  # tranh hạng 3: 2 đội thua bán kết
            a, b = KO_THIRD_FEED
            t1, t2 = _ko_loser_name(by.get(a, {})), _ko_loser_name(by.get(b, {}))
        else:
            a, b = KO_FEED[mno]
            t1, t2 = _ko_winner_name(by.get(a, {})), _ko_winner_name(by.get(b, {}))
        m["team1"], m["team2"] = t1 or "", t2 or ""
        m["ready"] = bool(t1 and t2)
    out = []
    for src in stored:  # giữ thứ tự gốc
        m = by[src["mno"]]
        m["winner"] = _ko_winner_name(m)
        if "ready" not in m:  # R32 lấy ready từ file
            m["ready"] = bool(m.get("team1") and m.get("team2"))
        out.append(m)
    return out


# ── Auth ────────────────────────────────────────────────────────────────────
def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


def _sessions() -> dict:
    return _load(SESSIONS, {})


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


MIN_TOGETHER = 5  # cặp/bộ ba cần ≥ ngần này trận cùng chọn mới được xếp hạng


def _chemistry(group_size, resulted_picks, names):
    """Xếp hạng 'hợp cạ' cho mọi nhóm cỡ group_size (2 hoặc 3).

    resulted_picks: list các (picks:{user:1|2}, win_side:1|2|None) cho trận đã KQ.
      win_side = đội thắng kèo (None nếu hòa kèo).
    Một trận tính cho nhóm khi MỌI thành viên đều vote VÀ chọn cùng 1 đội.
    % = số trận nhóm thắng kèo / số trận cùng chọn (bỏ hòa kèo).
    Trả (best, worst): mỗi cái là {members:[username], names:[..], rate, win, total}
    hoặc None nếu không nhóm nào đạt ngưỡng.
    """
    users = list(names.keys())
    stats = {}  # group(tuple) -> [win, total_non_push]
    for combo in combinations(users, group_size):
        win = total = 0
        for picks, win_side in resulted_picks:
            ps = [picks.get(u) for u in combo]
            if any(p is None for p in ps):
                continue                # có người không vote → bỏ
            if len(set(ps)) != 1:
                continue                # không cùng 1 cửa
            side = ps[0]
            if win_side is None:
                continue                # hòa kèo → không tính
            total += 1
            if side == win_side:
                win += 1
        if total >= MIN_TOGETHER:
            stats[combo] = (win, total)
    if not stats:
        return None, None

    def pack(combo):
        win, total = stats[combo]
        return {"members": list(combo), "names": [names[u] for u in combo],
                "rate": round(100 * win / total, 1), "win": win, "total": total}

    best = max(stats, key=lambda c: (stats[c][0] / stats[c][1], stats[c][1]))
    worst = min(stats, key=lambda c: (stats[c][0] / stats[c][1], -stats[c][1]))
    return pack(best), pack(worst)


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

    resulted_picks = []  # [(picks{user:1|2}, win_side 1|2|None)] cho 'hợp cạ'
    per_match = []
    for m in resulted:
        d = m.get("date", "")
        # Trận cũ trước khi trò chơi bắt đầu: chỉ hiện trong lịch sử để xem,
        # KHÔNG vote, KHÔNG tính tiền/đúng-sai/hợp cạ cho ai.
        if m.get("nocount"):
            per_match.append({
                "id": m["id"], "date": d, "ko": m.get("ko"),
                "team1": m["team1"], "team2": m["team2"],
                "hcap_side": m["hcap_side"], "hcap": m["hcap"],
                "score": f'{m["score1"]}-{m["score2"]}',
                "winner": _keo_winner(m),
                "nocount": True,
                "detail": [{"username": u, "name": names[u], "pick": None,
                            "team": None, "result": "skip", "pnl": None} for u in users],
            })
            continue
        vm = {u: s for u, s in votes.get(m["id"], {}).items() if u in users}
        pnl = _match_pnl(m, vm, users)
        # win_side: đội thắng kèo (1/2) hoặc None nếu hòa kèo
        r1 = ah_result(1, int(m["hcap_side"]), float(m["hcap"]), m["score1"], m["score2"])
        win_side = 1 if r1 > 0 else (2 if r1 < 0 else None)
        resulted_picks.append((vm, win_side))
        by_date.setdefault(d, {u: 0.0 for u in users})
        for u, p in pnl.items():
            totals[u] += p
            by_date[d][u] += p
        # accuracy + per-user detail for history (duyệt tất cả users:
        # không vote → tính là thua, vẫn phạt 50)
        detail = []
        for u in users:
            pick = vm.get(u)
            if pick:
                r = ah_result(pick, int(m["hcap_side"]), float(m["hcap"]), m["score1"], m["score2"])
                if r > 0:
                    acc[u]["correct"] += 1
                    res = "win"
                elif r < 0:
                    acc[u]["wrong"] += 1
                    res = "lose"
                else:
                    acc[u]["push"] += 1
                    res = "push"
            else:
                acc[u]["wrong"] += 1  # không vote → tính là thua
                res = "novote"  # không vote → phạt 50, đánh dấu là thua
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
            "mno": m.get("mno"), "round": m.get("round"),   # trận knockout → form nhập KQ có ô luân lưu
            "pen1": m.get("pen1"), "pen2": m.get("pen2"),
            "vote_count": len(vm),
            "picks": vm,  # {username: side} — đã khóa nên lộ
        })
    waiting.sort(key=_ko_key)

    # Hợp cạ: cặp & bộ ba hay cùng chọn 1 cửa
    pair_best, pair_worst = _chemistry(2, resulted_picks, names)
    trio_best, trio_worst = _chemistry(3, resulted_picks, names)

    return {
        "standings": standings,
        "chart": {"labels": dates, "series": series, "names": names},
        "matches": list(reversed(per_match)),
        "waiting": waiting,
        "chemistry": {
            "pair_best": pair_best, "pair_worst": pair_worst,
            "trio_best": trio_best, "trio_worst": trio_worst,
            "min_together": MIN_TOGETHER,
        },
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
    _save(SESSIONS, sess)
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
        _save(SESSIONS, sess)
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
            "mno": m.get("mno"), "round": m.get("round"),  # link sơ đồ nhánh (nếu là trận knockout)
            "pen1": m.get("pen1"), "pen2": m.get("pen2"),
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
    _save(VOTES, votes)
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
    if d.get("mno") is not None:  # trận knockout: link với sơ đồ nhánh
        payload["mno"] = int(d["mno"])
        payload["round"] = d.get("round")
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
    _save(MATCHES, matches)
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
        m["score1"], m["score2"] = None, None  # xóa KQ
        m["pen1"], m["pen2"] = None, None       # xóa luôn luân lưu
    else:
        m["score1"], m["score2"] = int(d["score1"]), int(d["score2"])
        # luân lưu (knockout): chỉ ghi khi request có gửi → tránh xóa nhầm khi
        # sửa kèo (saveKeoInline gọi /result không kèm pen).
        if "pen1" in d or "pen2" in d:
            m["pen1"] = int(d["pen1"]) if d.get("pen1") not in (None, "") else None
            m["pen2"] = int(d["pen2"]) if d.get("pen2") not in (None, "") else None
    _save(MATCHES, matches)
    # Trận knockout (có mno) → đẩy tỷ số 90' + luân lưu sang sơ đồ nhánh để
    # đội tự nhảy lên vòng sau. Tiền/ăn kèo vẫn tính theo tỷ số 90' như cũ.
    if m.get("mno") is not None:
        _push_result_to_bracket(m["mno"], m.get("score1"), m.get("score2"),
                                m.get("pen1"), m.get("pen2"))
    return {"ok": True}


@router.delete("/api/wc26/match/{mid}")
def wc26_delete_match(mid: str, request: Request):
    _require(request, admin=True)
    matches = [m for m in _matches() if m["id"] != mid]
    _save(MATCHES, matches)
    votes = _votes()
    votes.pop(mid, None)
    _save(VOTES, votes)
    return {"ok": True}


@router.get("/api/wc26/overview")
def wc26_overview(request: Request):
    _require(request)
    return compute_overview()


# ── Bracket API ───────────────────────────────────────────────────────────────
@router.get("/api/wc26/bracket")
def wc26_bracket(request: Request):
    _require(request)
    return {"matches": _compute_bracket(_bracket())}
