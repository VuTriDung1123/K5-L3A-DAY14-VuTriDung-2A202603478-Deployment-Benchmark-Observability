# Deployment Information

## Public URL
https://agent-production-31921a2c.up.railway.app

## Platform
**Railway** (deploy trực tiếp thư mục `06-lab-complete/` bằng `Dockerfile` multi-stage + `railway.toml`, kết nối service **Redis** quản lý trên Railway qua biến tham chiếu `REDIS_URL=${{Redis.REDIS_URL}}`).

## Test Commands

Đặt `BASE` là URL public và `AGENT_API_KEY` là key đã cấu hình trên Railway Dashboard (không ghi key thật vào code hay tài liệu):

```bash
export BASE="https://agent-production-31921a2c.up.railway.app"
export AGENT_API_KEY="<YOUR_RAILWAY_AGENT_API_KEY>"
```

### 1. Health Check (Liveness — không cần key)
```bash
curl -sS "$BASE/health"
# Expected (200 OK):
# {"status":"ok","uptime_seconds":...,"version":"1.0.0","environment":"production","timestamp":"..."}
```

### 2. Readiness Check (kiểm tra kết nối Cloud Redis)
```bash
curl -sS "$BASE/ready"
# Expected (200 OK):
# {"ready":true,"redis":"connected","in_flight_requests":1}
```

### 3. Authentication Check (không có API key → 401)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'
# Expected: 401
```

### 4. API Test (có API key hợp lệ → 200)
```bash
curl -sS -X POST "$BASE/ask" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "What is deployment?"}'
# Expected (200 OK): JSON trả lời kèm cost_usd và requests_remaining
```

### Bộ 4 lệnh tự kiểm nhanh (chỉ in mã HTTP, không lộ key)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"                                                                                  # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"                                                                                   # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'               # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}' # 200
```

## Environment Variables Set (trên Railway Dashboard / CLI)

*(Chỉ liệt kê tên biến, giá trị bí mật được lưu trên Railway và không commit vào Git)*

- `PORT` (`8000`)
- `ENVIRONMENT` (`production`)
- `LOG_LEVEL` (`INFO`)
- `REDIS_URL` (`${{Redis.REDIS_URL}}` — trỏ tới service `Redis` trong cùng project Railway)
- `AGENT_API_KEY` *(secret đặt qua `railway variable set --stdin`)*
- `RATE_LIMIT_PER_MINUTE` (`10`)
- `DAILY_BUDGET_USD` (`1.0`)
- `MONTHLY_BUDGET_USD` (`10.0`)

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
