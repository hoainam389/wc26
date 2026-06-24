"""Thêm các trận CŨ (trước khi trò chơi bắt đầu) vào storage.

Trận cũ: chỉ hiện trong Lịch sử để xem cho đủ — KHÔNG vote, KHÔNG tính
tiền/đúng-sai/hợp cạ (đánh dấu cờ "nocount": True).

Sửa danh sách OLD_MATCHES bên dưới rồi chạy:
    python add_old_matches.py --check   # XEM trước, không ghi
    python add_old_matches.py           # ghi (append, không đụng trận cũ đã có)

Credential đọc từ env (giống seed_redis.py / wc26.py):
    UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN  hoặc  KV_REST_API_*
Không set env Redis → ghi thẳng vào file local wc26_data/matches.json.
"""
import json
import os
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "wc26_data"
MATCHES_FILE = DATA_DIR / "matches.json"

# ── ĐIỀN TRẬN CŨ Ở ĐÂY ──
# Mỗi trận: date (YYYY-MM-DD), team1, team2, score1, score2.
# hcap/hcap_side để 1/0 cho có (không dùng vì nocount). Không cần ko/ou_line.
# hcap_side: 1 = team1 chấp, 2 = team2 chấp. hcap >= 0. ou = tài/xỉu. ko = giờ VN (ISO).
OLD_MATCHES = [
    # 11/06
    {"date": "2026-06-11", "team1": "Mexico", "team2": "Nam Phi", "score1": 2, "score2": 0, "hcap_side": 1, "hcap": 1.25, "ou": 2.25, "ko": "2026-06-11T02:00"},
    {"date": "2026-06-11", "team1": "Hàn Quốc", "team2": "Séc", "score1": 2, "score2": 1, "hcap_side": 1, "hcap": 0, "ou": 2.25, "ko": "2026-06-11T09:00"},
    # 12/06
    {"date": "2026-06-12", "team1": "Canada", "team2": "Bosnia", "score1": 1, "score2": 1, "hcap_side": 1, "hcap": 0.5, "ou": 2.25, "ko": "2026-06-12T02:00"},
    {"date": "2026-06-12", "team1": "Mỹ", "team2": "Paraguay", "score1": 4, "score2": 1, "hcap_side": 1, "hcap": 0.5, "ou": 2.25, "ko": "2026-06-12T08:00"},
    # 13/06
    {"date": "2026-06-13", "team1": "Qatar", "team2": "Thụy Sĩ", "score1": 1, "score2": 1, "hcap_side": 2, "hcap": 1.75, "ou": 2.75, "ko": "2026-06-13T02:00"},
    {"date": "2026-06-13", "team1": "Brazil", "team2": "Ma-rốc", "score1": 1, "score2": 1, "hcap_side": 1, "hcap": 0.75, "ou": 2.25, "ko": "2026-06-13T05:00"},
    {"date": "2026-06-13", "team1": "Haiti", "team2": "Scotland", "score1": 0, "score2": 1, "hcap_side": 2, "hcap": 1, "ou": 2.5, "ko": "2026-06-13T08:00"},
    # 14/06
    {"date": "2026-06-14", "team1": "Úc", "team2": "Thổ Nhĩ Kỳ", "score1": 2, "score2": 0, "hcap_side": 2, "hcap": 0.75, "ou": 2.5, "ko": "2026-06-14T11:00"},
    {"date": "2026-06-14", "team1": "Đức", "team2": "Curaçao", "score1": 7, "score2": 1, "hcap_side": 1, "hcap": 3.5, "ou": 4.25, "ko": "2026-06-14T00:00"},
    {"date": "2026-06-14", "team1": "Hà Lan", "team2": "Nhật Bản", "score1": 2, "score2": 2, "hcap_side": 1, "hcap": 0.5, "ou": 2.5, "ko": "2026-06-14T03:00"},
    {"date": "2026-06-14", "team1": "Bờ Biển Ngà", "team2": "Ecuador", "score1": 1, "score2": 0, "hcap_side": 2, "hcap": 0.25, "ou": 2, "ko": "2026-06-14T06:00"},
    {"date": "2026-06-14", "team1": "Thụy Điển", "team2": "Tunisia", "score1": 5, "score2": 1, "hcap_side": 1, "hcap": 0.5, "ou": 2.25, "ko": "2026-06-14T09:00"},
    # 15/06
    {"date": "2026-06-15", "team1": "Tây Ban Nha", "team2": "Cabo Verde", "score1": 0, "score2": 0, "hcap_side": 1, "hcap": 2.75, "ou": 3.5, "ko": "2026-06-15T23:00"},
    {"date": "2026-06-15", "team1": "Bỉ", "team2": "Ai Cập", "score1": 1, "score2": 1, "hcap_side": 1, "hcap": 1, "ou": 2.5, "ko": "2026-06-15T02:00"},
    {"date": "2026-06-15", "team1": "Ả Rập Xê Út", "team2": "Uruguay", "score1": 1, "score2": 1, "hcap_side": 2, "hcap": 1, "ou": 2.5, "ko": "2026-06-15T05:00"},
    {"date": "2026-06-15", "team1": "Iran", "team2": "New Zealand", "score1": 2, "score2": 2, "hcap_side": 1, "hcap": 0.5, "ou": 2, "ko": "2026-06-15T08:00"},
]


def _fields(o):
    """Các field dữ liệu (không gồm id) suy ra từ một dòng OLD_MATCHES."""
    return {
        "date": o["date"],
        "team1": o["team1"].strip(),
        "team2": o["team2"].strip(),
        "hcap_side": o.get("hcap_side", 1),
        "hcap": float(o.get("hcap", 0)),
        "ou_line": o.get("ou"),
        "ko": o.get("ko"),
        "score1": int(o["score1"]),
        "score2": int(o["score2"]),
        "nocount": True,
    }


def _load_remote():
    try:
        from upstash_redis import Redis
    except ImportError:
        return None, None
    url = os.environ.get("UPSTASH_REDIS_REST_URL") or os.environ.get("KV_REST_API_URL")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or os.environ.get("KV_REST_API_TOKEN")
    if not (url and token):
        return None, None
    r = Redis(url=url, token=token)
    raw = r.get("wc26:matches")
    return r, (json.loads(raw) if raw else [])


def main():
    check = "--check" in sys.argv[1:]
    redis, matches = _load_remote()
    where = "Redis prod"
    if redis is None:
        where = "file local"
        matches = json.loads(MATCHES_FILE.read_text(encoding="utf-8")) if MATCHES_FILE.exists() else []

    # map (date,team1,team2) -> match đang có, để update tại chỗ
    by_key = {(m.get("date"), m.get("team1"), m.get("team2")): m for m in matches}
    n_upd, n_add = 0, 0
    for i, o in enumerate(OLD_MATCHES, 1):
        f = _fields(o)
        key = (f["date"], f["team1"], f["team2"])
        cur = by_key.get(key)
        if cur:  # update: chỉ ghi đè field dữ liệu, GIỮ id cũ
            cur.update(f)
            n_upd += 1
            tag = "cập nhật"
        else:    # thêm mới
            f["id"] = f"old{i:02d}_" + o["date"].replace("-", "")
            matches.append(f)
            n_add += 1
            tag = "thêm mới"
        print(f"  [{tag}] {f['date']} {f['ko'][-5:] if f['ko'] else '--:--'}  "
              f"{f['team1']} {f['score1']}-{f['score2']} {f['team2']}  "
              f"(chấp {f['hcap_side']}/{f['hcap']}, T/X {f['ou_line']})")

    print(f"\nStorage: {where}. Cập nhật {n_upd}, thêm mới {n_add}.")
    if check:
        print("(--check: KHÔNG ghi)")
        return

    if redis is not None:
        redis.set("wc26:matches", json.dumps(matches, ensure_ascii=False))
    else:
        MATCHES_FILE.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Đã ghi vào {where}.")


if __name__ == "__main__":
    main()
