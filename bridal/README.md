# 婚纱礼服试穿与返店清点系统

管理礼服档案、尺码、试穿预约、搭配配件、出店单、返店检查、清洁状态和押金的本地一体化系统。
客户信息与照片均使用演示数据。零第三方依赖，仅需 Python 3.9+（标准库）。

## 单条本地启动命令

```bash
cd bridal
./run.sh                 # 首次自动生成预约/出店/返店/扣款样例，并启动服务
# 打开 http://127.0.0.1:8765
```

或手动：

```bash
python3 seed.py          # 生成完整演示数据（预约、出店、返店、扣款、清洁）
python3 server.py        # 启动服务（默认 8765 端口，BRIDAL_PORT 可改）
```

> 演示数据包含：有效预约、今日签到、迟到取消、临时换款、完整返店扣款闭环、
> 出店超时未返、清洁不合格不可约等典型样例。

## 测试

```bash
python3 test_bridal.py          # 服务层 19 项
python3 test_bridal.py --http   # 额外含 HTTP 接口测试，共 20 项
```

覆盖：**预约竞争、配件完整性、照片配对、押金幂等、客户隔离**，以及清洁门槛、
迟到取消、临时换款、已确认返店仅可追加复核、扣款校验等。

## 六大页面

| 页面 | 功能 |
| --- | --- |
| 礼服档案 | 礼服卡片（**统一 3:4 照片比例**，**尺码与预约状态固定在卡片底部**）、清洁记录、预约/换款/迟到取消入口 |
| 试穿日历 | 月历视图，按状态着色，点击预约可签到 / 临时换款 / 办理出店 / 取消 |
| 搭配清单 | 配件套装**按编号绑定**，显示在店/随单出店状态 |
| 出店核验 | 记录尺寸调整、出店污渍、可标注部位标签的细节照片；超时返店红色标记 |
| 返店检查 | **逐项打勾布局**（正常/缺失/破损/污渍），**异常照片与扣款金额并排**，出/返店照片按部位配对 |
| 押金记录 | 押金、扣款、实退、幂等键、结算号、客户隔离筛选 |

配色：黑白、玫瑰红（`#c8102e`）、浅灰（`#f2f2f2`）。

## 存储

- **SQLite**：`data/bridal.db`（预约、出店单、返店检查、清洁、押金等全部业务数据）。
- **本地照片目录**：`data/photos/`，表单上传的照片以文件落盘，库内只存 URL。
- **结算适配器**：`core.SETTLEMENT` 为**进程内模拟适配器**，按 `idempotency_key` 去重。

## 核心业务规则

1. **预约锁礼服与时段**：同一礼服存在时段重叠的有效预约即拒绝；不重叠的不同时段可各自锁定。
   礼服已出店或清洁未完成时不可预约。
2. **互斥**：同一礼服不能同时存在两张有效出店单；配件套装随单出店后不能绑定第二张出店单。
3. **异常分支**：
   - 迟到取消 → 预约置 `late_cancelled`，礼服释放；
   - 临时换款 → 旧礼服释放、新礼服锁定，原单记录 `swap_from_gown_id`；
   - 配件缺失 / 破损 / 污渍 → 返店逐项标记并可关联扣款；
   - 超时返店 → 出店列表红色标记「超时返店」；
   - 清洁不合格 → 礼服留在清洁流程、**不能再次预约**，自动生成新的待清洁记录。
4. **清洁闸门**：返店确认后礼服进入清洁（`cleaning/pending`），清洁合格恢复 `available`；
   合格前任何预约被拒绝。
5. **押金**：扣款必须**关联异常检查项且上传凭证照片**；确认返店时多退少补、一次性结算，
   结算以押金维度幂等键去重，重复确认不会重复扣款。
6. **返店结果**：确认后不可修改检查项与扣款，**只能追加复核**（复核按时间追加留痕）。
7. **照片配对**：出店/返店照片按相同部位标签（slot，如 `hem`、`zipper`）自动前后配对，
   仅单侧存在的照片以红色虚线边框提示。

## 目录结构

```
bridal/
├── run.sh             # 单条启动命令
├── server.py          # http.server：JSON API + 静态页 + 照片文件
├── core.py            # SQLite schema、业务规则、照片落盘、进程内模拟结算
├── seed.py            # 演示数据生成器（含本地 SVG 照片）
├── test_bridal.py     # 测试套件
├── static/
│   ├── index.html
│   ├── app.js         # 六页面前端（原生 JS）
│   └── style.css
└── data/
    ├── bridal.db      # SQLite（运行后生成）
    └── photos/        # 本地照片（运行后生成）
```

## 主要 API

```
GET  /api/gowns | /api/customers | /api/accessory-sets
GET  /api/appointments?from&to&gown_id&customer_id&status
GET  /api/out-orders?status&customer_id
GET  /api/inspections?customer_id      GET /api/cleaning?gown_id&status
GET  /api/deposits?customer_id

POST /api/appointments
POST /api/appointments/{id}/checkin | /cancel | /swap
POST /api/out-orders
POST /api/out-orders/{id}/return
POST /api/inspections/{id}/items | /deductions | /confirm | /review
POST /api/cleaning/{id}               # {status: passed|failed}
POST /api/gowns | /api/accessory-sets | /api/customers | /api/photos
```

金额一律以「分」整数存储，前端按元展示。
