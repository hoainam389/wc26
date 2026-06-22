# WC26 — chuyển sang "game chọn đội thu tiền nhậu"

Ngày: 2026-06-22

## Bối cảnh

App hiện tại là mô hình bet kèo chấp châu Á: nhóm vote, hệ thống xác định
"đồng thuận / theo số đông / nội chiến", nhân hệ số kèo (`odd`) với tiền cược
(`bet`), cộng cả kèo lẻ (sidebet) để ra điểm lời/lỗ.

Yêu cầu mới: bỏ mô hình bet, biến thành **game chọn đội để thu tiền nhậu**.
Mỗi người tự chịu trách nhiệm pick của mình; thua thì nộp tiền quỹ nhậu.

## Luật mới

**Giữ nguyên:**
- Kèo chấp châu Á — vẫn nhập `hcap_side` + `hcap` cho mỗi trận; `ah_result`
  vẫn cho ra win / push / thua-nửa / thua-trắng (gồm cả kèo .25/.75).
- Khóa vote lúc 18:00 GMT+7 ngày thi đấu (`_is_locked`).
- 6 tài khoản; admin (Quân) nhập trận và kết quả.

**Bỏ:**
- `odd` (hệ số kèo) và `bet` (tiền cược) — khỏi nhập trận, nhập kết quả, UI.
- Sidebet (kèo lẻ) — toàn bộ storage, API, UI.
- `_scenario` — đồng thuận / theo số đông / ×2 / nội chiến.
- Cơ chế giấu vote tới khi đủ 6 người hoặc khóa — giờ **hiện vote ngay**.
- Jackpot "thua full" — không làm (vòng trong ngày ít trận).

**Tính tiền** — mỗi người độc lập theo pick của chính mình, dựa trên
`r = ah_result(pick, ...)`:

| Kết quả kèo (`r`) | Tiền nộp |
|---|---|
| Thắng (`r > 0`) | 0 |
| Hòa kèo / push (`r == 0`) | 0 |
| Thua nửa (`r == -0.5`) | 25 |
| Thua trắng (`r == -1`) | 50 |

Công thức: `tien = -r * 50` khi `r < 0`, ngược lại `0`.
(`r = -0.5 → 25`, `r = -1 → 50`.)

**Phạt không vote:** với mỗi trận **đã có kết quả**, người **không vote** bị
tính **50** (như thua trắng). Phần phạt này **không** tính vào đúng/sai/% — chỉ
trận có vote thật mới vào thống kê chính xác. Trong `detail`, người không vote
có `result = "novote"`.

Lưu và hiển thị **số trần** (50 / 25 / 0), không thêm hậu tố "k".

**Bảng tổng:**
- "Điểm" của mỗi người = **tổng tiền phải nộp**.
- Xếp hạng: **nộp ít nhất lên đầu** (chọn giỏi nhất top 1).
- Vẫn giữ thống kê đúng/sai/hòa (correct/wrong/push) và biểu đồ tích lũy
  (giờ là tiền nộp tích lũy theo ngày).

## Thay đổi code

### `wc26.py`

- **Bỏ sidebet:** xóa `SIDEBETS_FILE`, `_sidebets()`, route `POST /api/wc26/sidebet`,
  `GET /api/wc26/sidebets`, và phần cộng sidebet trong `compute_overview`.
- **Bỏ `_scenario`:** xóa hàm. Mọi nơi đang dùng (`compute_overview`, `wc26_matches`,
  `waiting`) chuyển sang không còn khái niệm scenario/mode/mult.
- **`_match_pnl` viết lại:** với mỗi user đã vote, tính
  `r = ah_result(pick, hcap_side, hcap, s1, s2)`; `out[user] = -r * 50 if r < 0 else 0`.
  Không dùng `odd`, `bet`, `mult`, `bet_side`.
- **`compute_overview`:**
  - Bỏ `sidebets`, bỏ `scenario`/`mode` khỏi `per_match` và `waiting`.
  - `totals[u]` = tổng tiền nộp; `standings.sort(key=lambda x: x["points"])`
    (tăng dần — ít nhất lên đầu).
  - `by_date` / `series` giữ nguyên cơ chế tích lũy (giờ là tiền nộp).
  - `detail[].pnl` = tiền nộp của user ở trận đó.
- **`wc26_save_match`:** bỏ `odd`, `bet` khỏi payload.
- **`wc26_result`:** bỏ xử lý `odd`, `bet` — chỉ nhận `score1`, `score2`.
- **`wc26_matches`:** bỏ field `odd`, `bet`, `scenario`, `mode`; **luôn** trả
  `votes` (hiện vote ngay), bỏ điều kiện `full or locked`. Vẫn trả `my_vote`,
  `voters`, `locked`, `winner`.
- **`_keo_winner`:** giữ nguyên.

### `static/wc26.html`

- Bỏ ô nhập `odd`, `bet` ở form thêm/sửa trận và form nhập kết quả.
- Bỏ toàn bộ UI sidebet (form thêm + danh sách).
- Bỏ hiển thị scenario / "🔥 Đồng thuận ×2" / "⚔️ Nội chiến".
- Hiện vote của mọi người ngay (không chờ đủ 6 / khóa).
- Bảng tổng: đổi nhãn cột "điểm" → "tiền nộp"; hiển thị số trần.
- Chi tiết trận: hiển thị tiền nộp mỗi người (0 / 25 / 50).

### Dữ liệu

- `wc26_data/sidebets.json` không còn dùng — có thể xóa hoặc để mặc kệ
  (code không đọc nữa).
- Các trận cũ trong `matches.json` có field `odd`/`bet` thừa — vô hại, code
  mới bỏ qua. `_match_pnl` cũ từng phụ thuộc `odd`/`bet` nên **điểm lịch sử sẽ
  được tính lại** theo luật mới khi mở bảng tổng (đây là hành vi mong muốn).

## Không thay đổi

- Auth, session, lock 18:00, kết cấu Redis/file storage (phần deploy Vercel).
- `ah_result`, `_settle_half`, `_ko_key`, `_keo_winner`.

## Kiểm thử

- Trận thắng kèo → 0; hòa kèo → 0; thua nửa (.25/.75 ra -0.5) → 25; thua trắng → 50.
- Bảng tổng: tổng đúng, xếp tăng dần.
- API matches trả `votes` ngay cả khi chưa đủ 6 và chưa khóa.
- Vote sau 18:00 vẫn bị chặn (403).
