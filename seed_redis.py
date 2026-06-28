"""Đẩy dữ liệu JSON local trong wc26_data/ lên Upstash Redis.

Lấy credential từ env (chấp nhận cả hai kiểu tên — Upstash console hoặc Vercel):
    UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN
    KV_REST_API_URL        / KV_REST_API_TOKEN

Dùng (PowerShell):
    $env:KV_REST_API_URL="https://...upstash.io"
    $env:KV_REST_API_TOKEN="..."
    python seed_redis.py --check          # chỉ XEM key hiện có, KHÔNG ghi
    python seed_redis.py                  # ghi các key CÒN THIẾU; KHÔNG đụng key đã có
    python seed_redis.py --only bracket   # chỉ ghi đúng 1 key (vd seed bracket lên prod)
    python seed_redis.py --force          # ghi đè cả key đã có (NGUY HIỂM — mất data)

Mỗi file wc26_data/<stem>.json → 1 key `wc26:<stem>` (khớp cách wc26.py đọc).
AN TOÀN: mặc định KHÔNG bao giờ ghi đè key đã tồn tại (giữ data prod) — chỉ ghi
key còn thiếu. Muốn ghi đè phải --force. Chỉ đụng key prefix `wc26:`.
"""
import json
import os
import sys
from pathlib import Path

from upstash_redis import Redis

DATA_DIR = Path(__file__).resolve().parent / "wc26_data"
FILES = ["users.json", "matches.json", "votes.json", "bracket.json"]
KEYS = [f"wc26:{Path(f).stem}" for f in FILES]


def _redis():
    url = os.environ.get("UPSTASH_REDIS_REST_URL") or os.environ.get("KV_REST_API_URL")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or os.environ.get("KV_REST_API_TOKEN")
    if not (url and token):
        raise SystemExit(
            "Thiếu credential. Set UPSTASH_REDIS_REST_URL/TOKEN hoặc KV_REST_API_URL/TOKEN")
    return Redis(url=url, token=token)


def _existing_wc26_keys(redis):
    """Các key wc26:* đang có sẵn trên DB (để cảnh báo trước khi ghi)."""
    return [k for k in KEYS if redis.get(k) is not None]


def check(redis):
    """Liệt kê toàn cảnh DB: tổng số key + key wc26:* đã có."""
    try:
        all_keys = redis.keys("*")
    except Exception:
        all_keys = None
    if all_keys is not None:
        print(f"DB hiện có {len(all_keys)} key.")
        other = [k for k in all_keys if not k.startswith("wc26:")]
        if other:
            print(f"  ⚠ {len(other)} key KHÔNG phải wc26:* (của app khác?):")
            for k in other[:20]:
                print(f"      {k}")
            if len(other) > 20:
                print(f"      ... và {len(other)-20} key nữa")
    have = _existing_wc26_keys(redis)
    if have:
        print("  Key wc26:* ĐÃ tồn tại (seed sẽ ghi đè):", ", ".join(have))
    else:
        print("  Chưa có key wc26:* nào — ghi mới hoàn toàn an toàn.")
    return have


def seed(redis, force, only=None):
    """Ghi key còn thiếu (mặc định). KHÔNG ghi đè key đã có trừ khi --force.

    only: chỉ xử lý 1 stem (vd 'bracket') — dùng để seed riêng 1 key lên prod
    mà tuyệt đối không chạm các key khác.
    """
    files = FILES
    if only:
        files = [f for f in FILES if Path(f).stem == only]
        if not files:
            raise SystemExit(
                f"Không có file cho '{only}'. Chọn: " +
                ", ".join(Path(f).stem for f in FILES))
    for fname in files:
        path = DATA_DIR / fname
        if not path.exists():
            print(f"bỏ qua (không có file): {fname}")
            continue
        key = f"wc26:{path.stem}"
        if redis.get(key) is not None and not force:
            print(f"GIỮ NGUYÊN (đã có, không ghi đè): {key}")  # an toàn cho prod
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        redis.set(key, json.dumps(data, ensure_ascii=False))
        print(f"đã ghi {key}  ({len(json.dumps(data))} bytes)")
    print("Xong.")


def main():
    args = sys.argv[1:]
    only = None
    if "--only" in args:
        i = args.index("--only")
        only = args[i + 1] if i + 1 < len(args) else None
        if not only:
            raise SystemExit("--only cần tên key, vd: --only bracket")
    redis = _redis()
    if "--check" in args:
        check(redis)
        return
    seed(redis, force="--force" in args, only=only)


if __name__ == "__main__":
    main()
