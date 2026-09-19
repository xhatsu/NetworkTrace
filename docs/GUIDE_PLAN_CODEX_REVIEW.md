# Hướng dẫn Review Kế hoạch Xử lý `-anonymous-` cho Codex (GPT-6 ASTRA Medium)

Tài liệu này cung cấp toàn bộ bối cảnh hệ thống, tài liệu kế hoạch, và prompt review chuẩn chuyên gia dành cho model **Codex (GPT-6 ASTRA medium)** để đánh giá tính khả thi, an toàn bảo mật và hiệu năng kiến trúc.

---

## 1. Prompt Chuyên sâu Dành cho Codex (GPT-6 ASTRA Medium)

> **Hướng dẫn sử dụng**: Sao chép toàn bộ khối lệnh dưới đây và dán trực tiếp vào prompt của Codex (GPT-6 ASTRA medium).

```markdown
You are a Principal Software Architect and Lead Security Observability Engineer reviewing an architectural enhancement for "TraceScope", an enterprise OpenTelemetry & behavioral observability platform.

### System Overview & Context
- Codebase: TraceScope (FastAPI backend + React 19 frontend + ClickHouse 24.8 + Elasticsearch 7.17 APM datastore).
- Invariant 1: TPS, Request Volumes, and Latency Percentiles (p50/p95/p99) across all services must remain 100% accurate and mathematically unaltered.
- Invariant 2: User Behavioral Engine tracks identity deviations (Account Takeover, credential abuse, unusual endpoints, off-hours activity, new source IPs).

### The Problem
Currently, unauthenticated requests (missing Authorization header, unauthenticated mobile calls, health checks, web crawlers) are attributed to a pseudo-user named "-anonymous-" (or "unknown").
Because thousands of unrelated clients share this single pseudo-identity:
1. "-anonymous-" fans out to hundreds of source IPs and target services, triggering behavioral detectors (NEW_SOURCE_IP, SOURCE_FANOUT_SURGE, OPERATION_MIX_SHIFT).
2. Its risk score is perpetually calculated at 100 (Critical), ranking #1 in the "Top Risky Accounts" cohort and masking genuine compromised accounts.
3. The User Directory (/users) displays "-anonymous-" as if it were a real employee or service account.

### The Proposed Plan: "Pseudo-Entity Segregation"
1. Ingestion & Storage:
   - Retain all traces and metric buckets with principal_name = "-anonymous-" (zero data loss for service throughput & latency).
   - Add categorization tag: entity_category = "unauthenticated" (vs "human" and "service").
2. Behavioral & Incident Engine:
   - Exclude "-anonymous-" from individual user risk scoring (behavior_score = 0 / neutral).
   - Shift monitoring of unauthenticated traffic to Source IP Centric (anomalies flagged on caller_ip: ip_new_endpoint, unusual_access) and Endpoint Centric (auth_failure_burst on 401/403).
3. Backend APIs (/api/v1/users, /api/v1/users/summary):
   - Default to filtering out "-anonymous-" from user inventory (WHERE principal_name NOT IN ('-anonymous-', 'unknown', '')).
   - Provide an explicit query toggle: `include_anonymous=true`.
   - Overview KPI "Active Users" counts only identified human + service accounts, exposing a dedicated `anonymous_traffic_ratio` metric.
4. Frontend UI:
   - User Directory defaults to 100% clean identity view with a toggle: "[ ] Show Unauthenticated Traffic (-anonymous-)".
   - Special neutral gray badge: `[Public / Unauthenticated Traffic]` when viewed, suppressing misleading user risk metrics.

### Your Review Tasks (Answer in structured detail):
1. **Architectural Correctness & Data Invariants**:
   - Does this plan guarantee zero distortion to service-level TPS, error rates, and latency percentiles?
   - Are there any edge cases where aggregating or filtering "-anonymous-" might drop telemetry from downstream caller graphs?
2. **Security & Threat Model Audit**:
   - If an attacker deliberately strips credentials to hide in "-anonymous-" traffic, how does the proposed IP-centric + 401/403 burst detection prevent blind spots?
   - What additional safeguards should be added to detect anonymous API brute-force or data exfiltration?
3. **Database Performance & Query Optimization (ClickHouse / SQL)**:
   - Will filtering `WHERE principal_name NOT IN ('-anonymous-', 'unknown', '')` cause full table scans on ClickHouse `ReplacingMergeTree` tables, or should we optimize table partitioning / sorting keys?
4. **API & UX Ergonomics**:
   - Critique the proposed API parameter `include_anonymous=true` and UI toggle. Is this intuitive for SOC analysts and SRE operators?
5. **Score & Final Verdict**:
   - Provide an overall readiness score (1–10) and a prioritized list of MUST-FIX, SHOULD-FIX, and OPTIONAL recommendations.
```

---

## 2. Tiêu chí Đánh giá Trọng tâm (Review Rubric)

Khi Codex (GPT-6 ASTRA medium) đánh giá, hãy đối chiếu câu trả lời với 4 tiêu chí cốt lõi sau:

| Tiêu chí | Điểm kiểm tra chính | Mục tiêu kỳ vọng |
| :--- | :--- | :--- |
| **1. Tính toàn vẹn số liệu (Data Integrity)** | Không được làm biến mất request công cộng khỏi TPS hoặc tính toán trễ P95/P99 của các Service. | Service Dashboard vẫn đo đúng 100% tải thực tế của hệ thống. |
| **2. Độ chính xác Rủi ro (Risk Fidelity)** | Không để `-anonymous-` chiếm vị trí số 1 trong danh sách tài khoản rủi ro cao nhất. | Các tài khoản thật bị rò rỉ credential (như `cm2.0`, `sale`, `alice`) phải nổi lên vị trí ưu tiên điều tra. |
| **3. Điểm mù An ninh (Security Blind Spots)** | Kẻ tấn công cố tình không truyền header xác thực để né tránh bộ phát hiện định danh. | Cơ chế phát hiện theo **Source IP Anomaly** và **401 Failure Burst** phải bắt được hành vi này. |
| **4. Tối ưu Truy vấn (Database Indexing)** | Tránh suy giảm hiệu năng khi bảng `traces` và `metric_buckets` có hàng chục triệu bản ghi. | Sử dụng câu lệnh ClickHouse tương thích với `ORDER BY (principal_name, ...)` và không gây lag dashboard. |

---

## 3. Các Câu hỏi Thảo luận Mở (Edge Cases Cần Lưu ý)

1. **Có nên đổi tên `-anonymous-` thành `unknown` hay giữ nguyên?**
   - TraceScope hiện tại hỗ trợ cả `unknown` và `-anonymous-`. Cần đảm bảo hàm lọc bao quát cả 2 giá trị này và chuỗi rỗng `""`.
2. **Xử lý các IP công cộng lớn (NAT Gateway / Proxy F5)**:
   - Nếu hàng ngàn khách vãng lai đi qua cùng 1 IP NAT của F5 Big-IP, liệu việc cảnh báo theo IP có gây nhiễu (noise) không?
   - *Giải pháp*: Kết hợp với thuật toán phát hiện F5 LB Normalization (đã có trong `backend/app/services/normalization.py`) để bóc tách IP máy khách thật qua header `X-Forwarded-For`.
