# camunda-examples

围绕 [camunda-python](https://github.com/movingheart/camunda-python) 引擎的可运行
示例集合：一个本地 Web 应用，演示请假 / 员工申请 / 报销 三条真实审批流程从前端
发起到后端流转的完整闭环。

适合用来快速验证引擎能力、看 BPMN 文件怎么写、或者作为自己业务系统的起点。

## 特性

- **三条开箱即用的审批流程**：请假（leave）、员工申请（employee_apply）、报销
  （expense），含排他网关 / 多角色审批 / serviceTask / 驳回重提。
- **任务归属写在 BPMN 节点上**：userTask 直接声明 `camunda:assignee` /
  `candidateUsers` / `candidateGroups`（支持 `${var}` 表达式），引擎解析节点
  变量并在任务创建时求值，应用层不再维护「流程-节点-权限」映射表。
- **可交互的 Web 前端**：纯 HTML / JS，无需任何构建步骤；流程全景含 SVG 流程图
  （绿=已过 / 蓝=进行中 / 灰=未达）、办理轨迹时间线、操作日志。
- **真实持久化**：业务流程用 SQLite / PostgreSQL / MySQL（与引擎共用 ACT_* 表）；
  业务侧用一份独立的业务表（`mst_flw_rle` 权限规则 + `mst_flw_fsvlog` 操作日志）。
- **零外部依赖**：除 camunda-python 引擎与 fastapi / uvicorn 外，不引入其他运行时。

## 演示流程

```
发起人填写表单  ──>  引擎部署 BPMN 启动流程  ──>  审批人待办
              │                              │
              └──>  我发起的  ──> 流程全景（变量 / 办理轨迹 / 操作日志 / SVG）
```

## 快速开始

```bash
git clone https://github.com/movingheart/camunda-examples.git
cd camunda-examples
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt                     # 引擎 camunda-python[api] 从 PyPI 安装
python main.py
```

打开浏览器访问 <http://127.0.0.1:8080>，右上角用户下拉框切换办理人。

首次启动会自动完成：
1. 业务表建表 + 种子数据（权限规则 / 用户 / 操作日志）
2. 部署三条流程（`leave` / `proc_employee_apply` / `expense`）
3. 注册 serviceTask 委托
4. 启动 Web 服务（默认端口 8080）

## 演示场景

| 场景 | 发起人 | 审批人 |
|---|---|---|
| 请假 | `u001` | 部门经理 `u002` / `u003`（审批节点不允许发起人本人办理） |
| 员工申请（请假 / 硬件申领） | `u001` | 直属上级 → 部门经理 |
| 报销 | `u001` | 部门经理 → 财务 `u005` |

操作路径：

- **发起**：进入对应场景 → 填写表单 → 提交。
- **审批**：右上角切换到审批人 → 「我的待办」找到卡片 → 通过 / 驳回。
- **驳回重提**：发起人在「我的待办」看到修改重提卡片 → 改表单 → 重新提交。
- **流程全景**：进入「我发起的」 → 选流程 → 看 SVG 流程图、变量、办理轨迹时间线、操作日志。

## 数据库

默认 SQLite（`flowengine-example.db`，零配置）。要切到 MySQL / PostgreSQL：

```bash
cp config.ini.example config.ini
# 编辑 config.ini 的 [database] 节
python main.py
```

`config.ini` 含口令，已加入 `.gitignore` 不入库。优先级：

> **命令行（`--db` / `--host` / `--port`）> 配置文件（`config.ini`）> 内置默认**

```bash
python main.py --port 9000                          # 换端口
python main.py --reset                              # 重建业务种子数据
python main.py --db mysql+pymysql://user:pwd@host/db # 直连覆盖
```

## API

后端为 FastAPI，业务接口契约：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/users` | 演示用户列表 |
| POST | `/api/start` | 发起请假 |
| POST | `/api/start/employee` | 发起员工申请 |
| POST | `/api/start/expense` | 发起报销 |
| GET | `/api/todos?userId=&mstrleId=` | 我的待办 |
| POST | `/api/approve` | 办理（通过 / 驳回） |
| GET | `/api/mine?userId=` | 我发起的 |
| GET | `/api/process/detail?businessKey=` | 流程全景 |
| GET | `/api/logs` | 全局操作日志 |

所有接口统一 `{success, data | message}` 响应契约（HTTP 200 + 业务级 success 标志位）。

## 项目结构

```
camunda-examples/
├── main.py          # 入口：配置 -> 业务表初始化 -> 引擎(Store) -> deploy -> delegate -> uvicorn
├── api.py           # FastAPI 业务路由
├── biz.py           # 业务表门面：建表 / 种子 / 权限规则展开 / 操作日志
├── graph.py         # BPMN DI -> 流程图数据（SVG 渲染所需）
├── delegates.py     # serviceTask 委托
├── config.ini.example   # 配置文件模板（复制为 config.ini 使用）
├── requirements.txt # 运行依赖（camunda-python[api] 来自 PyPI，>=0.1.2）
├── bpmn/            # 三条流程的 BPMN 定义文件
└── webapp/          # 静态前端（index.html / app.js / style.css）
```

## 添加自己的流程

1. 把 `.bpmn` 文件放到 `bpmn/` 目录
2. 在 `main.py` 的 `_FLOWS` 列表里加一行 `(展示名, definition_key, "文件名.bpmn")`
3. userTask 节点直接写 `camunda:assignee` / `candidateUsers` / `candidateGroups`
   （可用 `${var}` 引用流程变量，如 `${manager_users}`），引擎会解析节点变量
4. 重启 `python main.py`，引擎会自动以新版本 +1 部署

## 引擎升级

`requirements.txt` 直接从 PyPI 安装正式包 `camunda-python[api]`：

```
camunda-python[api]>=0.1.2
```

- 0.1.2 起引擎会在 userTask 创建时解析节点上的归属变量并对 `${...}` 求值
  （`camunda:assignee` / `candidateUsers` / `candidateGroups`）
- 要锁定行为，可收紧到 `>=0.1.2,<0.2`；升级后执行 `pip install -U -r requirements.txt`
- 引擎变更记录见 https://github.com/movingheart/camunda-python/blob/main/CHANGELOG.md

## 已知限制

- 角色 -> 用户/候选组的展开在应用层完成（`biz.py#users_for_role` 读
  `mst_flw_rle`），展开结果以 `{role}_users` / `{role}_groups` 注入流程变量，
  再由引擎对 BPMN 节点里的 `${manager_users}` 等表达式求值。改权限规则直接
  编辑 `mst_flw_rle` 表即可生效（支持日期列有效期）。
- 审批类节点「发起人本人不可办理」是示例的业务策略（`api.py#_can_do`），
  属应用层判定而非引擎语义；引擎只负责解析节点变量给出候选集。
- 流程实例当前归属与变量走引擎内存视图（`mst_flw_fsvlog` 操作日志持久化）；
  ACT_* 历史表仍会落库（Store 持久化），但本示例读取走内存视角。

## 许可

Apache-2.0。