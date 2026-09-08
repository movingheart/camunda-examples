"""业务库存取层：对齐 Java 示例的业务表语义。

Java 版依赖 flowengine 框架的「权限规则插件」读 mst_flw_rle 并把结果展开成
流程变量（${manager_users} / ${manager_groups}），日志由框架写入
mst_flw_fsvlog。本模块用纯 SQLAlchemy 在同一数据库里复刻这两张表 +
用户/部门/角色/用户组主数据，并直接提供「规则展开」与「日志读写」两个能力
（插件语义 → 显式函数，表结构与列名与 Java 版完全一致）。

依赖说明：
- 引擎的 ACT_* 表（由 camunda.persistence.store.Store 自动建表）与这里的
  业务表可共库；默认 SQLite（一条命令可跑），也支持 MySQL（mysql+pymysql://…）。
"""

from __future__ import annotations

import base64
import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    func,
    select,
    text,
)

# ---------------------------------------------------------------------------
# 表结构（与 Java 版 init_biz_tables.sql / init_example_data.sql 对齐）
# ---------------------------------------------------------------------------
_meta = MetaData()

mst_dpt = Table(
    "mst_dpt",
    _meta,
    Column("dpt_kid", String(64), primary_key=True),
)
mst_usr_ifo = Table(
    "mst_usr_ifo",
    _meta,
    Column("usr_kid", String(64), primary_key=True),
    Column("dpt_kid", String(64)),
    Column("bgn_dte", String(16), default=""),
    Column("end_dte", String(16), default=""),
    Column("usr_flg", Integer, default=0),
)
mst_rle = Table(
    "mst_rle",
    _meta,
    Column("rle_kid", String(64), primary_key=True),
)
a_myinfo_main = Table(
    "a_myinfo_main",
    _meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("sys", String(16)),
    Column("tbl", String(64)),
    Column("key_jsons", Text),  # {"id":"G001"}
    Column("val_jsons", Text),  # {"uid":["u001","u002"]}
)
mst_flw_rle = Table(
    "mst_flw_rle",
    _meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("rle_var", String(64)),
    Column("rle_typ", String(32)),  # user / user_group / user_dpt / group
    Column("rle_tgt", String(128)),
    Column("bgn_dte", String(16)),
    Column("end_dte", String(16)),
    Column("tsm", String(32)),
)
mst_flw_fsvlog = Table(
    "mst_flw_fsvlog",
    _meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("dte", String(16)),       # yyyy-MM-dd
    Column("flw_kid", String(64)),   # 流程定义 key
    Column("bus_kid", String(128)),  # 业务号
    Column("opr", String(64)),       # 操作人
    Column("tsk_nme", String(128)),
    Column("opr_typ", String(32)),   # Start / Submit / Approve
    Column("opr_ret", String(16)),   # true / false
    Column("opr_ifo", Text),         # Base64(UTF-8) 说明文字（框架旧格式）
    Column("tsm", String(32)),       # yyyy-MM-dd HH:mm:ss
)

# ---------------------------------------------------------------------------
# 种子数据（对齐 Java init_example_data.sql，规则 rle_var ↔ BPMN 变量）
# ---------------------------------------------------------------------------
SEED = {
    "dpt": [("D001",), ("D002",)],
    "usr": [
        ("u001", "D001", "2020-01-01", "", 0),
        ("u002", "D001", "2020-01-01", "", 0),
        ("u003", "D001", "2020-01-01", "", 0),
        ("u004", "D002", "2020-01-01", "", 0),
        ("u005", "D002", "2020-01-01", "", 0),
    ],
    "rle": [("manager_role",), ("boss_role",), ("employee_role",)],
    "group": [
        ("FSV", "v_mst_flw_usergroup", {"id": "G001"}, {"uid": ["u001", "u002"]}),
        ("FSV", "v_mst_flw_usergroup", {"id": "G002"}, {"uid": ["u004", "u005"]}),
    ],
    "flw_rle": [
        # submit: 所有用户可发起
        *[("submit", "user", u, "2020-01-01", "", "2026-08-28 00:00:00") for u in
          ("u001", "u002", "u003", "u004", "u005")],
        # manager: G001 组(u001,u002) + u003 + D001 部门(u001,u002,u003) + manager_role 角色
        ("manager", "user_group", "G001", "2020-01-01", "", "2026-08-28 00:00:00"),
        ("manager", "user", "u003", "2020-01-01", "", "2026-08-28 00:00:00"),
        ("manager", "user_dpt", "D001", "2020-01-01", "", "2026-08-28 00:00:00"),
        ("manager", "group", "manager_role", "2020-01-01", "", "2026-08-28 00:00:00"),
        # finance / boss: u005
        ("finance", "user", "u005", "2020-01-01", "", "2026-08-28 00:00:00"),
        ("boss", "user", "u005", "2020-01-01", "", "2026-08-28 00:00:00"),
        # leader: D001 研发部全体（员工申请的直属上级审批）
        ("leader", "user_dpt", "D001", "2020-01-01", "", "2026-08-28 00:00:00"),
    ],
}

_TODAY = date.today()


def _in_effect(bgn: Optional[str], end: Optional[str], today: date = _TODAY) -> bool:
    """规则/用户有效期判断（bgn_dte/end_dte 空 = 永久；对齐存储过程语义）。"""
    bgn, end = (bgn or "").strip(), (end or "").strip()
    if bgn and bgn > today.isoformat():
        return False
    if end and end < today.isoformat():
        return False
    return True


def _normalize_url(url: str) -> str:
    """裸文件路径 -> sqlite:/// 绝对路径（对齐 Store 的归一化规则）。"""
    u = url.strip()
    if "://" in u:
        return u
    from pathlib import Path

    return "sqlite:///" + str(Path(u).resolve())


class Biz:
    """业务表门面：建表 + 种子 + 权限规则展开 + 操作日志。"""

    def __init__(self, url: str, force_reset: bool = False) -> None:
        self.url = _normalize_url(url)
        self.engine = create_engine(self.url, future=True)
        _meta.create_all(self.engine)
        self._seed(force=force_reset)

    # ---------------- 初始化 / 种子 ----------------
    def _seed(self, force: bool = False) -> None:
        with self.engine.begin() as conn:
            filled = conn.execute(select(func.count()).select_from(mst_flw_rle)).scalar()
        if filled and not force:
            return  # 已初始化：幂等（--reset 可强制重建种子）
        if not filled:
            with self.engine.begin() as conn:
                for t, rows in (
                    (mst_dpt, SEED["dpt"]),
                    (mst_usr_ifo, SEED["usr"]),
                    (mst_rle, SEED["rle"]),
                ):
                    conn.execute(t.delete())
                    for row in rows:
                        conn.execute(t.insert().values(row))
                conn.execute(a_myinfo_main.delete())
                for sys_, tbl, key_j, val_j in SEED["group"]:
                    conn.execute(
                        a_myinfo_main.insert().values(
                            sys=sys_,
                            tbl=tbl,
                            key_jsons=json.dumps(key_j, ensure_ascii=False),
                            val_jsons=json.dumps(val_j, ensure_ascii=False),
                        )
                    )
                conn.execute(mst_flw_rle.delete())
                for row in SEED["flw_rle"]:
                    conn.execute(
                        mst_flw_rle.insert().values(
                            rle_var=row[0], rle_typ=row[1], rle_tgt=row[2],
                            bgn_dte=row[3], end_dte=row[4], tsm=row[5],
                        )
                    )

    # ---------------- 权限规则展开（对齐框架插件读 mst_flw_rle） ----------------
    def users_for_role(self, rule_var: str) -> Tuple[List[str], List[str]]:
        """按规则变量名展开可办理人。

        返回 (可办用户列表, 候选角色列表)：
        - rle_typ=user       -> 指定用户（rle_tgt）
        - rle_typ=user_group -> 用户组内用户（a_myinfo_main JSON）
        - rle_typ=user_dpt   -> 部门内用户（mst_usr_ifo）
        - rle_typ=group      -> 角色候选组（mst_rle，进 candidateGroups 通道）
        同 rle_var 多行 = 并集；bgn/end 日期过滤（空=永久）。
        """
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(mst_flw_rle).where(mst_flw_rle.c.rle_var == rule_var)
            ).mappings().all()
        users: List[str] = []
        roles: List[str] = []
        for r in rows:
            if not _in_effect(r["bgn_dte"], r["end_dte"]):
                continue
            typ, tgt = r["rle_typ"], r["rle_tgt"]
            if typ == "user":
                users.append(tgt)
            elif typ == "user_group":
                users.extend(self._group_users(tgt))
            elif typ == "user_dpt":
                users.extend(self._dpt_users(tgt))
            elif typ == "group":
                roles.append(tgt)
        # 去重保序
        seen: set = set()
        uniq_users: List[str] = []
        for u in users:
            if u not in seen:
                seen.add(u)
                uniq_users.append(u)
        return uniq_users, list(dict.fromkeys(roles))

    def _group_users(self, group_id: str) -> List[str]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(a_myinfo_main)).mappings().all()
        out: List[str] = []
        for r in rows:
            try:
                key = json.loads(r["key_jsons"] or "{}")
            except json.JSONDecodeError:
                continue
            if key.get("id") != group_id:
                continue
            val = json.loads(r["val_jsons"] or "{}")
            out.extend(val.get("uid") or [])
        return out

    def _dpt_users(self, dpt_id: str) -> List[str]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(mst_usr_ifo).where(mst_usr_ifo.c.dpt_kid == dpt_id)
            ).mappings().all()
        return [
            r["usr_kid"] for r in rows
            if _in_effect(r["bgn_dte"], r["end_dte"]) and r["usr_flg"] == 0
        ]

    # ---------------- 操作日志（对齐 mst_flw_fsvlog） ----------------
    @staticmethod
    def _enc(msg: str) -> str:
        """opr_ifo 落库格式：Base64(UTF-8)（对齐框架写日志的旧格式）。"""
        return base64.b64encode((msg or "").encode("utf-8")).decode("ascii")

    @staticmethod
    def _dec(b64: str) -> str:
        """读取时解码回明文中文（对齐 Java decodeOprIfo：解不出就原样返回）。"""
        if not b64:
            return ""
        try:
            raw = base64.b64decode(b64.encode("ascii"))
            return raw.decode("utf-8")
        except Exception:
            return b64

    def write_log(
        self,
        *,
        flw_kid: str,
        bus_kid: str,
        opr: str,
        tsk_nme: str,
        opr_typ: str,
        opr_ret: str,
        opr_ifo: str,
    ) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.engine.begin() as conn:
            conn.execute(
                mst_flw_fsvlog.insert().values(
                    dte=now[:10], flw_kid=flw_kid, bus_kid=bus_kid, opr=opr,
                    tsk_nme=tsk_nme, opr_typ=opr_typ, opr_ret=opr_ret,
                    opr_ifo=self._enc(opr_ifo), tsm=now,
                )
            )

    def fetch_logs(
        self,
        bus_kid: Optional[str] = None,
        limit: Optional[int] = 100,
        order: str = "desc",
    ) -> List[Dict[str, Any]]:
        """按时间取日志（opr_ifo 已解码为明文）。order: desc(全局日志) / asc(单流程)。"""
        with self.engine.connect() as conn:
            stmt = select(
                mst_flw_fsvlog.c.dte, mst_flw_fsvlog.c.flw_kid, mst_flw_fsvlog.c.bus_kid,
                mst_flw_fsvlog.c.opr, mst_flw_fsvlog.c.tsk_nme, mst_flw_fsvlog.c.opr_typ,
                mst_flw_fsvlog.c.opr_ret, mst_flw_fsvlog.c.opr_ifo, mst_flw_fsvlog.c.tsm,
            )
            if bus_kid:
                stmt = stmt.where(mst_flw_fsvlog.c.bus_kid == bus_kid)
            if order == "asc":
                stmt = stmt.order_by(mst_flw_fsvlog.c.tsm.asc(), mst_flw_fsvlog.c.id.asc())
            else:
                stmt = stmt.order_by(mst_flw_fsvlog.c.tsm.desc(), mst_flw_fsvlog.c.id.desc())
            if bus_kid is None and limit:
                stmt = stmt.limit(limit)
            rows = conn.execute(stmt).mappings().all()
        return [
            {
                "dte": r["dte"], "flw_kid": r["flw_kid"], "bus_kid": r["bus_kid"],
                "opr": r["opr"], "tsk_nme": r["tsk_nme"], "opr_typ": r["opr_typ"],
                "opr_ret": r["opr_ret"], "opr_ifo": self._dec(r["opr_ifo"]),
                "tsm": r["tsm"],
            }
            for r in rows
        ]
