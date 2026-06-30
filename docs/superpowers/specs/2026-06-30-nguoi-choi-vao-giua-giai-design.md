# Người chơi vào giữa giải — tính điểm từ ngày join

Ngày: 2026-06-30

## Bối cảnh

App wc26 (`wc26.py` + `static/wc26.html`) tính toàn bộ thống kê động từ store
`wc26:users` trong `compute_overview()`. Mọi người chơi trong store đều bị duyệt
qua **mọi** trận đã có kết quả. Trận đã tính mà không vote → bị **phạt 50 + tính
thua** (`result="novote"`), không phải "skip".

Hệ quả: vừa thêm người chơi mới `thanh.bui` (Thành). Nếu để nguyên, Thành bị phạt
50 cho **toàn bộ** trận cũ → tụt sâu xuống âm ngay khi vừa vào. Không hợp lý —
mong muốn: **Thành chỉ bắt đầu tính từ hôm nay (2026-06-30) trở đi.**

Hôm nay có đúng 3 trận chưa đá (chưa có kết quả); mọi trận trước đó đều đã xong.
Nên mốc cắt theo ngày là gọn và không mơ hồ.

## Mục tiêu

- Người chơi vào giữa giải chỉ được tính (tiền/đúng-sai/biểu đồ/hợp cạ) từ ngày
  họ tham gia trở đi.
- Cơ chế **chung, dữ liệu hóa** — lần sau thêm người giữa giải chỉ set 1 field,
  không sửa code.
- Không thay đổi gì với người chơi gốc.

## Không làm (YAGNI)

- Không làm UI quản trị thêm/sửa người chơi.
- Không hỗ trợ "rời giải" (chỉ join, không leave).
- Không cắt theo giờ/trận lẻ — cắt theo **ngày** (`date`), đủ cho app vui nội bộ.

## Thiết kế

### 1. Field `since` trên user record

Thêm `"since": "YYYY-MM-DD"` vào record user trong `wc26:users`:

```json
"thanh.bui": { "pw_hash": "...", "display_name": "Thành",
               "is_admin": false, "since": "2026-06-30" }
```

- User **không có** `since` = thành viên gốc → tính từ đầu (hành vi cũ y nguyên).
- User có `since` → chỉ tính các trận `match.date >= since`.

### 2. Sửa `compute_overview()` trong `wc26.py`

Định nghĩa helper: với 1 trận, user **đủ điều kiện tham gia** khi
`users[u].get("since") is None or users[u]["since"] <= match["date"]`.

Trong vòng lặp từng trận đã có kết quả (không phải `nocount`):

- **Tiền (`_match_pnl`)**: chỉ truyền danh sách user đủ điều kiện cho trận đó
  → user chưa join không bị tính tiền.
- **Chi tiết (`detail`)**: user chưa join → emit
  `{result: "notyet", pick: None, team: None, pnl: None}`
  (không cộng `acc`, không cộng `totals`, không vào `by_date`).
- **Đúng/sai/hòa (`acc`)** và **`totals`**: chỉ cập nhật cho user đủ điều kiện.
- **Hợp cạ**: không cần sửa — user chưa join không có pick ở trận đó nên mọi
  nhóm chứa họ tự bị bỏ qua (đã có `if any(p is None ...): continue`).

### 3. Biểu đồ tiền tích lũy

Trong vòng dựng `series`: với mỗi user, ngày `d < since` → append `None` (không
tích lũy); từ ngày `>= since` mới bắt đầu cộng dồn. Chart.js mặc định ngắt đường
ở `null` nên đường của người mới **bắt đầu từ ngày join**, không phải đường phẳng
ở 0 kéo từ đầu giải.

### 4. Frontend `static/wc26.html`

Thêm nhánh render cho `result === 'notyet'` (cạnh `'skip'` và `'novote'` ở
~dòng 917): hiện **mờ** chữ "chưa tham gia" (dùng class mờ như `.vt.mut`), không
hiện tiền. Phân biệt với `'skip'` (trận nocount, hiện "—") để rõ đây là "người
này chưa vào giải lúc đó".

Màu người chơi và cột header tự sinh từ danh sách user — không cần sửa.

## Kiểm thử

Sau khi sửa, chạy `compute_overview()` với dữ liệu prod (read-only) và xác nhận:

1. **Người gốc không đổi**: standings/points/chart của 6 người cũ giống hệt trước
   khi sửa (so sánh trước/sau).
2. **Thành sạch**: không bị phạt cho trận cũ — `points = 0`, `correct/wrong/push
   = 0` khi chưa có trận nào `>= 2026-06-30` có kết quả.
3. **Chi tiết trận cũ**: dòng Thành = `result:"notyet"`, `pnl: None`.
4. **Biểu đồ**: `series["thanh.bui"]` toàn `null` cho các ngày trước `since`.
5. **Hợp cạ**: không có cặp/bộ ba nào chứa Thành (chưa đủ trận cùng chọn).
6. Khi 1 trận `>= since` có kết quả mà Thành không vote → bị `novote` + phạt 50
   (đúng luật, vì lúc đó anh đã "trong giải").

## Triển khai

- Sửa `wc26.py` + `static/wc26.html` (local), test bằng dữ liệu prod read-only.
- Cập nhật field `since` cho `thanh.bui` trên `wc26:users` (KV) bằng ghi cộng dồn
  — KHÔNG `--force` toàn bộ key (giữ nguyên `NamL`/`NamN` và data cũ).
- Commit (người dùng tự push).
