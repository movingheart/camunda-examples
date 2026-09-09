"""camunda-examples 流程审批示例入口。

用法（在仓库根目录执行）：
    python main.py                              # 读取 config.ini（不存在则全默认）
    python main.py --config my.ini              # 指定配置文件
    python main.py --db mysql+pymysql://user:pwd@localhost:3306/flowdb
    python main.py --port 9000 --reset          # 重置业务种子数据

配置优先级：命令行参数（--db/--host/--port） > 配置文件 > 内置默认值
（默认 SQLite: flowengine-example.db，host 127.0.0.1，端口 8080）。

配置文件 config.ini（同目录，缺省可先复制 config.ini.example）：

    [server]
    host = 127.0.0.1
    port = 8080

    [database]
    ; 二选一：整条 SQLAlchemy URL，或拆字段（程序自动拼 URL）
    url = mysql+pymysql://user:pwd@localhost:3306/flowdb
    driver = mysql+pymysql
    host = localhost
    port = 3306
    user = root
    password = your_password
    name = flowdb

    ; [database] 全部缺省 -> SQLite 文件 flowengine-example.db（零配置）

启动后打开 http://127.0.0.1:8080 ，从右上角用户下拉框切换办理人体验
「发起 -> 待办 -> 审批(通过/驳回/驳回重提) -> 流程全景」的完整闭环。
"""

from __future__ import annotations

import argparse
import configparser
from pathlib import Path

from sqlalchemy.engine import URL  # 仅用于拆字段拼 URL（依赖随引擎安装）

# camunda-python 引擎由 requirements.txt 从 PyPI 安装（正式版 >=0.1.2）
import uvicorn

from camunda.engine.process_engine import ProcessEngine  # noqa: E402
from camunda.parser import parse_bpmn_xml  # noqa: E402
from camunda.persistence.store import Store  # noqa: E402

from api import create_app  # noqa: E402
from biz import Biz  # noqa: E402
from delegates import business_execute  # noqa: E402

# 内置默认值（配置文件缺失 / 未配置对应项时使用）
_DEFAULT_DB = "flowengine-example.db"
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8080
_CONFIG_FILE = Path(__file__).resolve().parent / "config.ini"

# 部署清单：(展示名, definition key, BPMN 文件名)
_FLOWS = [
    ("请假审批流程", "leave", "leave.bpmn"),
    ("员工申请审批流程", "proc_employee_apply", "employee_apply.bpmn"),
    ("报销审批流程", "expense", "expense.bpmn"),
]

_BANNER = """
  camunda-examples 流程审批示例
  ==============================
  演示用户: u001 张三 / u002 李四 / u003 王五 (研发部, manager_role)
           u004 赵六 / u005 孙七 (市场部, boss_role)
  权限规则: submit(所有用户) / manager(u001,u002,u003+manager_role)
           finance,u005 / leader(D001 部门) —— 来自 mst_flw_rle 种子
  Web UI : http://{host}:{port}
"""


def _deploy(engine: ProcessEngine, bpmn_dir: Path) -> None:
    for name, key, filename in _FLOWS:
        text = (bpmn_dir / filename).read_text(encoding="utf-8")
        model = parse_bpmn_xml(text)
        keys = engine.deploy(model, name)
        print(f"  [deploy] {name:<10} key={key:<20} version 就绪 ({keys})")


def _read_config(path: Path) -> configparser.ConfigParser:
    """读取配置文件（不存在/空文件返回空配置，全部走内置默认）。"""
    cfg = configparser.ConfigParser()
    if path.exists():
        cfg.read(path, encoding="utf-8")
    return cfg


def _db_from_cfg(cfg: configparser.ConfigParser, default: str) -> str:
    """[database] -> 连接串。url 整条优先；否则拆字段拼 SQLAlchemy URL；
    全空则返回 default（SQLite 裸路径，Biz/Store 会自动归一化）。"""
    if not cfg.has_section("database"):
        return default
    d = cfg["database"]
    url = str(d.get("url") or "").strip()
    if url:
        return url
    user = str(d.get("user") or "").strip()
    name = str(d.get("name") or "").strip()
    if not (user or name):  # 未配置数据库：走内置默认（SQLite）
        return default
    port_raw = str(d.get("port") or "").strip()
    return URL.create(
        drivername=str(d.get("driver") or "mysql+pymysql").strip() or "mysql+pymysql",
        username=user or None,
        password=str(d.get("password") or "") or None,
        host=str(d.get("host") or "").strip() or None,
        port=int(port_raw) if port_raw.isdigit() else None,
        database=name or None,
    ).render_as_string(hide_password=False)


def _server_from_cfg(
    cfg: configparser.ConfigParser, host: str, port: int
) -> tuple[str, int]:
    """[server] -> 监听地址与端口（未配置则返回传入的默认值）。"""
    if cfg.has_section("server"):
        s = cfg["server"]
        host = str(s.get("host") or "").strip() or host
        port_raw = str(s.get("port") or "").strip()
        if port_raw.isdigit():
            port = int(port_raw)
    return host, port


def main() -> None:
    parser = argparse.ArgumentParser(description="camunda-examples 流程审批示例")
    parser.add_argument(
        "--config", default=None,
        help=f"配置文件路径（默认 {_CONFIG_FILE.name}，与 main.py 同目录；"
             "不存在时全部使用内置默认）",
    )
    parser.add_argument(
        "--db", default=None,
        help="数据库连接串，覆盖配置文件 [database]：SQLite 文件路径或 MySQL URL，"
             "如 mysql+pymysql://user:pass@localhost:3306/flowdb",
    )
    parser.add_argument("--reset", action="store_true", help="重建业务种子数据")
    parser.add_argument(
        "--host", default=None, help="Web 监听地址，覆盖配置文件 [server]"
    )
    parser.add_argument(
        "--port", type=int, default=None, help="Web 端口，覆盖配置文件 [server]"
    )
    args = parser.parse_args()

    # 合并优先级：命令行 > 配置文件 > 内置默认
    config_path = Path(args.config) if args.config else _CONFIG_FILE
    cfg = _read_config(config_path)
    db = _db_from_cfg(cfg, _DEFAULT_DB)
    host, port = _server_from_cfg(cfg, _DEFAULT_HOST, _DEFAULT_PORT)
    if args.db is not None:
        db = args.db
    if args.host is not None:
        host = args.host
    if args.port is not None:
        port = args.port
    if config_path.exists():
        print(f"  [config] 读取配置文件: {config_path}")
    else:
        print(f"  [config] 未找到 {config_path.name}，使用内置默认（SQLite）")

    bpmn_dir = Path(__file__).resolve().parent / "bpmn"

    biz = Biz(db, force_reset=args.reset)
    engine = ProcessEngine(store=Store(db))

    _deploy(engine, bpmn_dir)
    # 注册 serviceTask 委托：BPMN 中 camunda:class 收敛成短名 "BusinessExecuteDelegate"
    engine.register_delegate("BusinessExecuteDelegate", business_execute)

    app = create_app(engine, biz)
    print(_BANNER.format(host=host, port=port))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
