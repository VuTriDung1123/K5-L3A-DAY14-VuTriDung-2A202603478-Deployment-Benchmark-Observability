# Benchmark & Observability Report — Day 14

> Mọi con số dưới đây được trích xuất trực tiếp từ các file JSON trong `reports/` (và CSV/screenshot thực tế ở Phần 4–5).

**Họ tên:** Vũ Trí Dũng — MSSV: 2A202603478  
**Ngày chạy:** 2026-11-25  
**Môi trường:** Windows + WSL2 Ubuntu (Python 3.12.3), Docker Desktop 29.5.3 / Docker Compose v5.1.4

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
| --- | --- | --- |
| p95 latency `/ask` | ≤ 500 ms | Đảm bảo 95% người dùng nhận phản hồi dưới 0.5 giây (trải nghiệm tương tác mượt); khớp ngưỡng mặc định của `load_test.py` (`--slo-p95-ms 500`) và chặt hơn ngưỡng alert Prometheus (`> 0.8s`). |
| Error rate `/ask` | ≤ 2.0% | Cho phép error budget 2% để hấp thụ lỗi ngẫu nhiên từ upstream LLM (~1% `MOCK_ERROR_RATE`) mà không gây alert fatigue, đồng thời chặt hơn ngưỡng alert (`> 5%`). |
| Accuracy trên golden dataset | ≥ 85% (mục tiêu 100% sau sửa KB, 0 regression) | Đảm bảo agent trả lời chính xác phần lớn câu hỏi kỹ thuật cốt lõi và không làm giảm chất lượng so với phiên bản trước mỗi lần deploy. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2, 300 requests, `MOCK_SLOW_RATE=0.03`)

*Nguồn dữ liệu: `reports/load_v2_c1.json`, `reports/load_v2_c10.json`, `reports/load_v2_c50.json`, `reports/load_v2_c100.json`.*

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO (`p95 ≤ 500ms`, `err ≤ 2%`) |
| ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| 1 | 4.42 | 185.5 | 218.9 | 1676.1 | 1.00% | ✅ PASS |
| 10 | 37.86 | 188.5 | 221.2 | 1704.5 | 0.33% | ✅ PASS |
| 50 | 112.12 | 194.0 | 252.0 | 1682.6 | 1.00% | ✅ PASS |
| 100 | 141.04 | 202.7 | 1657.9 | 1742.6 | 0.67% | ❌ FAIL |

**Nhận xét:** RPS **không tăng tuyến tính** theo concurrency:
- Từ `concurrency = 1 → 10` (tăng 10×): RPS tăng từ `4.42 → 37.86 req/s` (~8.6×) vì phần lớn thời gian mỗi request là chờ I/O bất đồng bộ (retrieval + LLM), nên event loop tận dụng tốt khoảng thời gian chờ để phục vụ song song.
- Từ `10 → 50` (tăng 5×): RPS chỉ tăng ~2.96× (`37.86 → 112.12 req/s`), và từ `50 → 100` (tăng 2×) RPS chỉ tăng thêm ~26% (`112.12 → 141.04 req/s`).
- **Nguyên nhân bão hòa:** Khi concurrency lớn trên 1 tiến trình Uvicorn duy nhất, chi phí chuyển ngữ cảnh trong event loop, đóng/mở kết nối HTTP và xử lý JSON bắt đầu tích tụ, đồng thời với tổng 300 request thì vài request chậm đột biến (~1.7s, straggler) kéo dài thời gian kết thúc toàn đợt (`duration_s = 2.13s`) và đẩy `p95` vọt lên `1657.9ms` làm vi phạm SLO.

---

### 2.2 Tail latency (agent v2, 300 requests, `concurrency=20`)

*Nguồn dữ liệu: `reports/load_v2_slow_0.json`, `reports/load_v2_slow_0.03.json`, `reports/load_v2_slow_0.1.json`.*

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) | RPS | SLO |
| --- | ---: | ---: | ---: | ---: | :---: |
| `0` | 188.4 | 214.7 | 220.7 | 103.88 | ✅ PASS |
| `0.03` (mặc định) | 239.6 | 222.2 | 1710.8 | 59.77 | ✅ PASS |
| `0.1` | 353.7 | 1696.4 | 1710.7 | 48.04 | ❌ FAIL |

**Nhận xét:**
- **`p99` và `p95` là các chỉ số nhạy nhất với tail latency:**
  - Khi `MOCK_SLOW_RATE` tăng từ `0` lên `0.03` (3% request chậm), `avg` chỉ tăng `51.2ms` (`188.4 → 239.6ms`), trong khi **`p99` nhảy vọt gấp 7.75 lần** (`220.7 → 1710.8ms`).
  - Khi tăng lên `0.1` (10% request chậm, vượt ngưỡng 5% của p95), **`p95` bùng nổ gấp 7.6 lần** (`222.2 → 1696.4ms`) làm vi phạm SLO (`≤ 500ms`), dù `avg` lúc này vẫn chỉ là `353.7ms`.
- **Vì sao SLO không nên đặt theo average?** Trung bình cộng bị chi phối bởi số đông request nhanh (90–97%) nên che giấu hoàn toàn trải nghiệm rất tệ của nhóm người dùng gặp tail latency. Đặt SLO theo `p95`/`p99` phản ánh trực tiếp trải nghiệm tệ nhất mà 1%–5% người dùng thực sự phải chịu.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

*Nguồn dữ liệu: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`.*

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
| --- | ---: | ---: | ---: |
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Latency p50 / p95 (ms) | 163.7 / 186.9 | 186.7 / 203.2 | 183.1 / 214.8 |
| Avg tokens / câu | 57.4 | 109.0 | 114.3 |
| Tổng cost (USD) | $0.000409 | $0.000759 | $0.000796 |
| Cost / câu đúng (USD) | $0.00040875 | $0.00003616 | $0.00003462 |
| Quality gate | ❌ FAIL | ✅ PASS (`≥ 80%`) | ✅ PASS (`≥ 100%`, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách sửa (sửa `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` và đồng bộ sang `production/utils/mock_llm.py`, không sửa `golden_dataset.jsonl`):**

| ID | Keyword bị thiếu | Đã sửa gì |
| --- | --- | --- |
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry `(["jwt"], ...)` vào `KNOWLEDGE_BASE` giải thích sự khác nhau giữa API key (cố định, không tự hết hạn) và JWT (token có chữ ký số, chứa thông tin user và thời điểm hết hạn, xác minh stateless). |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry `(["hpa", "kubernetes", "autoscal"], ...)` vào `KNOWLEDGE_BASE` giải thích Kubernetes HPA tự động scale số pod dựa trên CPU, memory hoặc custom metrics (RPS, độ dài hàng đợi). |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**
- **Chất lượng vs Chi phí:** So với `v1`, `v2` (sau khi sửa KB) tốn trung bình gần gấp đôi số token (`57.4 → 114.3 tokens/câu`) và tổng chi phí tăng gần 2× (`$0.000409 → $0.000796`) do phải đưa ngữ cảnh retrieval vào prompt. Đổi lại, độ chính xác nhảy vọt từ **`4.3%` lên `100.0%`**, giúp chỉ số **cost / câu đúng giảm tới ~11.8 lần** (`$0.00040875 → $0.00003462`). Do đó, *cost / câu đúng* phản ánh hiệu quả kinh tế thực chất hơn nhiều so với *cost / câu*.
- **Latency:** `v2` chậm hơn `v1` khoảng ~20–28ms ở `p50`/`p95` (`163.7 → 183.1ms`) do thêm bước retrieval (`MOCK_RETRIEVAL_MS=20ms`) và prompt dài hơn — mức đánh đổi rất nhỏ so với lợi ích tăng +95.7 điểm % độ chính xác.

**CI Quality Gate & Metric Instrumentation (Exercise 7.1 & 7.3):**
- **Exercise 7.1 (Metrics & Cardinality):** Đã thêm Histogram `agent_question_length_chars` vào `develop/app.py` (quan sát được trên `/metrics` cùng Counter `http_requests_total`, Gauge `agent_in_flight_requests`, Histogram `http_request_duration_seconds`). Middleware dùng `route.path` (template) thay vì `request.url.path` để tránh bùng nổ cardinality khi bot quét hàng nghìn URL ngẫu nhiên làm tràn RAM Prometheus.
- **Exercise 7.3 (CI Quality Gate):** Đã kiểm chứng chạy `run_eval.py` cho `v1` với `--baseline reports/eval_v2.json` trả **`exit code = 1`** (phát hiện 20 câu regression, `Quality gate ❌ FAIL`). Đã tạo workflow CI tại [`.github/workflows/eval.yml`](.github/workflows/eval.yml) chạy `python eval/run_eval.py --url http://localhost:8002 --min-accuracy 0.85` trên mỗi Pull Request: nếu accuracy dưới ngưỡng hoặc có regression, script thoát với exit code `1` làm job CI fail và chặn merge.

---

## 4. Observability stack (production)

### 4.1 Screenshot & Unit test Alert Rules

- **Unit test alert rules (`promtool`):** Đã chạy `docker run --rm -v "$PWD/prometheus:/p" --entrypoint promtool prom/prometheus:v3.16.0 test rules /p/alert_rules_test.yml` → **`SUCCESS`** (tất cả test case cho `AgentHighErrorRate` 10% vs 1% và `AgentInstanceDown` đều PASS).
- **Screenshots** (trong thư mục `screenshots/`):
  - Dashboard Grafana khi đang có tải: [`screenshots/grafana-dashboard.png`](screenshots/grafana-dashboard.png)
  - Trace chậm trong Jaeger (`1234577e4ea81cb805ae80c7ef72cd36`): [`screenshots/jaeger-slow-trace.png`](screenshots/jaeger-slow-trace.png)
  - Trace lỗi trong Jaeger (`e7fc0eb9f0db9ce4a4985d37f200e0d2`): [`screenshots/jaeger-error-trace.png`](screenshots/jaeger-error-trace.png)
  - Trang Alerts của Prometheus với **4/4 alert đang `firing` cùng lúc**: [`screenshots/prometheus-alert-firing.png`](screenshots/prometheus-alert-firing.png)

### 4.2 Trả lời 4 câu hỏi Exercise 7.4 (quan sát thực tế từ Prometheus & Grafana dưới tải `scale=3`)

1. **p95 và avg đang là bao nhiêu? Khoảng cách giữa chúng nói lên điều gì?**
   - Truy vấn Prometheus ngay dưới tải bình thường (`scale=3`, `MOCK_SLOW_RATE=0.03`): **`avg = 231.2 ms`** (`0.231s`), **`p95 = 293.0 ms`** (`0.293s`), còn `p99` trên Locust đạt **`1700 ms`** (`1.7s`).
   - Khoảng cách lớn giữa `avg` (~231 ms) và tail latency `p99` (~1700 ms, gấp >7×) chứng minh tồn tại nhóm ~3% request chậm đột biến (tail latency) mà trung bình cộng không thể hiện rõ; khi `MOCK_SLOW_RATE` tăng lên `0.3` thì `p95` cũng vọt lên `1.94s`.
2. **Panel "Requests/s theo instance": Nginx có chia đều traffic cho các instance không?**
   - **Có, chia rất đều** nhờ `server agent:8000 resolve` kết hợp round-robin trên Docker DNS: đo thực tế trên Prometheus ở tải 3 instance cho thấy `172.21.0.5:8000` đạt **`20.33 req/s`**, `172.21.0.8:8000` đạt **`20.33 req/s`**, và `172.21.0.9:8000` đạt **`20.06 req/s`**.
3. **Vì sao `input tokens/s` lớn hơn `output tokens/s`?**
   - Số đo thực tế trên Prometheus: **`input = 4,665.1 tokens/s`** so với **`output = 2,444.5 tokens/s`** (gấp ~1.91 lần). Nguyên nhân là agent `v2` (RAG) ghép `SYSTEM_PROMPT` + tài liệu ngữ cảnh lấy từ `KNOWLEDGE_BASE` + câu hỏi của user vào mỗi input prompt, trong khi câu trả lời output ngắn gọn hơn.
4. **`curl -i http://localhost:8080/metrics` (hoặc cổng Nginx `18080` khi tránh đụng cổng) trả về gì? Vì sao?**
   - Trả về **`HTTP/1.1 404 Not Found`** vì trong `nginx/nginx.conf` có rule `location = /metrics { return 404; }`. Không được public `/metrics` ra internet vì nó lộ thông tin nội bộ hệ thống (tên route, lưu lượng, tỉ lệ lỗi, mô hình, chi phí...); chỉ Prometheus trong mạng nội bộ `obs_net` mới được scrape trực tiếp `agent:8000/metrics`.

### 4.3 Thí nghiệm "phá hệ thống" (Exercise 7.6)

*Đo thời gian thực tế bằng cách theo dõi Prometheus `/api/v1/alerts` sau khi tiêm lỗi (`Locust 30 users`) — ở thí nghiệm A+B+C+D cả 4 alert đã chuyển sang `firing` đồng thời:*

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → pending / firing | Panel nào phản ánh rõ nhất |
| --- | --- | --- | --- | --- |
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (`severity: critical`) | `pending`: **20.0s** → `firing`: **80.1s** (`Error rate: 18.97%`, vượt ngưỡng 5% trong `for: 1m`) | Golden Signals → **Error rate** (đỏ) & LLM calls `ok`/`error` |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (`severity: warning`) | `pending`: **10.0s** → `firing`: **130.2s** (`p95: 1.94s`, vượt ngưỡng 1s trong `for: 2m`) | Golden Signals → **p95** (đỏ) & Latency & Traffic (`p95`/`p99`) |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`severity: warning`) | `firing` ngay (tốc độ chi tiêu tăng vọt lên **`$8.99/giờ`**, vượt ngưỡng `$2/giờ` trong `for: 2m`) | Golden Signals → **Cost 1h** & LLM → **Cost USD/giờ** |
| D | `docker pause k5-day14-observability-agent-4` | `AgentInstanceDown` (`severity: critical`) | `pending`: **15.0s** → `firing`: **45.0s** kể từ lúc pause (`up{instance="172.21.0.5:8000"} == 0` trong `for: 30s`) | Golden Signals → **Instances** (giảm 1) & Requests/s theo instance |
| E | `AGENT_VERSION=v1` (`MOCK_ERROR_RATE=0.01`, `MOCK_SLOW_RATE=0.03`) | **Không có alert chất lượng nào firing** | — (chỉ `agent_info` đổi sang `version="v1"` và `agent_retrieval_total` biến mất) | LLM → **Retrieval hit ratio** (mất dữ liệu) & bảng **Instances / Version** |

**Phân tích các điểm quan trọng từ thí nghiệm:**
- **Vì sao dùng `docker pause` mà không `docker stop` ở thí nghiệm D?** Prometheus tìm các instance agent qua `dns_sd_configs`. Nếu `docker stop`, container biến mất khỏi Docker DNS nên Prometheus chỉ xem là không còn target (không báo down). Khi `docker pause`, container vẫn nằm trong DNS nhưng tiến trình bị đóng băng không trả `/metrics` → `up == 0` → kích hoạt `AgentInstanceDown`. Ngoài ra, các lỗi `504` khi Nginx chờ quá `proxy_read_timeout` không hiện trên panel Error rate của agent vì request không được agent xử lý xong, nên production cần giám sát thêm ở tầng Load Balancer / synthetic check ngoài.
- **Thí nghiệm E không làm alert nào firing. Phát hiện sự cố tụt chất lượng trong production bằng cách nào?**
  1. **Chặn từ trước khi deploy (CI/CD):** Chạy eval tự động trên `golden_dataset` với quality gate (`run_eval.py --min-accuracy 0.85 --baseline ...`, exit code 1 chặn merge PR).
  2. **Giám sát chất lượng online trên production:** Theo dõi các metric nghiệp vụ đặc thù của RAG/LLM (ví dụ cảnh báo khi **retrieval hit ratio** tụt bất thường, độ dài câu trả lời/token giảm mạnh, hoặc `agent_info{version}` thay đổi), kết hợp **online sampling eval** (dùng LLM-as-judge chấm mẫu 1–5% traffic thật) và theo dõi tín hiệu phản hồi người dùng (thumbs up/down, tỉ lệ hỏi lại).

### 4.4 Debug bằng trace (Exercise 7.5 — Jaeger + JSON Log)

#### Trace chậm nhất (Slow Trace)
- **`trace_id`:** `1234577e4ea81cb805ae80c7ef72cd36`
- **Tổng thời gian (`POST /ask`):** **`1717.2 ms`**
- **Phân rã từng span trong Jaeger:**
  - `POST /ask`: `1717.2 ms` (`100.0%`)
  - `agent.run`: `1715.1 ms` (`99.9%`)
  - `agent.retrieve_context`: `16.7 ms` (`1.0%`)
  - **`chat mock-llm-small` (span chậm nhất):** **`1698.3 ms` (`98.9%`)** → chứng tỏ nút thắt nằm ở lời gọi upstream LLM (tail latency), không phải code FastAPI hay bước retrieval.
- **Dòng log JSON tương ứng (grep từ `docker compose -p k5-day14-observability logs agent` theo đúng `trace_id`):**

```json
{"ts": "2026-11-25T09:26:51.538965+00:00", "level": "INFO", "service": "observable-agent", "instance": "94c7478e4727", "event": "llm_call", "trace_id": "1234577e4ea81cb805ae80c7ef72cd36", "span_id": "fd8a44d03668d2b4", "request_id": "ea723d87a7d9", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 95, "output_tokens": 55, "cost_usd": 4.7e-05, "llm_ms": 1698.5}
{"ts": "2026-11-25T09:26:51.539427+00:00", "level": "INFO", "service": "observable-agent", "instance": "94c7478e4727", "event": "http_request", "trace_id": "1234577e4ea81cb805ae80c7ef72cd36", "span_id": "fd8a44d03668d2b4", "request_id": "ea723d87a7d9", "method": "POST", "route": "/ask", "status": 200, "ms": 1716.8}
```

#### Trace lỗi (Error Trace)
- **`trace_id`:** `e7fc0eb9f0db9ce4a4985d37f200e0d2`
- **Tổng thời gian (`POST /ask`):** `118.0 ms` (`agent.retrieve_context`: `20.4 ms`, `chat mock-llm-small`: `95.4 ms` kèm event `exception`)
- **Dòng log JSON tương ứng (`llm_error` + `http_request` status `503`):**

```json
{"ts": "2026-11-25T09:28:21.025957+00:00", "level": "INFO", "service": "observable-agent", "instance": "46e4a73170d9", "event": "llm_error", "trace_id": "e7fc0eb9f0db9ce4a4985d37f200e0d2", "span_id": "38898e8e49513352", "request_id": "f9b431df7b7a", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
{"ts": "2026-11-25T09:28:21.026335+00:00", "level": "INFO", "service": "observable-agent", "instance": "46e4a73170d9", "event": "http_request", "trace_id": "e7fc0eb9f0db9ce4a4985d37f200e0d2", "span_id": "38898e8e49513352", "request_id": "f9b431df7b7a", "method": "POST", "route": "/ask", "status": 503, "ms": 117.3}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

*Nguồn dữ liệu: `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv` (lưu ý: đã sửa lỗi thiếu `ENV PYTHONUSERBASE=/home/agent/.local` trong `production/Dockerfile` để container agent khởi chạy đúng, và dùng `--no-deps` khi chạy Locust để giữ đúng số replica 1 vs 3).*

### Bảng tổng hợp (`Aggregated` — gồm `POST /ask` + `GET /health`)

| Số instance | Tổng reqs | RPS | Avg (ms) | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **1** (`scale_1`) | 7,888 | 66.03 | 218.3 | 190 | 230 | 1700 | 75 (0.95%) |
| **3** (`scale_3`) | 7,880 | 66.00 | 213.6 | 190 | 220 | 1700 | 77 (0.98%) |

### Chi tiết riêng endpoint `POST /ask`

| Số instance | Reqs (`/ask`) | RPS (`/ask`) | Avg (ms) | p50 (ms) | p95 (ms) | p99 (ms) | Failures (503) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **1** (`scale_1`) | 7,228 | 60.50 | 237.8 | 190 | 230 | 1700 | 75 (1.04%) |
| **3** (`scale_3`) | 7,181 | 60.15 | 234.1 | 190 | 220 | 1700 | 77 (1.07%) |

**Giải thích kết quả:** Scale từ 1 lên 3 instance **chỉ giảm nhẹ `p95` từ `230ms` xuống `220ms`**, `p99` giữ nguyên `1700ms`, còn RPS gần như không đổi (`66.03` vs `66.00 req/s`). Nguyên nhân:
1. **Nút thắt nằm ở upstream LLM latency, không phải CPU của agent:** Mỗi request chờ bất đồng bộ (`asyncio`) gọi retrieval + mock LLM mất ~190–220ms (và 3% chậm ~1700ms). 1 container FastAPI/Uvicorn async đã dư sức gánh ~66 req/s I/O-bound, nên thêm instance không làm câu trả lời từ LLM nhanh hơn (chỉ giảm nhẹ overhead xử lý HTTP như thấy ở `/health`: `p95` giảm từ `9ms → 5ms`, `max` giảm từ `122ms → 59ms`).
2. **Tải sinh ra là closed-loop cố định 100 user** (mỗi user chờ ngẫu nhiên `0.5–2s` giữa các request), nên lưu lượng đầu vào tối đa bị chặn ở `~100 / (1.25s + 0.22s) ≈ 66–68 req/s`.
3. **Lợi ích thực sự của 3 instance ở đây là High Availability & khả năng chịu tải cao hơn:** Khi tăng đột biến lên hàng trăm/nghìn user hoặc khi 1 instance bị treo/deploy mới, 2 instance còn lại vẫn phục vụ mượt mà không sập hệ thống.

---

## 6. Kết luận

- **3 điều học được về Benchmark & Observability:**
  1. **Đo đúng chỉ số thay vì nhìn trung bình:** `p95`/`p99` vạch trần tail latency mà `avg` che giấu hoàn toàn; đồng thời trong đánh giá AI Agent cần tách rõ *hiệu năng* (load test) với *chất lượng* (eval trên golden dataset) và ưu tiên chỉ số `cost / câu đúng`.
  2. **Ba trụ cột Metrics – Traces – Logs phải liên kết chặt với nhau:** Prometheus/Grafana báo động *có vấn đề gì* (4 Golden Signals + chi phí LLM), Jaeger chỉ ra *chậm hay lỗi ở span nào* (`chat mock-llm-small` chiếm `98.9%`), và `trace_id` trong structured JSON log cho phép truy ngược chi tiết request trong vài giây.
  3. **Hạ tầng xanh chưa chắc AI Agent đúng:** Thí nghiệm E (`AGENT_VERSION=v1`) chứng minh lỗi tụt chất lượng không làm kích hoạt alert hạ tầng; bắt buộc phải kết hợp CI quality gate (chặn merge bằng exit code) với giám sát tín hiệu đặc thù của AI/RAG.
- **Nếu đưa agent này lên production thật, cần thêm metric / alert nào nữa?**
  - **Tầng Edge/Load Balancer & Synthetic Monitoring:** Metric status `502`/`504` từ Nginx/Ingress và probe kiểm tra định kỳ từ bên ngoài (để bắt sự cố như lỗi 504 khi agent bị treo mà metric nội bộ của agent không ghi nhận).
  - **Metric bảo mật & vận hành Redis:** Tỉ lệ bị chặn `401` (dấu hiệu dò API key), tỉ lệ `429` (rate limit), tỉ lệ `402` (user chạm budget), độ trễ & trạng thái kết nối Redis (`redis_up`, latency ping).
  - **Metric chất lượng AI online:** Alert khi `retrieval_hit_ratio` giảm đột ngột (ví dụ `< 50%` trong 5 phút), tỉ lệ câu trả lời fallback/rỗng, độ trễ **TTFT** (*Time To First Token*) nếu bật streaming, và điểm đánh giá từ online LLM-as-judge / phản hồi người dùng.

