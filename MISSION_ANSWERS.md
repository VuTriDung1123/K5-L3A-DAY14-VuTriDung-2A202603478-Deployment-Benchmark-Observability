# Day 14 Lab — Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns phát hiện trong `01-localhost-vs-production/develop/app.py`

Đọc `01-localhost-vs-production/develop/app.py` phát hiện **8 anti-pattern** không phù hợp cho production:

1. **Hardcode secrets trực tiếp trong mã nguồn (dòng 17–18):**
   - `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`.
   - **Hậu quả:** Khi push lên Git (đặc biệt repo public), bot tự động quét GitHub có thể đánh cắp key trong vài giây để đốt tiền API hoặc truy cập trái phép DB. Ngoài ra không thể xoay (rotate) key mà không sửa code và deploy lại.
   - **Cách bản `production` sửa:** Chuyển toàn bộ sang biến môi trường trong `production/config.py` (dòng 27, 32: `os.getenv("OPENAI_API_KEY", "")`, `os.getenv("AGENT_API_KEY", "")`), chỉ commit file mẫu `.env.example`, kèm hàm `validate()` (dòng 37–46) fail-fast nếu `ENVIRONMENT=production` mà thiếu `AGENT_API_KEY`.

2. **Hardcode cấu hình ứng dụng, không tách config khỏi code (dòng 21–22):**
   - `DEBUG = True`, `MAX_TOKENS = 500` viết cứng trong code.
   - **Hậu quả:** Muốn đổi cấu hình giữa `dev` / `staging` / `production` phải sửa code và build lại, vi phạm nguyên tắc 12-Factor (*III. Config*).
   - **Cách bản `production` sửa:** Tập trung quản lý cấu hình trong dataclass `Settings` (`production/config.py`, dòng 14–50) đọc từ biến môi trường (`DEBUG`, `MAX_TOKENS`, `ENVIRONMENT`, `LLM_MODEL`, `ALLOWED_ORIGINS`...).

3. **Dùng `print()` thay cho structured logging và làm lộ secret ra log (dòng 33–38):**
   - Dùng `print(f"[DEBUG] ...")`, đặc biệt dòng 34 in thẳng API key ra stdout: `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")`.
   - **Hậu quả:** Log dạng text tự do rất khó parse/lọc/truy vấn trên hệ thống tập trung (Loki, Datadog, ELK), không có level/timestamp chuẩn, và làm rò rỉ thông tin nhạy cảm vào hệ thống log.
   - **Cách bản `production` sửa:** Dùng module `logging` định dạng JSON (`production/app.py`, dòng 28–32) và chỉ log metadata an toàn như `event`, `question_length`, `client_ip`, `response_length` (dòng 111–122), tuyệt đối không log secret.

4. **Không có Health Check / Readiness / Metrics endpoint (dòng 42–43):**
   - Gọi `GET /health` trả về `404 Not Found`.
   - **Hậu quả:** Nền tảng cloud (Railway, Render, Kubernetes) và Load Balancer không biết container còn sống hay đã treo (liveness), cũng không biết app đã khởi động xong chưa để điều hướng traffic (readiness).
   - **Cách bản `production` sửa:** Bổ sung `GET /health` (dòng 135–149), `GET /ready` trả `200` hoặc `503` theo cờ `is_ready` (dòng 152–161), và `GET /metrics` (dòng 164–173).

5. **Bind cứng `host="localhost"` và `port=8000` (dòng 51–52):**
   - `host="localhost"` chỉ lắng nghe giao diện loopback `127.0.0.1`, nên khi đóng gói vào Docker container hoặc đưa lên cloud thì traffic từ bên ngoài không thể kết nối tới.
   - `port=8000` cố định sẽ lỗi trên các PaaS (Railway/Render) vốn cấp cổng động qua biến môi trường `PORT`.
   - **Cách bản `production` sửa:** Đọc `HOST` (mặc định `0.0.0.0`) và `PORT` (mặc định `8000`) từ env (`production/config.py`, dòng 17–18; `production/app.py`, dòng 196–197).

6. **Bật cứng `reload=True` (chế độ debug auto-reload) trong server (dòng 53):**
   - **Hậu quả:** Watcher theo dõi file (`WatchFiles`) tốn CPU/RAM, tạo tiến trình reloader thừa và có thể gây restart bất ngờ hoặc lộ thông tin debug trên production.
   - **Cách bản `production` sửa:** `reload=settings.debug` (`production/app.py`, dòng 198), với `DEBUG` mặc định là `false`.

7. **Không có lifecycle management và không xử lý Graceful Shutdown (`SIGTERM`):**
   - **Hậu quả:** Khi nền tảng deploy bản mới hoặc scale-in gửi tín hiệu `SIGTERM`, tiến trình tắt đột ngột làm cắt ngang request đang xử lý, gây lỗi `502/504` cho người dùng hoặc hỏng dữ liệu.
   - **Cách bản `production` sửa:** Dùng FastAPI `lifespan` (`production/app.py`, dòng 39–68) chuyển `is_ready = False` trước khi thoát để hoàn tất in-flight requests, kết hợp đăng ký `signal.signal(signal.SIGTERM, handle_sigterm)` (dòng 180–189).

8. **Thiếu chuẩn hóa API input, error handling và CORS (dòng 30–31):**
   - `POST /ask` nhận `question` qua query parameter thay vì JSON body, không kiểm tra input rỗng, không cấu hình `CORSMiddleware`.
   - **Cách bản `production` sửa:** Đọc JSON body, kiểm tra thiếu/rỗng `question` trả về `422 Unprocessable Entity` rõ ràng (`production/app.py`, dòng 102–108), và cấu hình `CORSMiddleware` giới hạn theo `ALLOWED_ORIGINS` (dòng 77–82).

---

### Exercise 1.2: Chạy và kiểm thử bản `develop`

Chạy trong WSL2 Ubuntu (`Python 3.12.3`, `os.name = posix`) tại thư mục `01-localhost-vs-production/develop/`:

```bash
python app.py
```

Kết quả gọi các endpoint bằng `curl`:

1. **`GET http://localhost:8000/`** → `200 OK`
```http
HTTP/1.1 200 OK
content-type: application/json

{"message":"Hello! Agent is running on my machine :)"}
```

2. **`POST "http://localhost:8000/ask?question=Hello"`** (bản develop nhận `question` qua query param) → `200 OK`
```http
HTTP/1.1 200 OK
content-type: application/json

{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

3. **`GET http://localhost:8000/health`** → `404 Not Found` (không có health check)
```http
HTTP/1.1 404 Not Found
content-type: application/json

{"detail":"Not Found"}
```

4. **Log của server `develop`** cho thấy rõ anti-pattern bật reloader và in thẳng secret ra màn hình:
```text
INFO:     Uvicorn running on http://localhost:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [400] using WatchFiles
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.
INFO:     127.0.0.1:55726 - "POST /ask?question=Hello HTTP/1.1" 200 OK
INFO:     127.0.0.1:55730 - "GET /health HTTP/1.1" 404 Not Found
```

---

### Exercise 1.3: Chạy bản `production` và bảng so sánh Develop vs Production

Chạy tại `01-localhost-vs-production/production/`:

- `GET /` → `200 OK`: `{"app":"AI Agent","version":"1.0.0","environment":"development","status":"running"}`
- `GET /health` → `200 OK`: `{"status":"ok","uptime_seconds":0.3,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T07:28:54.058590+00:00"}`
- `GET /ready` → `200 OK`: `{"ready":true}`
- `GET /metrics` → `200 OK`: `{"uptime_seconds":0.3,"environment":"development","version":"1.0.0"}`
- `POST /ask` với JSON `{"question": "Hello"}` → `200 OK`: `{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","model":"gpt-4o-mini"}`
- `POST /ask` với JSON `{}` → `422 Unprocessable Entity`: `{"detail":"question field is required"}`
- Khi khởi động không có `OPENAI_API_KEY`, `Settings.validate()` cảnh báo rõ ràng (`WARNING:root:OPENAI_API_KEY not set — using mock LLM`) và lắng nghe tại `http://0.0.0.0:8000`; khi nhận `SIGTERM`, server thực hiện shutdown tuần tự (`Waiting for application shutdown` → `Application shutdown complete`).

#### Bảng so sánh chi tiết

| Tiêu chí (Feature) | Develop (`develop/app.py`) | Production (`production/app.py` + `config.py`) | Tại sao quan trọng trong Production? |
| --- | --- | --- | --- |
| **Config & Secrets** | Hardcode trực tiếp trong code (`OPENAI_API_KEY`, `DATABASE_URL`, `DEBUG=True`, `MAX_TOKENS=500`) | Đọc tập trung qua dataclass `Settings` từ biến môi trường (`os.getenv`), có `.env.example` và `validate()` fail-fast | Tránh lộ bí mật khi push Git; dễ thay đổi cấu hình giữa dev/staging/prod mà không cần sửa code; phát hiện lỗi thiếu cấu hình ngay lúc khởi động thay vì crash giữa chừng. |
| **Network Binding & Port** | Cố định `host="localhost"`, `port=8000` | Đọc `HOST` (mặc định `0.0.0.0`) và `PORT` (mặc định `8000`) từ env | Container và PaaS (Railway/Render) yêu cầu lắng nghe trên `0.0.0.0` để nhận request từ bên ngoài và dùng cổng động do nền tảng inject qua biến `PORT`. |
| **Debug / Auto-reload** | Bật cứng `reload=True` | `reload=settings.debug` (mặc định `False`) | Tắt file watcher giúp tiết kiệm CPU/RAM, tránh restart bất thường và không làm lộ thông tin debug cho người dùng cuối. |
| **Health & Readiness Check** | Không có (`GET /health` → `404`) | Có `GET /health` (liveness + uptime/version), `GET /ready` (trả `200`/`503` theo `is_ready`), `GET /metrics` | Orchestrator biết khi nào container treo để tự restart (`/health`) và Load Balancer chỉ route traffic vào instance đã sẵn sàng (`/ready`), giảm lỗi khi rolling deploy. |
| **Logging** | `print()` tự do, in thẳng `OPENAI_API_KEY` ra stdout | `logging` có cấu trúc JSON (`time`, `level`, `msg`), chỉ ghi metadata (`question_length`, `client_ip`), không ghi secret | Log JSON dễ thu thập, tìm kiếm, tạo alert trên Loki/Datadog/ELK; không làm rò rỉ thông tin nhạy cảm qua hệ thống log. |
| **Lifecycle & Shutdown** | Không xử lý `SIGTERM`, tắt đột ngột | Có `lifespan` (startup/shutdown, hạ `is_ready=False`) và đăng ký `signal.signal(signal.SIGTERM, handle_sigterm)` | Khi deploy phiên bản mới hoặc scale-in, server ngừng nhận request mới và hoàn tất các request đang xử lý trước khi thoát, tránh lỗi 502/504 và mất dữ liệu. |
| **API Contract & Security** | Nhận `question` qua query param, không validate rỗng, không cấu hình CORS | Nhận JSON body, validate thiếu `question` trả `422`, cấu hình `CORSMiddleware` theo `ALLOWED_ORIGINS` | Chuẩn hóa giao tiếp REST API, ngăn request lỗi gây crash, và kiểm soát nguồn gốc trình duyệt được phép gọi API. |

---

## Part 2: Docker

### Exercise 2.1: Phân tích `02-docker/develop/Dockerfile`

1. **Base image là gì?**
   - `python:3.11` (dòng 8: `FROM python:3.11`). Đây là image đầy đủ gồm hệ điều hành Debian, Python 3.11 runtime cùng nhiều thư viện/công cụ hệ thống nên dung lượng lớn.
2. **Working directory là gì?**
   - `/app` (dòng 11: `WORKDIR /app`). Mọi lệnh `COPY`, `RUN`, `CMD` phía sau đều thực thi tương đối theo thư mục `/app` trong container.
3. **Tại sao `COPY requirements.txt` đứng trước `COPY . .` (hoặc `COPY app.py`)?**
   - Để tận dụng **Docker layer cache**. Docker cache từng instruction theo thứ tự từ trên xuống; nếu một layer thay đổi thì toàn bộ các layer sau nó bị vô hiệu hóa cache và phải chạy lại. Vì `requirements.txt` ít thay đổi hơn mã nguồn (`app.py`), việc copy và chạy `pip install` trước giúp các lần build sau khi chỉ sửa code vẫn tái sử dụng được layer dependencies, build nhanh hơn rất nhiều.
4. **`CMD` vs `ENTRYPOINT` khác nhau thế nào?**
   - **`CMD`:** Khai báo lệnh (hoặc tham số) mặc định khi container khởi chạy, và **dễ dàng bị ghi đè** nếu truyền lệnh mới ở cuối `docker run <image> <command>`.
   - **`ENTRYPOINT`:** Cố định chương trình thực thi chính của container; các tham số truyền thêm ở cuối `docker run` sẽ được nối vào sau `ENTRYPOINT` (muốn ghi đè phải dùng cờ `--entrypoint`). Trong thực tế thường kết hợp `ENTRYPOINT` (chương trình cố định) với `CMD` (tham số mặc định).

---

### Exercise 2.2: Build và chạy container `my-agent:develop`

Build từ thư mục gốc repository (vì Dockerfile copy `02-docker/develop/...` và `utils/mock_llm.py` tính từ build context gốc):

```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run -d --name cp2-dev -p 8000:8000 my-agent:develop
```

Kết quả kiểm thử gọi container (bản develop nhận `question` qua query param):

1. **`GET http://localhost:8000/`** → `200 OK`
```http
HTTP/1.1 200 OK
content-type: application/json

{"message":"Agent is running in a Docker container!"}
```

2. **`GET http://localhost:8000/health`** → `200 OK`
```http
HTTP/1.1 200 OK
content-type: application/json

{"status":"ok","uptime_seconds":0.4,"container":true}
```

3. **`POST "http://localhost:8000/ask?question=What%20is%20Docker%3F"`** → `200 OK`
```http
HTTP/1.1 200 OK
content-type: application/json

{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

---

### Exercise 2.3: Multi-stage build (`02-docker/production/Dockerfile`) và so sánh kích thước

- **Stage 1 (`FROM python:3.11-slim AS builder`):** Cài các gói build hệ thống (`gcc`, `libpq-dev`) và chạy `pip install --no-cache-dir --user -r requirements.txt` để cài toàn bộ thư viện Python vào `/root/.local`. Image trung gian này không dùng để deploy.
- **Stage 2 (`FROM python:3.11-slim AS runtime`):** Bắt đầu từ image `python:3.11-slim` sạch hoàn toàn, tạo non-root user `appuser`, chỉ `COPY --from=builder /root/.local /home/appuser/.local`, copy `main.py` và `utils/mock_llm.py`, chuyển sang `USER appuser`, cấu hình `HEALTHCHECK` và khởi chạy `uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2`.
- **Tại sao image nhỏ hơn và tốt hơn cho production?**
  - Dùng base image `python:3.11-slim` thay vì `python:3.11` đầy đủ.
  - Toàn bộ compiler/build tools (`gcc`, `libpq-dev`, headers) ở Stage 1 bị loại bỏ khỏi image cuối cùng → giảm kích thước mạnh, pull/deploy nhanh hơn và giảm bề mặt tấn công (attack surface), đồng thời tăng bảo mật nhờ chạy bằng non-root user `appuser`.

**Kết quả đo thực tế bằng `docker images`:**

```bash
docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
docker images my-agent --format "table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}"
```

```text
REPOSITORY   TAG        IMAGE ID       SIZE
my-agent     advanced   66aced01da89   240MB
my-agent     develop    0bae89b98958   1.67GB
```

- **Develop (`my-agent:develop`):** `1.67 GB` (`1,670 MB`)
- **Production (`my-agent:advanced`):** `240 MB`
- **Chênh lệch:** Giảm `1,430 MB` — nhỏ hơn **`85.6%`** (nhẹ hơn ~6.96 lần).

---

### Exercise 2.4: Docker Compose stack (`02-docker/production/docker-compose.yml`)

#### Sơ đồ kiến trúc và cách các service giao tiếp

```text
                        Host (ports 80 / 443)
                                  │
                                  ▼
                  ┌───────────────────────────────┐
                  │   nginx (nginx:alpine)        │
                  │   Reverse Proxy + Rate Limit  │
                  │   Security Headers            │
                  └───────────────┬───────────────┘
                                  │ proxy_pass http://agent:8000
                                  ▼
 ┌─────────────────────────────────────────────────────────────────┐
 │                 Docker bridge network: internal                 │
 │                                                                 │
 │                 ┌──────────────────────────────┐                │
 │                 │   agent (FastAPI / Uvicorn)  │                │
 │                 │   port 8000 (chỉ nội bộ)     │                │
 │                 └───────┬──────────────┬───────┘                │
 │     redis://redis:6379/0│              │http://qdrant:6333      │
 │                         ▼              ▼                        │
 │            ┌─────────────────┐  ┌─────────────────────┐         │
 │            │ redis:7-alpine  │  │ qdrant/qdrant:v1.9  │         │
 │            │ port 6379       │  │ port 6333           │         │
 │            └────────┬────────┘  └──────────┬──────────┘         │
 │                     │                      │                    │
 │                     ▼                      ▼                    │
 │           [vol: redis_data]      [vol: qdrant_data]             │
 └─────────────────────────────────────────────────────────────────┘
```

- **4 service khởi chạy:** `nginx`, `agent`, `redis`, `qdrant`.
- **Cách giao tiếp & cách ly:**
  - Cả 4 container nối vào cùng bridge network `internal`, gọi nhau qua Docker internal DNS bằng tên service (`agent:8000`, `redis:6379`, `qdrant:6333`).
  - Chỉ `nginx` publish cổng ra máy host (`80:80`, `443:443`); `agent`, `redis` và `qdrant` không mở cổng ra ngoài, toàn bộ traffic đi qua Nginx (áp dụng security headers và rate limit `10r/s`, miễn rate limit cho `/health`).
  - `agent` khai báo `depends_on` với `condition: service_healthy` tới `redis` (`redis-cli ping`) và `qdrant` (kiểm tra TCP cổng 6333) nên chỉ khởi động khi hạ tầng lưu trữ đã sẵn sàng.
  - Dữ liệu Redis và Qdrant được lưu bền vững trong hai named volumes (`redis_data`, `qdrant_data`).

#### Kết quả chạy và kiểm thử qua Nginx

Chạy bằng `docker compose -p k5-day14-docker up -d --build` (sau khi tạo `.env.local`):

```text
NAME                       IMAGE                   SERVICE   STATUS                           PORTS
k5-day14-docker-agent-1    k5-day14-docker-agent   agent     Up 1 second (health: starting)   8000/tcp
k5-day14-docker-nginx-1    nginx:alpine            nginx     Up 1 second                      0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
k5-day14-docker-qdrant-1   qdrant/qdrant:v1.9.0    qdrant    Up 12 seconds (healthy)          6333-6334/tcp
k5-day14-docker-redis-1    redis:7-alpine          redis     Up 12 seconds (healthy)          6379/tcp
```

1. **`GET http://localhost/health`** → `200 OK` (qua Nginx, có security headers):
```http
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":0.5,"version":"2.0.0","timestamp":"2026-11-25T08:05:12.402061"}
```

2. **`GET http://localhost/ready`** → `200 OK`: `{"ready":true}`
3. **`GET http://localhost/`** → `200 OK`: `{"app":"AI Agent","version":"2.0.0","environment":"staging"}`
4. **`POST http://localhost/ask`** với `{"question": "Explain microservices"}` → `200 OK`:
```http
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json

{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

Sau khi kiểm thử đã dọn sạch stack bằng `docker compose -p k5-day14-docker down -v` và xóa file tạm `.env.local`.

---

## Part 3: Cloud Deployment

### Exercise 3.1: Deploy Agent Part 6 (`06-lab-complete/`) lên Railway

- **Nền tảng chính:** Railway (project `day14-ai-agent`, gồm 2 service đang chạy ở trạng thái `SUCCESS`: `agent` build từ `06-lab-complete/Dockerfile` + `railway.toml`, và `Redis` `redis:8.2` gắn qua biến tham chiếu `REDIS_URL=${{Redis.REDIS_URL}}`).
- **Public URL:** https://agent-production-31921a2c.up.railway.app
- **Chi tiết triển khai & lệnh test:** Xem [DEPLOYMENT.md](DEPLOYMENT.md)
- **Screenshots:** `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`

**Kết quả chạy 4 lệnh tự kiểm CP6 trên URL public:**
```text
GET  /health          -> 200  ({"status":"ok","version":"1.0.0","environment":"production",...})
GET  /ready           -> 200  ({"ready":true,"redis":"connected","in_flight_requests":1})
POST /ask (no key)    -> 401  ({"detail":"Invalid or missing API key. Provide header X-API-Key."})
POST /ask (valid key) -> 200  (trả về JSON answer, cost_usd, requests_remaining)
```

---

### Exercise 3.2: So sánh `railway.toml` và `render.yaml`

So sánh dựa trên cả file mẫu trong `03-cloud-deployment/` và file cấu hình đã viết trong `06-lab-complete/`:

| Tiêu chí | `railway.toml` (Railway) | `render.yaml` (Render Blueprint) |
| --- | --- | --- |
| **Định dạng & phạm vi** | TOML, cấu hình cho **một service** cụ thể (đặt ngay trong thư mục service như `06-lab-complete/railway.toml`). | YAML (Infrastructure as Code Blueprint), có thể khai báo **nhiều service cùng lúc** trong 1 file (cả `type: web` lẫn `type: keyvalue`/`redis`). |
| **Build & Runtime** | Chọn builder (`builder = "DOCKERFILE"` hoặc `"NIXPACKS"`), `dockerfilePath`, có thể ghi đè `startCommand`. | Khai báo tường minh `runtime: docker` (hoặc `python`), `dockerfilePath`, `buildCommand`, `startCommand`, kèm `region` và `plan` (`free`/`starter`...). |
| **Health check & Restart** | `healthcheckPath = "/health"`, `healthcheckTimeout = 30`, cùng chính sách restart (`restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries = 3`). | `healthCheckPath: /health` và `autoDeploy: true` (tự deploy khi push nhánh GitHub); không cần khai báo restart policy thủ công. |
| **Biến môi trường & Secrets** | Không khai báo danh sách env trong `railway.toml`; quản lý qua CLI (`railway variable set`) hoặc Dashboard, nối service bằng cú pháp tham chiếu `${{Redis.REDIS_URL}}`. | Khai báo trực tiếp schema `envVars` ngay trong YAML, hỗ trợ tự sinh secret (`generateValue: true`), nhập tay trên dashboard (`sync: false`), và nối Redis qua `fromService`. |
| **Luồng triển khai thực tế** | Rất thuận tiện cho monorepo/thư mục con (`cd 06-lab-complete && railway up`), tạo Redis add-on độc lập qua CLI/UI. | Theo hướng GitOps (Blueprint đọc từ gốc repo khi connect GitHub); nếu app nằm trong thư mục con thì phải cấu hình thêm `rootDir` hoặc tự khai báo `dockerfilePath` và Redis add-on. |

---

### Exercise 3.3: Phân tích CI/CD Pipeline GCP Cloud Run (`03-cloud-deployment/production-cloud-run/`)

Đọc `cloudbuild.yaml` và `service.yaml`, pipeline CI/CD cho GCP Cloud Run đi qua 4 bước tuần tự (`waitFor`) mỗi khi push lên nhánh `main`:
1. **`test`:** Chạy container `python:3.11-slim` cài `requirements.txt` + `pytest` và thực thi `pytest tests/` để chặn build nếu unit test lỗi.
2. **`build`:** Build Docker image gắn đồng thời 2 tag `$COMMIT_SHA` (truy vết chính xác phiên bản) và `latest`, tận dụng layer cache từ image `latest` (`--cache-from`).
3. **`push`:** Đẩy toàn bộ các tag vừa build lên Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **`deploy`:** Gọi `gcloud run deploy` triển khai image `$COMMIT_SHA` lên Cloud Run tại `asia-southeast1` (`min-instances=1` để tránh cold start, `max-instances=10`, `512Mi` RAM / `1` CPU, timeout `60s`) và nạp secret từ Google Secret Manager qua `--set-secrets`. File `service.yaml` (Knative Service IaC) mô tả cấu hình tương đương kèm `containerConcurrency: 80`, `livenessProbe` (`GET /health`), `startupProbe` (`GET /ready`) và tham chiếu secret bằng `secretKeyRef`.

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/app.py`)

**Phân tích code:**
1. **API key được kiểm tra ở đâu?**
   - Trong dependency `verify_api_key` (`develop/app.py`, dòng 39–54), đọc header `X-API-Key` qua `APIKeyHeader(name="X-API-Key", auto_error=False)` và đối chiếu với biến môi trường `AGENT_API_KEY`.
   - Dependency được gắn vào endpoint bảo vệ `POST /ask` qua `_key: str = Depends(verify_api_key)` (dòng 70); các endpoint public như `/` và `/health` không yêu cầu key.
2. **Điều gì xảy ra nếu thiếu hoặc sai key?**
   - Thiếu header `X-API-Key` → trả về **`401 Unauthorized`** (`Missing API key...`).
   - Có header nhưng sai giá trị → trả về **`403 Forbidden`** (`Invalid API key.`).
3. **Làm sao rotate key an toàn?**
   - Không hardcode key trong code mà đọc từ biến môi trường / Secrets Manager. Để rotate không gây downtime (zero-downtime), cho phép hệ thống chấp nhận đồng thời nhiều key hợp lệ (ví dụ danh sách phân tách bằng dấu phẩy trong env hoặc lưu trong Redis/DB): thêm key mới song song key cũ → cập nhật client chuyển sang key mới → thu hồi key cũ.

**Kết quả kiểm thử thực tế (`AGENT_API_KEY=secret-key-123 python app.py`):**

- **Không có API Key → `401 Unauthorized`:**
```http
HTTP/1.1 401 Unauthorized
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
```

- **Sai API Key (`X-API-Key: wrong-key`) → `403 Forbidden`:**
```http
HTTP/1.1 403 Forbidden
content-type: application/json

{"detail":"Invalid API key."}
```

- **Đúng API Key (`X-API-Key: <MASKED>`) → `200 OK`:**
```http
HTTP/1.1 200 OK
content-type: application/json

{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

---

### Exercise 4.2: JWT Authentication (`04-api-gateway/production/`)

**Cơ chế JWT trong `auth.py`:**
- Client gửi `username` và `password` tới `POST /auth/token` → `authenticate_user()` kiểm tra thông tin đăng nhập → `create_token()` ký JWT bằng thuật toán `HS256` với `JWT_SECRET`, payload chứa `sub` (username), `role` (`user`/`admin`), `iat` và `exp` (hết hạn sau 60 phút).
- Khi gọi `POST /ask`, `verify_token()` đọc header `Authorization: Bearer <token>`, xác thực chữ ký và thời hạn token hoàn toàn **stateless** (không cần truy vấn DB mỗi request): thiếu token → `401`, hết hạn → `401`, token không hợp lệ → `403`.

**Kết quả kiểm thử thực tế (tài khoản `student` / `demo123`, đã che token):**

- **Gọi `POST /ask` không có JWT → `401 Unauthorized`:**
```http
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}
```

- **Lấy token tại `POST /auth/token` → `200 OK`:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...<MASKED>",
  "token_type": "bearer",
  "expires_in_minutes": 60,
  "hint": "Include in header: Authorization: Bearer <MASKED>"
}
```

- **Gọi `POST /ask` với `Authorization: Bearer <MASKED>` → `200 OK`:**
```http
HTTP/1.1 200 OK
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"question":"Explain JWT","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","usage":{"requests_remaining":9,"budget_remaining_usd":1.6e-05}}
```

---

### Exercise 4.3: Rate Limiting (`04-api-gateway/production/rate_limiter.py`)

**Phân tích code:**
1. **Thuật toán sử dụng:** **Sliding Window Log** (mỗi `user_id` có một `deque` lưu timestamp của các request trong cửa sổ thời gian; trước khi đếm, vòng `while` loại bỏ các timestamp cũ hơn `now - window_seconds` bằng `popleft()`).
2. **Giới hạn (limit):** Tài khoản `user` (`rate_limiter_user`) là **10 requests/phút** (`window_seconds=60`); tài khoản `admin` (`rate_limiter_admin`) là **100 requests/phút**.
3. **Cách phân biệt / bypass giới hạn cho admin:** Trong `app.py` (dòng 141), đọc `role` từ JWT payload để chọn limiter tương ứng (`rate_limiter_admin if role == "admin" else rate_limiter_user`), hoặc có thể bỏ qua bước kiểm tra limiter nếu `role == "admin"`.

**Kết quả chạy vòng lặp vượt ngưỡng 10 req/phút (tài khoản `student`):**

```text
Request  1 -> HTTP 200 (requests_remaining: 9)
Request  2 -> HTTP 200 (requests_remaining: 8)
...
Request  9 -> HTTP 200 (requests_remaining: 1)
Request 10 -> HTTP 200 (requests_remaining: 0)
Request 11 -> HTTP 429 | {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
Request 12 -> HTTP 429 | {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
Request 13 -> HTTP 429 | {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

Output đầy đủ `curl -i` khi bị chặn **`429 Too Many Requests`**:
```http
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795594125
retry-after: 59
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

---

### Exercise 4.4: Cost Guard và lý do cần cả Rate Limit lẫn Cost Guard

**Cơ chế Cost Guard:**
- Trong `04-api-gateway/production/cost_guard.py`, hệ thống theo dõi số input/output tokens theo đơn giá model (`$0.00015 / 1K input`, `$0.0006 / 1K output`), kiểm tra ngân sách **trước khi gọi LLM** ở 2 mức: ngân sách toàn hệ thống (`global_daily_budget_usd = $10/ngày` → vượt trả `503`) và ngân sách từng user (`daily_budget_usd = $1/ngày` → vượt trả `402 Payment Required`), đồng thời cảnh báo khi dùng tới `80%`. Kiểm tra thực tế sau 10 request qua `GET /me/usage`:
  ```json
  {"user_id":"student","date":"2026-11-25","requests":10,"input_tokens":40,"output_tokens":308,"cost_usd":0.000191,"budget_usd":1.0,"budget_remaining_usd":0.999809,"budget_used_pct":0.0}
  ```
- **Cách triển khai chuẩn Production với Redis (budget $10/tháng):**
  - Thay vì lưu dict trong RAM (mất dữ liệu khi restart và sai lệch khi chạy nhiều instance), lưu chi phí tích lũy trên Redis với key theo tháng `budget:{user_id}:{YYYY-MM}`.
  - Trước khi gọi LLM: đọc `current = float(r.get(key) or 0)`, nếu `current + estimated_cost > 10.0` thì chặn và trả về HTTP **`402 Payment Required`**.
  - Khi còn ngân sách: cộng chi phí bằng lệnh nguyên tử `r.incrbyfloat(key, cost)` và đặt `r.expire(key, 32 * 24 * 3600)` (32 ngày) để sang tháng mới tự động bắt đầu với key `YYYY-MM` mới và dọn key cũ.

**Vì sao cần CẢ Rate Limit VÀ Cost Guard?**
- **Rate Limit bảo vệ tốc độ và hạ tầng:** Ngăn người dùng/bot gửi ồ ạt request trong thời gian ngắn gây quá tải CPU/RAM server hoặc chạm giới hạn RPM của nhà cung cấp LLM.
- **Cost Guard bảo vệ ngân sách (tiền):** Một người dùng vẫn có thể tuân thủ đúng rate limit (ví dụ gửi đều đặn 9 request/phút suốt cả ngày với prompt/context rất dài tốn nhiều token) và làm phát sinh hóa đơn lớn mà không bao giờ bị `429`. Ngược lại, chỉ có Cost Guard thì không ngăn được spam request ngắn gây nghẽn hệ thống. Do đó hệ thống AI Agent ở production phải áp dụng song song cả hai lớp bảo vệ.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health Check (`/health`) vs Readiness Check (`/ready`)

Đọc `05-scaling-reliability/develop/app.py` và `production/app.py`:

| Tiêu chí | Liveness Probe (`GET /health`) | Readiness Probe (`GET /ready`) |
| --- | --- | --- |
| **Câu hỏi trả lời** | *"Process / container còn sống không?"* | *"Instance này đã sẵn sàng nhận traffic từ người dùng chưa?"* |
| **Ai sử dụng & hành động khi fail** | Orchestrator (Docker, Kubernetes, Railway/Render) → **restart container** nếu trả non-200 hoặc timeout. | Load Balancer (Nginx, Ingress, Service) → **ngừng route traffic mới** vào instance đó (chuyển sang instance khỏe khác), **không** restart container. |
| **Khi nào trả lỗi (`503`)** | Chỉ fail khi bản thân tiến trình app bị treo/chết. Không nên phụ thuộc cứng vào dependency ngoài (như Redis) để tránh vòng lặp restart vô ích khi Redis tạm chập chờn. | Trả **`503 Service Unavailable`** khi app đang khởi động (`_is_ready = False`), đang shutdown, hoặc dependency bắt buộc (Redis/DB) mất kết nối (`_redis.ping()` lỗi). |

**Kết quả kiểm thử thực tế trên `05-scaling-reliability/develop/app.py`:**

- `GET /health` → `200 OK`:
```json
{"status":"ok","uptime_seconds":0.3,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T08:11:11.637587+00:00","checks":{"memory":{"status":"ok","used_percent":14.0}}}
```
- `GET /ready` → `200 OK`:
```json
{"ready":true,"in_flight_requests":1}
```

---

### Exercise 5.2: Graceful Shutdown (`SIGTERM`)

**Cơ chế hoạt động trong `05-scaling-reliability/develop/app.py`:**
- Middleware `track_requests` tăng/giảm biến đếm `_in_flight_requests` theo từng request đang xử lý.
- Đăng ký `signal.signal(signal.SIGTERM, handle_sigterm)` kết hợp `timeout_graceful_shutdown=30` của Uvicorn và FastAPI `lifespan`:
  1. Khi nền tảng gửi `SIGTERM`, server ngừng nhận kết nối mới và chuyển `_is_ready = False` (`/ready` trả `503` để Load Balancer thôi gửi traffic tới).
  2. Uvicorn đợi toàn bộ request đang xử lý hoàn tất (`Waiting for connections to close`, vòng chờ `_in_flight_requests == 0` tối đa 30 giây).
  3. Đóng kết nối sạch sẽ rồi mới thoát tiến trình.

**Kết quả kiểm thử thực tế (gửi đồng thời 2 request `POST /ask` rồi gửi `kill -TERM $PID` sau 0.3 giây):**
- Cả 2 request đang chạy đều **hoàn thành với `HTTP 200`**, không bị ngắt kết nối giữa chừng:
```text
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
[Req1 HTTP 200]
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
[Req2 HTTP 200]
```
- Log của server xác nhận trình tự tắt an toàn:
```text
INFO:     Shutting down
INFO:     127.0.0.1:52834 - "POST /ask?question=Long%20task%201 HTTP/1.1" 200 OK
INFO:     Waiting for connections to close. (CTRL+C to force quit)
INFO:     127.0.0.1:52838 - "POST /ask?question=Long%20task%202 HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
2026-11-25 15:11:17,816 INFO 🔄 Graceful shutdown initiated...
2026-11-25 15:11:17,816 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [3652]
2026-11-25 15:11:17,816 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

---

### Exercise 5.3: Thiết kế Stateless và lý do lưu state trong RAM bị hỏng khi scale

- **Vì sao state trong RAM bị hỏng khi chạy nhiều instance?**
  - Mỗi container/instance có không gian bộ nhớ RAM tách biệt. Khi scale ngang (`--scale agent=3`) đứng sau Load Balancer (Nginx round-robin):
    - Request 1 của User A rơi vào `agent-1` → lịch sử hội thoại / bộ đếm rate limit lưu trong RAM của `agent-1`.
    - Request 2 của User A rơi vào `agent-2` → `agent-2` không có dữ liệu đó trong RAM → mất ngữ cảnh hội thoại (hoặc rate limit bị nhân 3 lần do mỗi instance đếm riêng).
    - Ngoài ra, khi restart hoặc deploy bản mới, toàn bộ dữ liệu trong RAM bị xóa sạch.
- **Cách `05-scaling-reliability/production/app.py` giải quyết:**
  - Chuyển toàn bộ session & conversation history sang **Redis** (`save_session` dùng `_redis.setex(f"session:{session_id}", 3600, serialized)`, `load_session` dùng `_redis.get(...)`, giữ tối đa 20 messages/session với TTL 1 giờ). Nhờ vậy mọi instance đều bình đẳng (stateless) và có thể thêm/bớt instance bất kỳ lúc nào mà không mất trạng thái người dùng.

---

### Exercises 5.4 & 5.5: Load Balancing 3 Instance với Nginx và kiểm thử `test_stateless.py`

Chạy stack trong `05-scaling-reliability/production/` với `-p k5-day14-scaling` và `--scale agent=3` *(lưu ý: máy cục bộ đang có container `sep_adminer` giữ cổng `8080`, nên chạy với Compose override tạm map Nginx sang cổng `18080:80` mà không sửa file đề bài)*:

```text
NAME                       IMAGE                    SERVICE   STATUS                    PORTS
k5-day14-scaling-agent-1   k5-day14-scaling-agent   agent     Up 13 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-2   k5-day14-scaling-agent   agent     Up 13 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-3   k5-day14-scaling-agent   agent     Up 14 seconds (healthy)   8000/tcp
k5-day14-scaling-nginx-1   nginx:alpine             nginx     Up 13 seconds             0.0.0.0:18080->80/tcp
k5-day14-scaling-redis-1   redis:7-alpine           redis     Up 24 seconds (healthy)   6379/tcp
```

**Kết quả chạy `test_stateless.py` (gửi 5 câu hỏi liên tiếp trong cùng 1 `session_id` qua `POST /chat` rồi đọc `/chat/{session_id}/history`):**

```text
============================================================
Stateless Scaling Demo
============================================================

Session ID: 6685c2db-5ba6-436a-a07d-ad5bbfc262d4

Request 1: [instance-4ca8e6]  Q: What is Docker?
Request 2: [instance-9c254c]  Q: Why do we need containers?
Request 3: [instance-1734d4]  Q: What is Kubernetes?
Request 4: [instance-4ca8e6]  Q: How does load balancing work?
Request 5: [instance-9c254c]  Q: What is Redis used for?
------------------------------------------------------------
Total requests: 5
Instances used: {'instance-1734d4', 'instance-9c254c', 'instance-4ca8e6'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10 (5 user + 5 assistant)
✅ Session history preserved across all instances via Redis!
```

**Kiểm chứng thêm kịch bản tắt 1 instance (`docker stop k5-day14-scaling-agent-1`):**
- Turn 1 (`session_id: e23b5235-4076-47bd-8a85-050e080ccddd`) được phục vụ bởi `instance-4ca8e6`.
- Dừng container `k5-day14-scaling-agent-1`.
- Turn 2 gửi cùng `session_id` được Nginx tự động chuyển sang `instance-9c254c` nhờ cấu hình `proxy_next_upstream error timeout http_503` (trả `200 OK`, không lỗi).
- Gọi `GET /chat/e23b5235-4076-47bd-8a85-050e080ccddd/history` vẫn còn nguyên **đủ 4 messages** (`count: 4`) nhờ lưu trữ trên Redis.

**Giải thích kết quả:** Nginx sử dụng Docker DNS (`resolver 127.0.0.11`, `server agent:8000`) phân tán đều request theo round-robin tới cả 3 replica (`instance-4ca8e6`, `instance-9c254c`, `instance-1734d4`), trong khi cả 3 replica cùng đọc/ghi `session:{id}` trên một Redis dùng chung. Nhờ đó toàn bộ 10 tin nhắn của phiên hội thoại được bảo toàn xuyên suốt các instance khác nhau, và hệ thống vẫn hoạt động liên tục không mất dữ liệu ngay cả khi một instance bị tắt đột ngột. Sau khi kiểm thử đã dọn sạch stack bằng `docker compose -p k5-day14-scaling down -v`.

---

## Part 6: Final Project (`06-lab-complete/`)

Đã hoàn thiện toàn bộ các `TODO` ngay trong thư mục `06-lab-complete/` (`app/config.py`, `app/redis_client.py`, `app/auth.py`, `app/rate_limiter.py`, `app/cost_guard.py`, `app/main.py`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`) và không chỉnh sửa `check_production_ready.py`.

Kết quả chạy bản đầy đủ (`python check_production_ready.py` trong WSL2 Ubuntu, `os.name = posix`, có Docker):

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

Một số chỉ số đo thực tế từ script chấm:
- **Docker image:** build thành công (`30s`), dung lượng `69 MB` (`docker image inspect`, < 500 MB), chạy non-root user `appuser` trên `python:3.11-slim`.
- **Readiness vs Liveness:** `/health` luôn trả `200` kể cả khi Redis mất kết nối, còn `/ready` trả `200` khi Redis sẵn sàng và `503` khi Redis ngắt kết nối.
- **Rate Limiting & Stateless:** trả `429` sau đúng `5` request với `RATE_LIMIT_PER_MINUTE=5` kèm `Retry-After`; sau khi restart agent vẫn tiếp tục bị `429` nhờ lưu sliding window (`ZSET`) trên Redis.
- **Cost Guard:** lưu chi phí ngày/tháng trên Redis (`INCRBYFLOAT` + `EXPIRE`), trả `402` khi vượt ngân sách.
- **Structured Logging:** toàn bộ `17` dòng log của app đều là JSON hợp lệ (`JsonFormatter`).
- **Graceful Shutdown:** `SIGTERM` lúc đang xử lý request vẫn hoàn tất `200` và thoát `exit code 0`; `docker stop` tắt êm trong `0.7s` (`exit code 0`) nhờ `exec uvicorn` làm PID 1.

---

## AI Log

| Thời điểm / Mốc | Hỏi AI điều gì | Nhận được gì | Tự kiểm tra & xác nhận |
| --- | --- | --- | --- |
| CP0 — Setup | Kiểm tra yêu cầu tài khoản cloud, kiểm tra trạng thái WSL2, Python, Docker và setup môi trường làm bài trong WSL2 | Xác định chỉ cần GitHub + Railway/Render (không cần GCP hay LLM API key), phát hiện WSL2 Ubuntu có Python 3.12.3 (`posix`) nhưng thiếu `pip`/`venv` và Docker Desktop chưa bật tích hợp WSL2 cho Ubuntu; tạo venv `~/day14-venv` bằng `uv`. | Tự chạy `docker run --rm hello-world` (thành công), kiểm tra `python --version` (`3.12.3`) và `os.name` (`posix`) trong WSL2 Ubuntu. |
| CP1 — Part 1 | Phân tích anti-pattern giữa `01-localhost-vs-production/develop` và `production`, chạy thử cả hai phiên bản để đối chiếu | Danh sách 8 anti-pattern kèm số dòng đối chiếu trong `develop/app.py` và cách sửa trong `production/app.py` & `config.py`; bảng so sánh chi tiết có giải thích lý do. | Tự chạy cả `develop/app.py` và `production/app.py` trong WSL2, gọi trực tiếp bằng `curl -i` kiểm chứng `200`/`404`/`422`, xác nhận log lộ secret ở bản `develop` và luồng shutdown khi gửi `SIGTERM` ở bản `production`. |
| CP2 — Part 2 | Phân tích Dockerfile single-stage vs multi-stage, xử lý lỗi 429 Docker Hub khi pull image Compose, vẽ sơ đồ stack 4 service | Giải thích 4 câu Ex 2.1, phân tích stage builder/runtime Ex 2.3, chẩn đoán lỗi `429 Too Many Requests` do chưa đăng nhập Docker Hub trên Docker Desktop và vẽ sơ đồ stack `nginx`/`agent`/`redis`/`qdrant`. | Tự bật WSL Integration và đăng nhập Docker Desktop, tự build `my-agent:develop` (`1.67 GB`) và `my-agent:advanced` (`240 MB`, giảm `85.6%`), tự chạy container Ex 2.2 và stack Compose Ex 2.4 (`-p k5-day14-docker`) kiểm chứng `curl -i` qua Nginx đều `200 OK`, sau đó dọn stack sạch sẽ. |
| CP3 — Part 4 | Phân tích cơ chế API Key, JWT, Sliding Window rate limiter và cách thiết kế Cost Guard dùng Redis | Giải thích luồng xác thực trong `develop/app.py`, `production/auth.py`, `rate_limiter.py`, `cost_guard.py`, thiết kế key Redis `budget:{user_id}:{YYYY-MM}` và phân tích lý do cần kết hợp Rate Limit + Cost Guard. | Tự cài `pyjwt` vào venv WSL2, chạy cả bản `develop` và `production`, dùng `curl -i` kiểm chứng trực tiếp mã `401`/`403`/`200`/`429` (đã che JWT token trước khi lưu) và kiểm tra `/me/usage`. |
| CP4 — Part 5 | Phân tích sự khác biệt `/health` vs `/ready`, cơ chế graceful shutdown và xử lý xung đột cổng 8080 khi chạy stack 3 instance | So sánh liveness/readiness, phân tích `lifespan` + `SIGTERM`, xử lý tránh xung đột cổng 8080 (container `sep_adminer` đang dùng) bằng Compose override tạm không sửa file repo. | Tự chạy bản `develop` kiểm chứng 2 request song song đều trả `200` khi gửi `SIGTERM`; tự bật 3 instance (`--scale agent=3`), chạy `test_stateless.py` thấy cả 3 instance cùng phục vụ 10 messages nguyên vẹn trên Redis, và test dừng 1 instance xác nhận failover không mất history, sau đó dọn stack sạch sẽ. |
| CP5 — Part 6 | Thiết kế và hoàn thiện các module TODO trong `06-lab-complete/` theo đúng hợp đồng 12 tiêu chí (Redis ZSET rate limiter, Redis cost guard, constant-time API key auth, JSON logger, lifespan shutdown, multi-stage Dockerfile với `exec uvicorn`, Compose, `railway.toml`, `render.yaml`) | Mã nguồn cho 6 module trong `app/` và 6 file cấu hình container/deploy (`Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`). | Tự kiểm tra trực tiếp bằng `python check_production_ready.py` bản đầy đủ (có Docker) trong WSL2 Ubuntu đạt `PASS 12/12` (`43/43 checks passed`), xác nhận không sửa `check_production_ready.py` và không commit `.env`. |
| CP7 — Part 7 (Bước 1) | Thực hiện load test 4 mức concurrency, thí nghiệm tail latency (`MOCK_SLOW_RATE`), eval v1 vs v2, sửa `KNOWLEDGE_BASE` và viết workflow CI quality gate | Thêm Histogram `agent_question_length_chars` vào `develop/app.py`, thêm 2 entry `jwt` và `hpa/kubernetes` vào `KNOWLEDGE_BASE` (đồng bộ cả `develop` và `production`), tạo `.github/workflows/eval.yml` và hoàn thiện phần đầu `BENCHMARK_REPORT.md`. | Tự chạy toàn bộ 7 bài `load_test.py` và 3 bài `eval/run_eval.py` trên WSL2, xác nhận `eval_v2_fixed.json` đạt `100.0%` (`23/23`, `0` regression, `Quality gate ✅ PASS`), xác nhận `golden_dataset.jsonl` không bị sửa và đối chiếu 100% số liệu trong `BENCHMARK_REPORT.md` với 10 file JSON trong `reports/`. |
| CP6 — Part 3 & Deploy Part 6 | Cài đặt Railway CLI, tạo project `day14-ai-agent`, gắn Cloud Redis, cấu hình biến môi trường, deploy `06-lab-complete/` lên Railway, viết `DEPLOYMENT.md` và phần so sánh `railway.toml`/`render.yaml` + tóm tắt Cloud Run | Deploy thành công `agent` và `Redis` trên Railway với URL `https://agent-production-31921a2c.up.railway.app`, soạn `DEPLOYMENT.md` và hoàn thiện mục Part 3 trong `MISSION_ANSWERS.md` (không ghi secret hay email vào repo). | Tự bấm xác nhận đăng nhập Railway trên trình duyệt, tự chạy đủ 4 lệnh curl tự kiểm CP6 trên URL public xác nhận `200`/`200` (`redis: connected`)/`401`/`200` và kiểm tra bằng `check_production_ready.py --public-url`. |
| CP8 — Part 7 (Bước 2) | Dựng full Observability Stack (`-p k5-day14-observability`), chẩn đoán lỗi `ModuleNotFoundError: uvicorn` trong `production/Dockerfile`, chạy Locust headless `scale_1` & `scale_3`, phân tích Prometheus/Jaeger/JSON log và chạy thí nghiệm phá hệ thống A–E | Tìm ra nguyên nhân thiếu `ENV PYTHONUSERBASE=/home/agent/.local` trong `production/Dockerfile`, sửa và chạy thành công `promtool` (`SUCCESS`), `scale_1_stats.csv`, `scale_3_stats.csv`, trích xuất trace chậm (`1717.2ms`) & trace lỗi (`503`) khớp log JSON, kích hoạt 4/4 alert firing và hoàn thiện `BENCHMARK_REPORT.md`. | Tự đối chiếu 100% số liệu `BENCHMARK_REPORT.md` với `benchmark-results/scale_1_stats.csv`, `scale_3_stats.csv`, truy vấn trực tiếp Prometheus/Jaeger API và tự chụp ảnh từ Grafana/Jaeger/Prometheus đang chạy thực tế. |
