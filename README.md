# WC26 — App vote & thống kê kèo bóng đá World Cup 2026

Web app nhỏ để một nhóm bạn vote **kèo chấp châu Á** cho các trận trong ngày, rồi tự
tính điểm thắng/thua, tỷ lệ đoán đúng và vẽ biểu đồ — thay cho việc ghi tay trên Google Sheet.

Backend là **FastAPI**, lưu dữ liệu bằng **file JSON** (không cần database), frontend là
**một file HTML** thuần (vanilla JS + Chart.js). Toàn bộ chỉ ~1.500 dòng, dễ đọc và sửa.

---

## Chạy thử trong 1 phút

Cần Python 3.9+.

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Mở trình duyệt: **http://127.0.0.1:8000/wc26**

### Tài khoản demo (đăng nhập sẵn trong `wc26_data/users.json`)

| Tài khoản  | Mật khẩu   | Quyền                        |
|------------|------------|------------------------------|
| `admin`    | `admin123` | Admin — nhập trận, tỷ số, kèo |
| `player2`  | `1234`     | Người chơi (chỉ vote)        |
| `player3`  | `1234`     | Người chơi                   |
| `player4`  | `1234`     | Người chơi                   |
| `player5`  | `1234`     | Người chơi                   |
| `player6`  | `1234`     | Người chơi                   |

> Đây là mật khẩu DEMO công khai. Nếu dùng thật, hãy đổi mật khẩu (xem dưới).

---

## Đổi tài khoản / mật khẩu

Mật khẩu lưu dạng **SHA-256** trong `wc26_data/users.json`. Tạo hash mới:

```bash
python -c "import hashlib; print(hashlib.sha256('matkhaumoi'.encode()).hexdigest())"
```

Dán chuỗi vừa in vào `pw_hash` của user tương ứng. Đổi `display_name` để hiện tên thật.
Mô hình tính tiền cần **đúng 6 người chơi** (1 admin có thể vừa làm người chơi).

---

## Cấu trúc

```
.
├── main.py            # App FastAPI tối giản: mount static + nạp router wc26
├── wc26.py            # Toàn bộ logic: auth, API, engine kèo + tính tiền
├── static/wc26.html   # Toàn bộ giao diện (1 file: HTML + CSS + JS)
└── wc26_data/         # Dữ liệu JSON (tạo/ghi khi chạy)
    ├── users.json     # 6 tài khoản (pw_hash, display_name, is_admin)
    ├── matches.json   # Danh sách trận (đội, kèo chấp, tỷ số, bet, odd, giờ)
    ├── votes.json     # match_id -> { username: 1|2 }
    ├── sidebets.json  # Kèo lẻ ngoài luồng
    └── sessions.json  # Phiên đăng nhập (không commit)
```

API chính (tiền tố `/api/wc26/`): `login`, `logout`, `me`, `dates`, `matches`, `vote`,
`match` (admin tạo/sửa), `result` (admin nhập tỷ số), `sidebet`, `overview`.

---

## Mô hình tính tiền (chỉ kèo chấp châu Á)

Sau khi đủ 6 người vote một trận, xét theo số phiếu mỗi bên:

- **6–0 đồng thuận** → cược **×2**, cả nhóm theo một bên, lãi/lỗ như nhau.
- **5–1 / 4–2** → cược **bên số đông** (×1), cả 6 lãi/lỗ như nhau (vote thiểu số chỉ
  ảnh hưởng tỷ lệ đoán đúng cá nhân, không ảnh hưởng tiền).
- **3–3 nội chiến** → mỗi người ăn/thua theo đúng bên mình chọn, chuyển 1:1 (không nhân
  odd), tổng nhóm = 0.

Công thức bên số đông: thắng → `hệ_số_kèo × odd × bet`; thua → `hệ_số_kèo × bet`.
Hệ số kèo (`ah_result` trong `wc26.py`) tự tính thắng/thua/hòa, gồm cả thắng-thua **nửa**
khi chấp 0.25 / 0.75. Đơn vị là **điểm thuần**.

Vote lưu theo **bên (1/2)** chứ không theo tên đội → đổi tên đội không ảnh hưởng kết quả.

---

## Ghi chú kỹ thuật

- **Múi giờ:** mọi mốc khóa vote tính theo **GMT+7** (giờ Việt Nam). Vote một trận khóa
  lúc **18:00** ngày diễn ra trận (`VOTE_DEADLINE_HOUR` trong `wc26.py`).
- **Auth** dùng cookie `wc26_session` riêng, độc lập — token lưu trong `sessions.json`.
- Không có database: muốn sao lưu chỉ cần copy thư mục `wc26_data/`.
- Đây là bản tách độc lập từ một app dashboard lớn hơn; đã bỏ phần đường dẫn cứng để
  chạy được ở bất cứ đâu.
