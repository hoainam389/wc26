"""Đẩy dữ liệu JSON local trong wc26_data/ lên Upstash Redis (chạy 1 lần).

Lấy credential từ env (chấp nhận cả hai kiểu tên — Upstash console hoặc Vercel):
    UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN
    KV_REST_API_URL        / KV_REST_API_TOKEN

Dùng (PowerShell):
    $env:KV_REST_API_URL="https://...upstash.io"
    $env:KV_REST_API_TOKEN="..."
    python seed_redis.py

Đọc các file wc26_data/*.json và ghi mỗi file thành 1 key `wc26:<stem>`,
khớp với cách wc26.py đọc khi chạy trên Redis. Bỏ qua sessions.json.
"""
import json
import os
from pathlib import Path

from upstash_redis import Redis

DATA_DIR = Path(__file__).resolve().parent / "wc26_data"
FILES = ["users.json", "matches.json", "votes.json", "sidebets.json"]


def main():
    url = os.environ.get("UPSTASH_REDIS_REST_URL") or os.environ.get("KV_REST_API_URL")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or os.environ.get("KV_REST_API_TOKEN")
    if not (url and token):
        raise SystemExit(
            "Thiếu credential. Set UPSTASH_REDIS_REST_URL/TOKEN hoặc KV_REST_API_URL/TOKEN")
    redis = Redis(url=url, token=token)
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


if __name__ == "__main__":
    main()
