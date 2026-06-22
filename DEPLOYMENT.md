# Deploy WC26 lên Vercel (Upstash Redis qua Marketplace)

App WC26 ghi dữ liệu (vote, trận, kết quả, session) ra storage. Vercel có
filesystem **read-only & ephemeral** nên không thể ghi file JSON như khi chạy
trên server có ổ đĩa thật. Vì vậy trên Vercel ta dùng **Upstash Redis** — gắn
trực tiếp qua **Vercel Marketplace**, Vercel tự inject credential.

Code đã hỗ trợ sẵn cả hai môi trường:

| Môi trường | Storage | Kích hoạt khi |
|---|---|---|
| Local (máy bạn) | File JSON trong `wc26_data/` | Không có env Redis |
| Vercel | Upstash Redis (mỗi file → 1 key `wc26:<tên>`) | Có env Redis |

Việc chọn backend nằm ở [wc26.py](wc26.py) (`_load` / `_save`), đọc credential từ
**một trong hai** cặp env var:

- `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` (tạo từ Upstash console)
- `KV_REST_API_URL` / `KV_REST_API_TOKEN` (Vercel Marketplace tự inject)

---

## Các bước

### 1. Push code lên GitHub

```powershell
git add -A
git commit -m "Deploy to Vercel with Upstash Redis storage"
git push
```

### 2. Import project vào Vercel

1. Vào https://vercel.com → **Add New → Project**.
2. Import repo này.
3. Bấm **Deploy** (lần đầu app build được nhưng chưa có Redis — sẽ gắn ở bước 3).

### 3. Gắn Upstash Redis qua Marketplace

1. Mở project → tab **Storage** → **Create Database**.
2. Chọn **Upstash for Redis**.
3. Chọn region gần người dùng (vd **Singapore**) → tạo.
4. **Connect** database vào project.

Vercel sẽ **tự inject** `KV_REST_API_URL` + `KV_REST_API_TOKEN` vào Environment
Variables của project — không cần copy tay.

### 4. Seed dữ liệu hiện có lên Redis (chạy local, 1 lần)

Lấy URL + token: tab **Storage** → mở database → mục **REST API** (hoặc file
`.env.local` tải về).

```powershell
pip install upstash-redis
$env:KV_REST_API_URL="https://xxx.upstash.io"
$env:KV_REST_API_TOKEN="xxxxx"
python seed_redis.py
```

Script [seed_redis.py](seed_redis.py) đọc `wc26_data/*.json` và ghi mỗi file thành
một key `wc26:<tên>` (bỏ qua `sessions.json`). In ra từng key đã ghi.

> Bỏ qua bước này nếu bắt đầu với dữ liệu trống — app sẽ tự tạo khi dùng.

### 5. Redeploy

1. Vercel → tab **Deployments** → **Redeploy** (để build mới nhận env var).
2. Mở `https://<project>.vercel.app/wc26`.

---

## Kiểm tra sau deploy

- `https://<project>.vercel.app/` → trả JSON `{"app": "WC26 Vote", "open": "/wc26"}`.
- `https://<project>.vercel.app/wc26` → trang web hiển thị.
- Đăng nhập + vote một trận → reload vẫn còn → Redis hoạt động.

---

## Lưu ý quan trọng

- **Bắt buộc Redeploy sau khi connect storage.** Env var chỉ áp dụng từ lần build
  tiếp theo; deploy cũ vẫn rơi vào nhánh ghi-file và sẽ lỗi khi vote.
- **Không commit credential.** `KV_REST_API_TOKEN` chỉ đặt trong Vercel env var /
  shell local, không đưa vào git.
- **Sessions nằm trong Redis** nên đăng nhập bền vững, không mất khi cold start.
- Nếu Vercel inject tên env khác (hiếm), thêm tên đó vào nhánh chọn backend trong
  [wc26.py](wc26.py) — hiện đã cover `UPSTASH_REDIS_REST_*` và `KV_REST_API_*`.

---

## Cấu trúc liên quan đến deploy

| File | Vai trò |
|---|---|
| [api/index.py](api/index.py) | Entrypoint serverless của Vercel (re-export `app`) |
| [vercel.json](vercel.json) | Rewrite mọi request về `/api/index` |
| [requirements.txt](requirements.txt) | Dependencies (gồm `upstash-redis`) |
| [seed_redis.py](seed_redis.py) | Đẩy dữ liệu JSON local lên Redis (chạy 1 lần) |
| [main.py](main.py) | FastAPI app, mount `/static`, gắn router |
| [wc26.py](wc26.py) | Logic + lớp storage (Redis / file) |

---

## Chạy local (không cần Redis)

```powershell
pip install -r requirements.txt
uvicorn main:app --reload
# mở http://127.0.0.1:8000/wc26
```

Không set env Redis → app tự dùng file JSON trong `wc26_data/`, y như trước.
