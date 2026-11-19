<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:3203f313f73b7719589e8466346614984fb37e830e7c9e20f4bf9ae8bdafaeb7 -->

<!-- coderabbit-ai-generated-section:v1:ffa42ee57966b7dbf22d5dc93312d160e05336cd9025563b4cbf1553f2158597 -->

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

## Research Lab v0.2

Nâng cấp theo hướng nghiên cứu forex: backtest hai chiến lược EMA Trend và RSI Reversion, nhập CSV OHLC, thư viện cấu hình, sổ thí nghiệm SQLite, so sánh hai kết quả, xuất JSON toàn bộ dữ liệu và CSV từng lệnh. Giao diện **Research Lab** mở từ sidebar; không cần API key với dữ liệu mô phỏng hoặc CSV.

- CSV: cột `time,open,high,low,close`, từ 60–3000 nến, tối đa 450 KB; thời gian ISO 8601 tăng dần, không trùng; thiếu timezone được coi là UTC. Dữ liệu người dùng chưa được xác minh độc lập.
- EMA Trend: tín hiệu close > EMA20 > EMA50 cho BUY, đảo chiều cho SELL. RSI Reversion: BUY khi RSI14 < 30, SELL khi RSI14 > 70. Cần 50 nến khởi tạo. Khi không có vị thế, tín hiệu hiện hữu được phép mở vị thế mới.
- Một vị thế tại một thời điểm; tín hiệu chỉ dùng nến đã đóng, khớp ở open nến kế tiếp. Stop/target cố định theo pip và Reward/Risk. Chi phí spread + slippage khứ hồi được tính khi thoát; sizing dự trù chi phí và bị giới hạn đòn bẩy, làm tròn xuống 0.01 lot.
- Gap qua stop khớp tại open bất lợi. Gap qua target chỉ nhận giá target. Nếu open nằm giữa hai mức nhưng high/low chạm cả hai, ưu tiên stop. Vị thế còn mở đóng tại close nến cuối. Không có swap, commission riêng, margin call hay khớp lệnh tick.
- USD quote tính P/L trực tiếp; USD base quy đổi tại giá thoát. Equity theo close, đã trừ chi phí dự kiến của vị thế mở; drawdown theo equity close, không phải drawdown nội nến. Không tính CAGR/Sharpe trên mẫu ngắn. Profit factor hiển thị `—` nếu không có lệnh lỗ.
- Mỗi thí nghiệm giữ dữ liệu đầu vào, SHA-256, tham số và phiên bản engine. Xóa bộ CSV không làm mất snapshot đã lưu trong backtest. 120 nến tích hợp chỉ phù hợp kiểm tra tính năng; nhập lịch sử dài hơn cho nghiên cứu. So sánh hai kết quả cần kiểm tra nguồn, thời kỳ và giả định giống nhau.

CLI backtest độc lập:

```sh
python -m traderai.backtest EUR/USD --csv examples/forex-ohlc-demo.csv --strategy ema_trend --balance 10000 --risk-percent 1 --spread-pips 1.2 --slippage-pips 0.3 --output result.json
```

Tệp CSV mẫu là **dữ liệu tổng hợp**, không phải giá thật. Thêm API: `GET/POST /api/datasets`, `/api/strategies`, `/api/backtests`; `GET/DELETE /api/{collection}/{id}`. POST dataset nhận `{pair,name,csv}`; strategy nhận `{pair,name,params}`; backtest nhận `{pair,name,interval,source,dataset_id,params}`. Khi có dataset_id, bỏ qua nguồn tích hợp và cặp tiền phải khớp CSV. GET danh sách trả tối đa 100 mục, không trả mảng dữ liệu lớn; GET một backtest trả cả snapshot OHLC, đường vốn và lệnh.

Kho mã dùng duy nhất nhánh `main` theo yêu cầu. GitHub Actions chạy unit tests trên Python 3.10/3.12/3.14, kiểm tra cú pháp JavaScript, cài package và cấu hình Compose khi push main. Các kiểm tra này không gọi API trả phí.


<!-- /coderabbit-ai-generated:v1 -->

## Validation Workbench v0.3

Mở **Kiểm định** ở sidebar để đánh giá chiến lược theo thứ tự thời gian. Mục tiêu là kiểm tra độ bền của một giả thuyết nghiên cứu forex; kết quả không phải lệnh giao dịch hoặc phê duyệt của Portfolio Manager.

1. Chọn lịch sử CSV từ **300–3000 nến**, hoặc mẫu **720 nến 1H tổng hợp cố định từ 2025-01-01**. Mẫu có cả cuối tuần, không phải lịch sử thị trường. Dữ liệu giá tích hợp 120 nến vẫn giữ nguyên cho dashboard/backtest và không đủ cho kiểm định.
2. Đặt trước tỷ lệ train 50–80%, số lệnh tối thiểu, giới hạn drawdown, vốn, rủi ro, đòn bẩy và chi phí. Phần đầu là train, phần sau là holdout; không xáo trộn thời gian.
3. Thử đúng **18 cấu hình** trên train: EMA Trend / RSI Reversion × stop 15/25/40 pip × R/R 1/1.5/2. Chọn lợi nhuận USD sau chi phí cao nhất trong nhóm đủ số lệnh và không vượt drawdown. Hòa điểm: drawdown thấp hơn, rồi strategy/stop/RR tăng dần. Không dùng chỉ số holdout để chọn tham số. Không bắt buộc lợi nhuận train dương; kết luận holdout phản ánh số liệu thực tế.
4. Khóa cấu hình và bắt đầu tài khoản mới trên holdout, cùng vốn ban đầu, không chuyển vị thế từ train. Chỉ báo khởi tạo lại bằng **50 nến ngay trước holdout**, chỉ dùng để warmup; không mở lệnh trong các nến đó. Equity, số lệnh và exposure holdout chỉ tính trên phần đánh giá. Đây không phải cơ chế tiếp tục trạng thái chỉ báo từ toàn bộ lịch sử train.
5. So sánh spread + slippage ở mức ×1, ×1.5, ×2 trên holdout; không chọn lại chiến lược, lot được tái tính theo cùng ngân sách rủi ro. Nếu một loại chi phí vượt giới hạn engine 100 pip, tình huống tương ứng được ghi là không khả dụng.
6. Khi holdout có ít nhất 10 lệnh: bootstrap khối vòng tròn, độ dài khối `min(5, ceil(sqrt(số lệnh)))`, 100–1000 mẫu, seed cố định. Lấy mẫu **P/L USD cố định**, không tái tính sizing, không tính equity nội lệnh, compound hoặc margin call. Phân vị return/drawdown và tỷ lệ mẫu kết thúc lỗ chỉ mô tả phép lấy mẫu lại, không phải xác suất thị trường tương lai.

Kết quả gồm bảng toàn bộ cấu hình train, kết luận theo ngưỡng holdout, đường vốn, nhật ký lệnh, kiểm tra cấu trúc dữ liệu, độ nhạy chi phí, phân phối bootstrap và lịch sử SQLite. Nếu không có cấu hình đủ điều kiện train thì không chạy holdout hoặc tạo kết quả thắng giả. Nếu holdout thiếu lệnh hoặc vượt drawdown, kết luận nêu rõ. Có thể lưu cấu hình đã chọn vào thư viện Research Lab, xuất JSON toàn bộ kết quả hoặc CSV snapshot để tái chạy. Xóa CSV gốc không làm mất snapshot của kiểm định đã lưu.

Kiểm tra dữ liệu báo cáo bước thời gian trung vị, khoảng cách >1.5 lần trung vị, nến high=low, thay đổi close >3% và nến cuối tuần UTC. Không tự điền nến hoặc coi mọi gap là mất dữ liệu; chưa đối chiếu lịch phiên, ngày nghỉ hay tính xác thực của nhà cung cấp.

### CLI kiểm định

```sh
python -m traderai.validation EUR/USD --demo --output validation.json
python -m traderai.validation EUR/USD --csv history.csv --train-percent 70 --min-trades 3 --max-drawdown 20 --balance 10000 --risk-percent 1 --spread-pips 1.2 --slippage-pips 0.3 --leverage 10 --samples 500 --seed 42 --output validation.json
# Sau khi pip install .:
traderai-validate EUR/USD --demo --output validation.json
```

### API kiểm định

- `GET/POST /api/validations`, `GET/DELETE /api/validations/{id}`.
- POST nhận `{pair,name,dataset_id,source,params,options}`. Không có dataset_id thì chỉ hỗ trợ `source: demo` với mẫu cố định 720 nến. Có dataset_id thì dùng CSV, cặp tiền phải khớp bộ dữ liệu.
- `params`: `balance`, `risk_percent`, `leverage`, `spread_pips`, `slippage_pips`. Engine còn nhận strategy/stop/RR nhưng quy trình kiểm định luôn ghi đè ba trường này bằng lưới cố định.
- `options`: `train_percent` (số nguyên 50–80), `min_trades` (1–50), `max_drawdown` (1–100), `samples` (100–1000), `seed` (0–4294967295). Mặc định 70 / 3 / 20 / 500 / 42.
- HTTP 201 khi lưu hoàn tất; tối đa một kiểm định chạy cùng lúc trên process; yêu cầu thứ hai nhận HTTP 400 và thông báo chờ. Phân tích agent vẫn chạy trong pool riêng. Chạy đồng bộ, giới hạn 3000 nến và 18 cấu hình để giới hạn tài nguyên.
- GET danh sách tối đa 100 mục, bỏ các mảng nặng; GET từng mục trả đủ snapshot, SHA-256 toàn dữ liệu và train, phiên bản engine, lựa chọn và giả định. `/api/config` bổ sung `validation_defaults` và `validation_grid`.

Giữ nguyên engine khớp lệnh v1.0 và API/CLI v0.2. Chưa có walk-forward nhiều cửa sổ, dữ liệu tick, broker execution, swap, commission riêng hoặc margin call. Tối ưu và xem lại cùng holdout nhiều lần sẽ làm mất tính độc lập; cần giai đoạn dữ liệu mới trước khi đưa ra kết luận nghiên cứu tiếp theo.


<!-- /coderabbit-ai-generated:v1 -->