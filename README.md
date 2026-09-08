# flowengine 流程示例（camunda-python 版）

请假 / 员工申请 / 报销 三条审批流程的 Web 演示应用 —— Java 版示例
（`E:\workspace\flowengine\flowengine-example`，基于 flowengine + Camunda 7.18）
的 Python 移植：流程定义（BPMN）与前端（webapp）**原文件复用**，后端用独立的
camunda-python 引擎 + FastAPI 重写（见文末「camunda-python 引擎与 wheel」），
业务表（权限规则 / 操作日志）与 Java 版同构。

```
发起流程 ──> 我的待办(userId + 角色 双通道) ──> 审批 通过/驳回/驳回重提
        └──> 我发起的 ──> 流程全景（变量 / 办理轨迹 / 操作日志 / SVG 流程图）
```

## 环境要求

| 项目 | 要求 | 说明 |
| --- | --- | --- |
| 操作系统 | Windows / macOS / Linux | 以下命令 Windows 用 cmd/PowerShell，其他用 bash |
| Python | **>= 3.12** | 引擎 `camunda-python` 要求（`requires-python = ">=3.12"`），安装前用 `python --version` 确认 |
| pip | 随 Python 自带 | 版本过低可 `python -m pip install --upgrade pip` |
| 数据库 | 默认 SQLite（零配置） | 可选 MySQL 5.7+ / 8.x（另装 pymysql 驱动） |
| 浏览器 | Chrome / Edge / Firefox 等 | 前端为普通网页，无其他要求 |

> 前端 `webapp/`（index.html / app.js / style.css）是纯静态页面（Java 版原样复用），
> **不需要 Node.js / npm / 任何构建步骤**；后端 Web 依赖（FastAPI / uvicorn）随引擎的 `[api]` extras 一并安装。

## 安装步骤

### 1) 获取本仓库（引擎以 wheel 随附，无需另备源码）

运行依赖的 camunda-python 引擎以 **wheel 随附在本仓库**（`vendor/camunda-python/`，
构建自独立的引擎源码仓库），`requirements.txt` 用 `--find-links` 指向它即可正常
`pip install`，因此**默认不需要**再准备 `../camunda-python` 源码目录。

仅在需要**修改引擎源码并立即生效**（引擎二次开发）时，才需把引擎仓库平级摆放：

```
E:\workspace\                # 也可以是任意父目录
├── camunda-python\          # 引擎源码仓库（可选，仅引擎开发时需要）
└── flowengine-example\      # 本示例仓库（当前目录）
```

引擎源码改动后：要么按文末「camunda-python 引擎与 wheel」重建 wheel 替换 vendor 文件，
要么临时 `pip install -e "<引擎绝对路径>[api]"` 覆盖安装做联调。

### 2) 创建并激活虚拟环境（推荐，隔离依赖）

Windows（cmd / PowerShell）：

```bat
cd /d E:\workspace\flowengine-example
python -m venv .venv
.venv\Scripts\activate
```

macOS / Linux：

```bash
cd /path/to/flowengine-example
python3 -m venv .venv
source .venv/bin/activate
```

激活成功后命令行前缀会出现 `(.venv)`，后续命令均在该环境内执行。

> 不建虚拟环境也可直接安装到用户/系统 Python，但推荐 venv 避免污染全局环境。

### 3) 安装依赖

`requirements.txt` 通过 `--find-links vendor/camunda-python` 从随附 wheel 安装引擎
（含 `[api]` extras：fastapi/uvicorn 等），其余常规依赖走你已配置的 pip 索引
（公司镜像 / 默认 PyPI）：

```bash
pip install -r requirements.txt
```

> 引擎升级时需同步替换 `vendor/camunda-python/` 中的 wheel（见文末
> 「camunda-python 引擎与 wheel」）；若引擎已发布到（内网）PyPI，可删掉
> `--find-links` 行改为直接 `camunda-python[api]==0.1.0`。

可选：连 MySQL 需另装驱动：

```bash
pip install pymysql
```

### 4) 校验安装

```bash
python -c "import camunda, fastapi; print('dependencies ok')"
```

无报错即安装成功。可用 `pip show camunda-python` 确认引擎来自随附 wheel
（Location 指向 venv 的 `site-packages`，而非某源码目录）。

### 5) 启动

```bash
python main.py
```

首次启动会自动完成：业务表建表 + 种子数据（默认 SQLite 文件 `flowengine-example.db`，
生成在当前目录）→ 部署三条流程（`leave` / `proc_employee_apply` / `expense`，
ACT_RE_PROCDEF 版本 +1，与 Camunda 一致）→ 注册 serviceTask 委托
`BusinessExecuteDelegate` → 启动 Web 服务。看到 banner 与 `Uvicorn running on
http://127.0.0.1:8080` 即就绪。

数据库/监听地址支持**配置文件**（默认读取 main.py 同目录的 `config.ini`，模板见
`config.ini.example`）与命令行两种方式，优先级为
**命令行（--db/--host/--port）> 配置文件 > 内置默认（SQLite + 8080）**，详见第 7 步。

常用启动参数：

```bash
python main.py                          # 默认 SQLite，端口 8080
python main.py --config my.ini          # 使用指定配置文件
python main.py --port 9000              # 换端口（命令行覆盖配置文件）
python main.py --reset                  # 重建业务种子数据（DELETE + INSERT）
python main.py --help                   # 全部参数
```

### 7)（可选）连 MySQL：写入配置文件

推荐把连接信息写进 `config.ini`（含口令，不入库；先复制模板）：

```bash
# Windows
copy config.ini.example config.ini
# macOS / Linux
cp config.ini.example config.ini
```

编辑 `config.ini` 的 `[database]` 节，两种写法任选其一（都不配则回退 SQLite）：

```ini
[database]
; 写法一：整条 SQLAlchemy URL（密码含 @ : / 等特殊字符时需自行 URL 编码）
url = mysql+pymysql://root:wst5878067@localhost:3306/flowdb

; 写法二：拆字段（推荐，程序自动拼 URL，密码无需手工编码）
driver = mysql+pymysql
host = localhost
port = 3306
user = root
password = wst5878067
name = flowdb
```

监听地址/端口同理写在 `[server]` 节（`host` / `port`）。保存后直接启动：

```bash
python main.py                          # 引擎 ACT_* 表与业务表共库（MySQL）
python main.py --reset                  # 重建业务种子数据
```

不想建配置文件时，仍可临时用 `--db` 直传（等价的命令行覆盖）：

```bash
python main.py --db mysql+pymysql://root:wst5878067@localhost:3306/flowdb
```

> `--reset` 重建业务种子数据（对齐 Java `init_example_data.sql` 的 DELETE+INSERT）。
> 每次启动都会重新 deploy 三条流程（ACT_RE_PROCDEF 版本 +1，与 Camunda 一致）。

## 演示路径

右上角用户下拉框切换办理人：

| 场景 | 发起人 | 审批人 | 流程 |
| --- | --- | --- | --- |
| 请假 | u001 | 部门经理 u002/u003（审批节点不允许发起人本人办理） | `leave` |
| 员工申请（请假/硬件申领） | u001 | 直属上级(u001,u002,u003) → 部门经理 u002/u003 | `proc_employee_apply` |
| 报销 | u001 | 部门经理 u002/u003 → 财务 u005 | `expense` |

- 待办卡片：通过 / 驳回；驳回后「申请人」在待办看到修改重提卡片，可改表单重新提交
- 「查看流程」进入流程全景：SVG 流程图（绿=已过、蓝=进行中、灰=未达）、办理轨迹时间线、
  操作日志、流程变量
- 员工申请 flow 内嵌 serviceTask「执行业务」，控制台打印（对齐 Java `BusinessExecuteDelegate`）

## 与 Java 版的对应关系

| Java 版 | Python 版 |
| --- | --- |
| `Main.java`（Jetty + init） | `main.py`（引擎初始化 + deploy + uvicorn） |
| `web/ApiServlet.java`（/api/* 业务接口） | `api.py`（FastAPI 同路径同契约） |
| `delegate/BusinessExecuteDelegate.java` | `delegates.py` + `register_delegate("BusinessExecuteDelegate", …)` |
| 权限规则插件读 `mst_flw_rle` → 流程变量 `${manager_users}` | `biz.py#users_for_role`（显式规则展开，任务归属按 BPMN 表达式意图静态映射） |
| 框架写 `mst_flw_fsvlog`（opr_ifo Base64） | `biz.py#write_log / fetch_logs`（同表同列） |
| `ProcessGraphUtil` 流程图数据 | `graph.py`（BPMN DI bounds/waypoints + 活动痕迹状态） |
| `resources/bpmn/*.bpmn` | `bpmn/*.bpmn`（原文件，未改动） |
| `resources/webapp/*` | `webapp/*`（原文件，仅顶部副标题文案） |
| `myapp.conf` | `config.ini` + `main.py --config`（同目录 config.ini 默认读取；`--db` 等价于命令行覆盖） |

### 任务归属如何工作

camunda-python 不解析 userTask 的 `camunda:assignee/candidateUsers` 表达式属性
（M1 简化），因此 Java 里「由引擎求值表达式 + 框架插件写变量」的权限机制在本版
落到应用层 `api.py#_can_do`：按「流程 key + 任务节点 id」判定归属 ——
发起/提交/修改重提类节点归发起人本人（= `${startBy}`），审批类节点按规则变量名
（`manager` / `leader` / `finance`）查 `mst_flw_rle` 展开用户并集；审批类任务始终
不允许发起人自己办理（对齐 Java `customCheckUserRule`）。规则数据在 `biz.py` 种子里，
可在数据库直接改 `mst_flw_rle` 增删权限，重启或下次查询即生效（日期列支持有效期）。

## API

保持 Java `ApiServlet` 的 `{success, data|message}` 契约：

| 方法与路径 | 说明 |
| --- | --- |
| `GET /api/users` | 演示用户列表 |
| `POST /api/start` | 发起请假：`{userId, reason, days}` → `{businessKey}` |
| `POST /api/start/employee` | 发起员工申请：`{userId, applyType, reason, detail, needManager}` |
| `POST /api/start/expense` | 发起报销：`{userId, amount, reason, detail}` |
| `GET /api/todos?userId=&mstrleId=` | 我的待办（user 展开 + 角色候选组双通道） |
| `POST /api/approve` | 办理：`{userId, mstrleId, processDefinitionKey, businessKey, taskName, approved, comment, variables?}` |
| `GET /api/mine?userId=` | 我发起的（进行中/已结束） |
| `GET /api/process/detail?businessKey=` | 流程全景：variables/currentTasks/activities/logs/graph |
| `GET /api/logs` | 全局操作日志（mst_flw_fsvlog，倒序 100 条） |

## 项目结构

```
flowengine-example/
├── main.py          # 入口：配置合并(config.ini+命令行) -> 业务表初始化 -> 引擎(Store) -> deploy -> delegate -> uvicorn
├── api.py           # FastAPI 业务路由（对齐 ApiServlet）
├── biz.py           # 业务表门面：建表/种子/权限规则展开/操作日志（对齐 mst_* 表）
├── graph.py         # BPMN DI -> 流程图数据（对齐 ProcessGraphUtil 输出）
├── delegates.py     # serviceTask 委托（BusinessExecuteDelegate）
├── config.ini.example # 配置文件模板（[server]/[database]；复制为 config.ini 使用）
├── config.ini       # 本地运行配置（含口令，.gitignore 已忽略，不提交）
├── vendor/camunda-python/ # camunda-python 引擎 wheel（--find-links 安装源，引擎升级时替换）
├── requirements.txt # 运行依赖（--find-links vendor 安装 camunda-python[api] 等）
├── .gitignore
├── bpmn/            # leave / employee_apply / expense（Java 版原文件）
└── webapp/          # index.html / app.js / style.css（Java 版原文件）
```

## 已知差异（与 Java 版）

1. 权限规则与操作日志由应用层实现（插件/存储过程 -> 显式函数），不依赖
   flowengine 框架与 Camunda 部署。
2. 「我发起的 / 流程全景」基于引擎内存态实例（重启后仅运行中的流程可见；
   操作日志持久化于 `mst_flw_fsvlog`，随时可查）。
3. 流程实例无 assignee/candidate 属性（引擎 M1 简化），任务归属见上表，
   不影响页面演示闭环。
4. 数据库 `ACT_*` 历史表仍会落库（Store 持久化），但本示例的读取走引擎内存视图。

## camunda-python 引擎与 wheel

本仓库是**独立项目**，只含示例代码与资源，不打包引擎。运行依赖的 `camunda`
包以 **wheel 随附**（`vendor/camunda-python/camunda_python-<版本>-py3-none-any.whl`），
由独立的 camunda-python 引擎源码仓库构建而来（上游 `github.com/movingheart/camunda-python`，
公司网络不可达 GitHub，故不采用 git+ / 公共 PyPI，改为随附 wheel + `--find-links` 安装）。

**引擎升级 / 重建 wheel**（在引擎源码目录执行，先改引擎 `pyproject.toml` 的
`[project] version` 再构建）：

```bash
cd <camunda-python 引擎目录>
python -m pip wheel . --no-deps -w dist   # 产出 dist/camunda_python-<版本>-py3-none-any.whl
copy /y dist\camunda_python-*.whl <本仓库>\vendor\camunda-python\   # Windows
# cp dist/camunda_python-*.whl <本仓库>/vendor/camunda-python/      # macOS / Linux
```

替换后同步更新本仓库 `requirements.txt` 中的版本号即可。

**发布到（内网）PyPI**（可选，网络与权限允许时做一次，之后全公司按常规索引安装）：

```bash
pip install twine
twine upload --repository-url <内网源地址> dist/camunda_python-*.whl
```

发布后本仓库 `requirements.txt` 可去掉 `--find-links` 行，改为一行
`camunda-python[api]==0.1.0`，安装即走已配置的索引。
