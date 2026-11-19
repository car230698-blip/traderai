# traderai
trade

<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:6bf4ec6226ecfbfc603125c47bf26bac06408703979b7f0a5b75dc094c7a5bb2 -->

# TraderAI — Forex Intelligence

Workspace phân tích forex gồm Python backend, giao diện web tiếng Việt và CLI. Không có thư viện runtime hoặc bước build frontend. Python 3.10+.

## Chạy ứng dụng web

```sh
cp .env.example .env
python -m traderai.server
```

Mở **http://localhost:8000**. Dữ liệu mô phỏng và phân tích định lượng chạy ngay, không cần API key. Để truy cập trong container hoặc sandbox: `python -m traderai.server --host 0.0.0.0 --port 8000`.

### Chức năng

- Theo dõi EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CHF, USD/CAD.
- Biểu đồ nến tương tác; khung 15 phút, 1 giờ, 4 giờ, 1 ngày; bật/tắt EMA20, EMA50; crosshair OHLC và mở rộng biểu đồ.
- Chỉ báo RSI14, MACD(12,26,9), ATR14 theo Wilder; hỗ trợ / kháng cự từ 20 nến. Tính trên 120 nến, có thời gian và nguồn dữ liệu.
- Chế độ định lượng tạo các báo cáo theo quy tắc, xác định dữ liệu còn thiếu. Không giả lập lời gọi LLM.
- Chế độ LLM: bốn analyst (vĩ mô tiền tệ, tâm lý, kỹ thuật, tin tức), tranh luận Bull/Bear từ 1–3 vòng, Trader, Risk Manager và Portfolio Manager. Tiến trình chạy nền, tối đa hai báo cáo đồng thời.
- Tính lot cho tài khoản **USD** với cả USD quote và USD base; chuyển đổi P/L tại giá thoát, làm tròn xuống bước 0.01 lot. Không bao gồm phí, spread, gap và trượt giá.
- Báo cáo lưu SQLite, xem lại, xóa và xuất `.txt`. Không có tích hợp đặt lệnh.

Dữ liệu mô phỏng và lịch kinh tế mẫu được ghi nhãn trên giao diện. Lịch mẫu không được dùng làm bằng chứng cho agent. Dữ liệu mô phỏng dùng để khám phá tính năng, không phản ánh giá thực tế.

## Kết nối dữ liệu và LLM

Điền key vào `.env`, rồi khởi động lại server:

| Chức năng | Biến môi trường |
| --- | --- |
| OpenAI | `OPENAI_API_KEY` |
| Gemini | `GEMINI_API_KEY` |
| Claude | `ANTHROPIC_API_KEY` |
| Endpoint tương thích OpenAI | `TRADERAI_API_KEY`, `TRADERAI_BASE_URL`, `TRADERAI_MODEL` |
| Giá forex Twelve Data | `TWELVE_DATA_API_KEY` |

Chọn nhà cung cấp và model ở **Phân tích AI**. Model mặc định: `gpt-4o-mini`, `gemini-2.5-flash`, `claude-sonnet-4-5`; thay bằng model hỗ trợ API tương ứng và có quyền truy cập trong tài khoản của bạn. Một vòng tranh luận tốn 9 lượt gọi, mỗi vòng thêm 2 lượt. Key chỉ nằm trên server; API cấu hình trả về trạng thái có/không, không trả key.

Chọn **Nguồn: Twelve Data** để gọi time series forex. Quyền forex, độ trễ và hạn mức phụ thuộc gói Twelve Data; ứng dụng không khẳng định dữ liệu là tick thời gian thực. Khi tải thất bại, hiển thị lỗi và giữ dữ liệu trước đó cùng nhãn nguồn, không thay bằng dữ liệu giả.

Ứng dụng chưa tự thu thập tin tức, lịch kinh tế, COT hoặc dữ liệu ngân hàng trung ương. Trong **Phân tích AI → Bổ sung dữ liệu**, nhập JSON có `fundamentals`, `sentiment`, `news`, `portfolio`, `risk_constraints`, kèm nguồn và ngày cập nhật. Giá, chỉ báo và bằng chứng bổ sung sẽ được gửi đến LLM được chọn. Agent vĩ mô phân tích chênh lệch chính sách/lãi suất giữa hai đồng tiền; thiếu dữ liệu phải được nêu rõ. Kết quả LLM là văn bản tự do, không được tự động chuyển thành lệnh giao dịch hay kết luận phê duyệt có cấu trúc.

`.env` hỗ trợ `KEY=value`, giá trị có dấu nháy, comment và `export`; không mở rộng biến. Biến môi trường của process được ưu tiên. `TRADERAI_PROVIDER` và `TRADERAI_MODEL` thiết lập mặc định. `TRADERAI_BASE_URL` ghi đè API base; `OPENAI_BASE_URL` hỗ trợ riêng OpenAI. Chỉ cấu hình endpoint tin cậy.

## Docker

Mặc định container chạy **web server**. Đây là thay đổi so với phiên bản CLI đầu tiên.

```sh
docker compose up --build
# http://localhost:8000
```

Hoặc:

```sh
docker build -t traderai .
docker run --rm -p 127.0.0.1:8000:8000 --env-file .env -v traderai-data:/data traderai
```

SQLite lưu trong volume `/data`. Image chạy bằng user không có quyền root; `.env` và dữ liệu cục bộ được loại khỏi build context. Docker `--env-file` yêu cầu giá trị không bọc dấu nháy và không có tiền tố `export`. `compose.yaml` cho phép thiếu `.env` để chạy chế độ mẫu; cần Docker Compose hỗ trợ `env_file.required` hoặc tạo `.env` trước.

## CLI tương thích

```sh
python -m traderai EUR/USD --data examples/forex.json --provider openai
# Ví dụ công ty cũ vẫn được hỗ trợ:
python -m traderai EXAMPLE --data examples/research.json
```

CLI yêu cầu key của provider. Có thể dùng `--model`, `--rounds`, `--env-file`, `--output`. Đặt `asset_class: forex` và `language: Vietnamese` trong JSON để dùng prompt vĩ mô forex. Các JSON ví dụ chỉ là mẫu cấu trúc, không phải dữ liệu thị trường hiện tại.

Dùng CLI từ image:

```sh
docker run --rm --env-file .env -v "$(pwd)/examples:/inputs:ro" --entrypoint python traderai -m traderai EUR/USD --data /inputs/forex.json
```

## API

Backend và frontend cùng origin, không cần CORS. Phản hồi JSON lỗi có trường `error`.

| Method | Endpoint | Mục đích |
| --- | --- | --- |
| GET | `/api/health` | Readiness |
| GET | `/api/config` | Provider readiness, cặp tiền, khung thời gian |
| GET | `/api/market?pair=EUR%2FUSD&interval=1h&source=demo` | OHLC và chỉ báo; `source=live` dùng Twelve Data |
| GET | `/api/watchlist` | Danh sách theo dõi mô phỏng, ghi nhãn riêng |
| POST | `/api/analysis` | Tạo job; trả HTTP 202 với `id` |
| GET | `/api/analysis/{id}` | Trạng thái, stage hoặc báo cáo |
| DELETE | `/api/analysis/{id}` | Xóa báo cáo đã dừng |
| GET | `/api/history` | 100 báo cáo gần nhất |
| POST | `/api/risk` | Tính khối lượng cho tài khoản USD |

Body phân tích: `{"pair":"EUR/USD","interval":"1h","source":"demo","mode":"quant"}`. LLM dùng `mode: llm`, `provider`, `model`, `rounds` và `evidence` tùy chọn.

Body tính lot: `{"pair":"EUR/USD","balance":10000,"risk_percent":1,"entry":1.1,"stop":1.095,"target":1.11}`. Stop và target phải khác phía so với entry, rủi ro tối đa 5%. Khối lượng trả về có thể bằng 0 nếu ngân sách không đủ cho 0.01 lot.

## Lưu trữ và triển khai

Mặc định DB là `.traderai/workspace.db`; ghi đè bằng `TRADERAI_DB_PATH`. Báo cáo được giữ khi khởi động lại; job đang chạy sẽ được đánh dấu thất bại khi server khởi động lại. Không chạy nhiều process cùng trỏ tới một DB trong khi có job đang chạy. Sao lưu SQLite sau khi dừng server.

Đây là workspace cho một người dùng, mặc định chỉ nghe loopback, chưa có hệ thống đăng nhập. Trước khi công khai server, cần reverse proxy HTTPS và xác thực truy cập. API kiểm tra Origin cho thao tác ghi và giới hạn body 512 KB; frontend render báo cáo như text, không thực thi HTML từ LLM. Không có broker connector hoặc cơ chế giao dịch tự động.

## Kiểm thử

```sh
python -m unittest discover -s tests -v
node --check traderai/web/app.js  # tùy chọn, Node chỉ phục vụ kiểm tra cú pháp
```

Kiểm thử dùng dữ liệu tổng hợp và mock provider, bao gồm chỉ báo, công thức lot, API, SQLite, workflow LLM forex và CLI cũ. Không cần key thật. Dữ liệu thị trường và lời gọi LLM thật cần key cùng quyền truy cập phù hợp.


<!-- /coderabbit-ai-generated:v1 -->