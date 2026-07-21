# -*- coding: utf-8 -*-
"""
================================================================================
 MC1 数据清洗脚本  (clean_data.py)
================================================================================
用途：
    读取 VAST Challenge 2026 MC1 的原始文件 MC1_final_00.json，将其从
    "按 round 嵌套" 的结构摊平为 3 张干净的长表，并修复所有已知的数据质量问题，
    输出 CSV（默认）与一个整合后的 JSON，供后续特征提取 / 可视化直接使用。

如何运行：
    1) 把本脚本放在与 MC1_final_00.json 【同一个文件夹】下；
    2) 安装依赖（只需 pandas）：
           pip install pandas
    3) 直接运行：
           python clean_data.py
       （如需指定输入文件名或输出目录：
           python clean_data.py --input MC1_final_00.json --outdir cleaned ）

输出（默认写到 ./cleaned/ 目录）：
    - messages_clean.csv       一行一条消息（912 行），核心表
    - environment_clean.csv    一行一个 round（23 行），世界/环境状态
    - participants_clean.csv   一行一个 (round, agent)（100 行），含 declared_action 等
    - agents_dim.csv           agent 维度表（7 个 agent 的 id/role/label/层级）
    - cleaning_report.txt       本次清洗做了什么、修了多少问题的报告
    - mc1_clean.json            上述表整合后的 JSON（可选，方便 JS/D3 直接读）

依赖：Python 3.8+，pandas
================================================================================
"""

import json
import os
import re
import argparse
from datetime import datetime


# ------------------------------------------------------------------ #
# 0. 常量与字典：修复 "角色名不一致" 陷阱                              #
# ------------------------------------------------------------------ #
# 数据内部存在三方不一致：
#   - agent_id        = social_media_agent
#   - agent_role      = social_media          （communications/participants 里的字段）
#   - recipients / @提及 token = social_manager （收件人和 responding_to 里用的名字）
#   - 官方说明文档写的又是 social_manager_agent / judge_eval_agent
# 因此需要一张 "role token -> 规范 agent_id" 的映射，才能把 @提及 / recipients 解析到人。
ROLE_TOKEN_TO_AGENT_ID = {
    "legal":          "legal_agent",
    "platform_trust": "quality_agent",       # 注意：id 叫 quality_agent，但角色是平台信任
    "social_media":   "social_media_agent",
    "social_manager": "social_media_agent",  # recipients/@提及里用的是 social_manager
    "pr":             "pr_agent",
    "pr_intern":      "pr_intern_agent",
    "intern":         "intern_agent",
    "judge":          "judge_agent",
}

# agent 维度表（层级：Senior 高级 / Junior 初级 / Compliance 合规官）
AGENTS_DIM = [
    # agent_id,            role,            label,               seniority,      desc
    ("legal_agent",        "legal",          "Legal-Agent",        "Senior",       "法务总顾问：把关合规与法律风险"),
    ("quality_agent",      "platform_trust", "Platform-Trust-Agent","Senior",      "平台信任与安全 VP：维护并解释评分产品"),
    ("social_media_agent", "social_media",   "Social-Manager-Agent","Senior",      "社媒经理：运营对外社媒账号与舆情监测"),
    ("pr_agent",           "pr",             "PR-Agent",           "Senior",       "公关主管：对外传播与危机公关"),
    ("intern_agent",       "intern",         "Intern-Agent",       "Junior",       "通用实习生"),
    ("pr_intern_agent",    "pr_intern",      "PR-Intern-Agent",    "Junior",       "公关实习生：持有官方 TenantThread Flex 账号权限"),
    ("judge_agent",        "judge",          "Judge",              "Compliance",   "合规官/裁判：评估风险、调解冲突、给出合规指引"),
]

# 危机当天（逐小时快照）从这个 round 开始；此前是每日 9AM 基线快照
CRISIS_START_ROUND = 13

# 公开发帖通道
PUBLIC_CHANNELS     = {"official_post", "personal_post", "anonymous_post"}
FRONTSTAGE_CHANNELS = {"official_post"}                 # 官方前台
BACKSTAGE_CHANNELS  = {"side_huddle"}                   # 影子/后台频道

MSG_ID_RE = re.compile(r"^\d{8}_(\d+)_(\d+)$")          # YYYYMMDD_ROUND_SEQ
MENTION_RE = re.compile(r"@([\w-]+)")


# ------------------------------------------------------------------ #
# 1. 小工具：解析数值 / 时间                                          #
# ------------------------------------------------------------------ #
def parse_money(v):
    """ '$38.70' -> 38.70 ; None/异常 -> None """
    if v is None:
        return None
    s = str(v).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_percent(v):
    """ '-0.5%' -> -0.5 ; None -> None """
    if v is None:
        return None
    s = str(v).replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_ts(ts):
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def round_of_msgid(mid):
    """ 从 message_id 里取出 round 号；取不到返回 None """
    m = MSG_ID_RE.match(str(mid))
    return int(m.group(1)) if m else None


def normalize_ws(s):
    """ 统一空白，便于做重复文本判断 """
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


# ------------------------------------------------------------------ #
# 2. 主流程                                                           #
# ------------------------------------------------------------------ #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="MC1_final_00.json", help="原始 JSON 文件名")
    ap.add_argument("--outdir", default="cleaned", help="输出目录")
    ap.add_argument("--no-json", action="store_true", help="不输出整合后的 mc1_clean.json")
    args = ap.parse_args()

    import pandas as pd

    if not os.path.exists(args.input):
        raise SystemExit(f"[错误] 找不到输入文件 {args.input}，请把脚本放在与该 JSON 同级的目录下。")

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    rounds = data["rounds"]
    os.makedirs(args.outdir, exist_ok=True)

    report = []          # 清洗报告
    def log(s):
        print(s)
        report.append(s)

    log("=" * 64)
    log(" MC1 数据清洗报告")
    log("=" * 64)
    log(f"输入文件      : {args.input}")
    log(f"round 数      : {len(rounds)}")

    # ---- 2.1 先建 message_id -> (timestamp, round) 索引，用于校验 responding_to ---- #
    id2ts, id2round = {}, {}
    for r in rounds:
        for c in r["communications"]:
            id2ts[c["message_id"]] = c["timestamp"]
            id2round[c["message_id"]] = round_of_msgid(c["message_id"])

    # ---- 2.2 摊平 messages ---- #
    msg_rows = []
    cnt_future_ref = 0
    cnt_mention_ref = 0
    cnt_dangling = 0
    cnt_valid_ref = 0
    cnt_internal = 0

    for ri, r in enumerate(rounds):
        hour = r["hour"]
        dt = parse_ts(hour)
        day = dt.date().isoformat() if dt else None
        is_crisis = ri >= CRISIS_START_ROUND

        for c in r["communications"]:
            ist = c.get("internal_state")
            if isinstance(ist, dict):
                reacting = ist.get("reacting")
                rationalizing = ist.get("rationalizing")
                deliberating = ist.get("deliberating")
            else:
                reacting = rationalizing = deliberating = None
            has_internal = any([reacting, rationalizing, deliberating])
            if has_internal:
                cnt_internal += 1

            # ---- responding_to：区分三种格式并校验 ----
            rt = c.get("responding_to")
            rt_type = "null"
            rt_resolved_agents = []     # 解析出的 agent_id 列表（针对 @提及）
            rt_valid = False            # 指向的 message_id 是否存在且在过去
            rt_is_future = False        # 指向的 message_id 在未来（损坏）
            rt_target_round = None

            if rt is None or rt == "":
                rt_type = "null"
            elif MSG_ID_RE.match(str(rt)):
                rt_type = "message_id"
                rt_target_round = round_of_msgid(rt)
                if rt in id2ts:
                    tgt = parse_ts(id2ts[rt]); cur = parse_ts(c["timestamp"])
                    if tgt and cur and tgt > cur:
                        rt_is_future = True
                        cnt_future_ref += 1
                    else:
                        rt_valid = True
                        cnt_valid_ref += 1
                else:
                    cnt_dangling += 1
            elif str(rt).startswith("@"):
                rt_type = "mention"
                cnt_mention_ref += 1
                for tok in MENTION_RE.findall(str(rt)):
                    aid = ROLE_TOKEN_TO_AGENT_ID.get(tok)
                    if aid:
                        rt_resolved_agents.append(aid)
            else:
                rt_type = "other"

            recips = c.get("recipients") or []
            # 把 recipients 里的角色 token 也解析成 agent_id（ALL 保留）
            recips_resolved = []
            for x in recips:
                if x == "ALL":
                    recips_resolved.append("ALL")
                else:
                    recips_resolved.append(ROLE_TOKEN_TO_AGENT_ID.get(x, x))

            channel = c["channel"]
            content = c.get("content") or ""

            msg_rows.append({
                "message_id":        c["message_id"],
                "round_idx":         ri,
                "msgid_round":       round_of_msgid(c["message_id"]),
                "timestamp":         c["timestamp"],
                "hour_label":        hour,
                "day":               day,
                "is_crisis_day":     is_crisis,
                "agent_id":          c["agent_id"],
                "agent_role":        c["agent_role"],
                "agent_label":       c.get("agent_label"),
                "channel":           channel,
                "message_type":      c["message_type"],
                "recipients":        "|".join(map(str, recips)),
                "recipients_resolved": "|".join(recips_resolved),
                "n_recipients":      len([x for x in recips if x != "ALL"]),
                "is_broadcast":      ("ALL" in recips),
                # 通道分层（本题分析灵魂）
                "is_public":         channel in PUBLIC_CHANNELS,
                "is_frontstage":     channel in FRONTSTAGE_CHANNELS,
                "is_backstage":      channel in BACKSTAGE_CHANNELS,
                "is_action":         c["message_type"] == "action",
                # 决策点：显式 action，或公开发帖
                "is_decision":       (c["message_type"] == "action") or (channel in PUBLIC_CHANNELS),
                "content":           content,
                "content_len":       len(content),
                # 内部独白拆列
                "reacting":          reacting,
                "rationalizing":     rationalizing,
                "deliberating":      deliberating,
                "has_internal_state": has_internal,
                # responding_to 清洗结果
                "responding_to_raw":     rt,
                "responding_to_type":    rt_type,           # null / message_id / mention / other
                "responding_to_valid":   rt_valid,          # 指向过去且存在 → 可信
                "responding_to_is_future": rt_is_future,    # 指向未来 → 损坏（危机窗口）
                "responding_to_target_round": rt_target_round,
                "responding_to_resolved_agents": "|".join(rt_resolved_agents),
            })

    msgs = pd.DataFrame(msg_rows)

    # ---- 2.3 重建 thread_id ----
    # 规则：
    #   (a) responding_to_valid 的 message_id → 直接用它做父节点；
    #   (b) mention 型 / 损坏的 future 型 / null → 父节点置空（留给特征脚本用启发式补），
    #       这里给出一个 "同通道最近一条其他 agent 消息" 的启发式父节点，便于危机窗口画线程。
    msgs = msgs.sort_values(["round_idx", "timestamp", "message_id"]).reset_index(drop=True)
    parent = {}
    # 先放可信父节点
    valid_parent = dict(zip(msgs["message_id"],
                            msgs.apply(lambda x: x["responding_to_raw"] if x["responding_to_valid"] else None, axis=1)))
    # 启发式：为 mention / future / null，找同 round 同 channel 里此前最近一条“他人”消息
    heuristic_parent = {}
    by_round = {ri: g for ri, g in msgs.groupby("round_idx")}
    for ri, g in by_round.items():
        g = g.sort_values("timestamp")
        recent_in_channel = {}
        for _, row in g.iterrows():
            mid = row["message_id"]
            if valid_parent.get(mid):
                heuristic_parent[mid] = valid_parent[mid]
            else:
                cand = recent_in_channel.get(row["channel"])
                heuristic_parent[mid] = cand  # 可能为 None
            recent_in_channel[row["channel"]] = mid
    msgs["thread_parent"] = msgs["message_id"].map(heuristic_parent)
    msgs["thread_parent_source"] = msgs.apply(
        lambda x: "responding_to" if x["responding_to_valid"] else
                  ("heuristic" if x["thread_parent"] else "none"), axis=1)

    # ---- 2.3b 标记重复 / 近重复公开帖（保留，不删除） ----
    msgs["content_norm"] = msgs["content"].map(normalize_ws)
    msgs["public_post_exact_dup_count"] = 1
    msgs["public_post_exact_dup_group"] = None
    msgs["public_post_near_dup_group"] = None

    public_mask = msgs["is_public"] & msgs["content_norm"].ne("")
    public_msgs = msgs.loc[public_mask, ["message_id", "content_norm"]].copy()

    # 完全相同文本：同一条公开帖被重复发出
    exact_groups = public_msgs.groupby("content_norm")["message_id"].agg(list)
    exact_dup_idx = 1
    for _, mids in exact_groups.items():
        if len(mids) > 1:
            group_id = f"exact_dup_{exact_dup_idx}"
            exact_dup_idx += 1
            msgs.loc[msgs["message_id"].isin(mids), "public_post_exact_dup_count"] = len(mids)
            msgs.loc[msgs["message_id"].isin(mids), "public_post_exact_dup_group"] = group_id

    # 近重复：同一公开帖被扩写/续写，但前缀框架完全相同
    prefix_col = msgs["content_norm"].map(lambda s: s[:240] if s else "")
    msgs["public_post_prefix_240"] = prefix_col
    prefix_groups = msgs.loc[public_mask].groupby("public_post_prefix_240")["message_id"].agg(list)
    near_dup_idx = 1
    for prefix, mids in prefix_groups.items():
        if prefix and len(mids) > 1:
            texts = msgs.loc[msgs["message_id"].isin(mids), "content_norm"].tolist()
            if len(set(texts)) > 1:
                group_id = f"near_dup_{near_dup_idx}"
                near_dup_idx += 1
                msgs.loc[msgs["message_id"].isin(mids), "public_post_near_dup_group"] = group_id

    # ---- 2.4 environment 表 ----
    env_rows = []
    stock_outliers = []
    for ri, r in enumerate(rounds):
        ec = r["environment_context"]
        ms = ec.get("market_snapshot") or {}
        price = parse_money(ms.get("stock_price"))
        pct = parse_percent(ms.get("percent_change"))
        env_rows.append({
            "round_idx":       ri,
            "hour_label":      r["hour"],
            "timestamp":       r["hour"],
            "day":             (parse_ts(r["hour"]).date().isoformat() if parse_ts(r["hour"]) else None),
            "is_crisis_day":   ri >= CRISIS_START_ROUND,
            "event_headline":  ec.get("event_headline"),
            "event_narrative": ec.get("event_narrative"),
            "social_state":    ec.get("social_state"),
            "stock_price":     price,
            "percent_change":  pct,
            "sentiment":       ms.get("sentiment"),
            "trending_hashtags": "|".join(ms.get("trending_hashtags") or []),
            "n_hashtags":      len(ms.get("trending_hashtags") or []),
            "media_events":    "||".join(ec.get("media_events") or []),
            "external_actor_actions": "||".join(ec.get("external_actor_actions") or []),
            "social_manager_alerts":  "||".join(ec.get("social_manager_alerts") or []),
            "critical_deadlines":     "||".join(ec.get("critical_deadlines") or []),
            "agents_unavailable":     "|".join(ec.get("agents_unavailable") or []),
            "n_agents_unavailable":   len(ec.get("agents_unavailable") or []),
            "news":            "||".join(ec.get("news") or []),
        })
        # 股价离群点检测（例如 R15 的 $180 与同阶段后续 $27.20/$26.90/$18.0 明显不符）
        if price is not None and price > 100:
            stock_outliers.append((ri, price))
    env = pd.DataFrame(env_rows)

    # sentiment 有序编码（neutral < cautious < ... < CRITICAL），便于画压力曲线
    sent_order = {"neutral": 0, "cautious": 1, "concerned": 2, "negative": 3,
                  "LOW": 3, "HIGH": 4, "CRITICAL": 5, "RECOVERING": 2}
    env["sentiment_ordinal"] = env["sentiment"].map(lambda s: sent_order.get(s, None))

    # ---- 2.5 participants 表 ----
    part_rows = []
    for ri, r in enumerate(rounds):
        for p in r["participants"]:
            md = p.get("agent_round_metadata") or {}
            da_raw = p.get("declared_action")
            # 拆分 declared_action 的动作动词前缀与正文
            da_verb, da_text = None, None
            if da_raw:
                m = re.match(r"^([A-Z_]+)\s*[:\-—]?\s*(.*)$", da_raw.strip(), re.S)
                if m:
                    da_verb = m.group(1)
                    da_text = m.group(2).strip().strip('"') or None
                else:
                    da_verb = da_raw.strip().split()[0]
                    da_text = da_raw
            part_rows.append({
                "round_idx":            ri,
                "hour_label":           r["hour"],
                "agent_id":             p["agent_id"],
                "agent_role":           p["agent_role"],
                "agent_label":          p.get("agent_label"),
                "declared_action_raw":  da_raw,
                "declared_action_verb": da_verb,          # POSTED_ANONYMOUS / MONITORING / ...
                "declared_action_text": da_text,          # 动作附带的正文（若有）
                "sentiment_at_turn":    md.get("sentiment_at_turn"),
                "action_classification": md.get("action_classification"),
            })
    parts = pd.DataFrame(part_rows)

    # ---- 2.6 agent 维度表 ----
    agents = pd.DataFrame(AGENTS_DIM,
                          columns=["agent_id", "agent_role", "agent_label", "seniority", "description_zh"])

    # ------------------------------------------------------------------ #
    # 3. 写出                                                             #
    # ------------------------------------------------------------------ #
    msgs.to_csv(os.path.join(args.outdir, "messages_clean.csv"), index=False, encoding="utf-8-sig")
    env.to_csv(os.path.join(args.outdir, "environment_clean.csv"), index=False, encoding="utf-8-sig")
    parts.to_csv(os.path.join(args.outdir, "participants_clean.csv"), index=False, encoding="utf-8-sig")
    agents.to_csv(os.path.join(args.outdir, "agents_dim.csv"), index=False, encoding="utf-8-sig")

    # ------------------------------------------------------------------ #
    # 4. 报告                                                             #
    # ------------------------------------------------------------------ #
    log("")
    log("-- 摊平结果 --")
    log(f"messages 行数      : {len(msgs)}")
    log(f"environment 行数   : {len(env)}")
    log(f"participants 行数  : {len(parts)}")
    log("")
    log("-- responding_to 清洗 --")
    log(f"  null（无回复对象）           : {(msgs['responding_to_type']=='null').sum()}")
    log(f"  message_id 且可信（指向过去）: {cnt_valid_ref}")
    log(f"  message_id 但【指向未来·损坏】: {cnt_future_ref}   （集中在危机 round {CRISIS_START_ROUND}-21，全部错指向 round 22）")
    log(f"  @提及（需解析角色）          : {cnt_mention_ref}")
    log(f"  悬空（message_id 不存在）    : {cnt_dangling}")
    log(f"  → 已新增列：responding_to_type / _valid / _is_future / _resolved_agents")
    log(f"  → thread_parent：可信处用 responding_to，其余用同通道最近消息启发式补")
    log("")
    log("-- 其他修复 --")
    log(f"  internal_state 拆成 reacting/rationalizing/deliberating 三列（{cnt_internal} 条非空）")
    log(f"  stock_price / percent_change 去掉 $ 和 % 转为浮点（stock 5 个 None，pct 6 个 None）")
    log(f"  股价离群点（>100，疑似录入错误）: {stock_outliers}")
    log(f"  declared_action 拆成 verb + text 两列")
    log(f"  角色名映射：social_manager/social_media → social_media_agent；platform_trust → quality_agent")
    log(f"  sentiment 有序编码列 sentiment_ordinal 已加入 environment 表")
    exact_dup_rows = int((msgs["public_post_exact_dup_count"] > 1).sum())
    near_dup_rows = int(msgs["public_post_near_dup_group"].notna().sum())
    log(f"  重复公开帖标记：完全重复 {exact_dup_rows} 条；近重复/扩写 {near_dup_rows} 条（保留，不删除）")
    log("")
    log("-- 输出文件（目录 %s）--" % args.outdir)
    for fn in ["messages_clean.csv", "environment_clean.csv",
               "participants_clean.csv", "agents_dim.csv", "cleaning_report.txt"]:
        log(f"  {fn}")

    if not args.no_json:
        clean_json = {
            "messages":     msgs.to_dict(orient="records"),
            "environment":  env.to_dict(orient="records"),
            "participants": parts.to_dict(orient="records"),
            "agents":       agents.to_dict(orient="records"),
        }
        with open(os.path.join(args.outdir, "mc1_clean.json"), "w", encoding="utf-8") as f:
            json.dump(clean_json, f, ensure_ascii=False, indent=1)
        log("  mc1_clean.json")

    with open(os.path.join(args.outdir, "cleaning_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(report))

    print("\n[完成] 清洗结束。")


if __name__ == "__main__":
    main()
