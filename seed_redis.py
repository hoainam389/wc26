"""Đẩy dữ liệu JSON local trong wc26_data/ lên Upstash Redis.

Lấy credential từ env (chấp nhận cả hai kiểu tên — Upstash console hoặc Vercel):
    UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN
    KV_REST_API_URL        / KV_REST_API_TOKEN

Dùng (PowerShell):
    $env:KV_REST_API_URL="https://...upstash.io"
    $env:KV_REST_API_TOKEN="..."
    python seed_redis.py --check     # chỉ XEM key hiện có, KHÔNG ghi
    python seed_redis.py             # ghi, nhưng dừng nếu wc26:* đã tồn tại
    python seed_redis.py --force     # ghi đè kể cả khi wc26:* đã có

Mỗi file wc26_data/<stem>.json → 1 key `wc26:<stem>` (khớp cách wc26.py đọc).
An toàn khi dùng chung DB với app khác: chỉ đụng các key có prefix `wc26:`.
"""
import json
import os
import sys
from pathlib import Path

from upstash_redis import Redis

DATA_DIR = Path(__file__).resolve().parent / "wc26_data"
FILES = ["users.json", "matches.json", "votes.json"]
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


def seed(redis, force):
    have = _existing_wc26_keys(redis)
    if have and not force:
        raise SystemExit(
            "DỪNG: các key đã tồn tại: " + ", ".join(have) +
            "\nChạy lại với --force nếu chắc chắn muốn ghi đè (chỉ ảnh hưởng key wc26:*).")
    for fname in FILES:
        path = DATA_DIR / fname
        if not path.exists():
            print(f"bỏ qua (không có): {fname}")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        key = f"wc26:{path.stem}"
        redis.set(key, json.dumps(data, ensure_ascii=False))
        print(f"đã ghi {key}  ({len(json.dumps(data))} bytes)")
    print("Xong.")


def main():
    args = set(sys.argv[1:])
    redis = _redis()
    if "--check" in args:
        check(redis)
        return
    seed(redis, force="--force" in args)


if __name__ == "__main__":
    main()
