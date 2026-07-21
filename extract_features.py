# -*- coding: utf-8 -*-
"""
================================================================================
 MC1 结构化特征提取脚本  (extract_features.py)
================================================================================
用途：
    在 clean_data(1).py 产出的干净长表基础上，从消息正文、internal_state 与
    环境文本中提取结构化特征，输出后续可视化/分析需要的表。

关键修订：
    1) 泄露风险分只针对 18:00 embargo 解除前计算，避免把 R22 正常公开传播
       误判成泄露。
    2) 将“治理叙事”和“合理化/自我开脱”拆开，降低合理化特征的假阳性。
    3) 补全 7 agent x 23 round 的行为指纹网格，沉默/缺席也进入偏离度计算。
    4) 增加 message_edges.csv 与 environment_text_features.csv，支持关系图和
       先行指标图。

如何运行：
    python extract_features.py --indir cleaned --outdir features

输出：
    - messages_features.csv
    - agent_round_fingerprint.csv
    - behavior_deviation.csv
    - leading_indicators.csv
    - message_edges.csv
    - environment_text_features.csv
    - feature_report.txt
================================================================================
"""

import argparse
import os
import re

import numpy as np


CRISIS_START_ROUND = 13
EMBARGO_LIFT_ROUND = 22       # R22 = 2046-06-05 18:00，禁令正式解除
PUBLIC_CHANNELS = {"official_post", "personal_post", "anonymous_post"}
UNOFFICIAL_PUBLIC_CHANNELS = {"personal_post", "anonymous_post"}
CHANNELS = [
    "comms_huddle",
    "one_on_one_chat",
    "side_huddle",
    "official_post",
    "personal_post",
    "anonymous_post",
]

ROLE_TOKEN_TO_AGENT_ID = {
    "legal": "legal_agent",
    "platform_trust": "quality_agent",
    "social_media": "social_media_agent",
    "social_manager": "social_media_agent",
    "pr": "pr_agent",
    "pr_intern": "pr_intern_agent",
    "pr-intern": "pr_intern_agent",
    "intern": "intern_agent",
    "judge": "judge_agent",
}


# 并购/禁令：用于识别触碰 embargo 的敏感内容。
MERGER_KEYWORDS = [
    "harborcrest",
    "civicloom",
    "merger",
    "acquisition",
    "embargo",
    "6 pm",
    "6:00 pm",
    "definitive agreement",
    "strategic partner",
    "rebrand",
    "residentedge",
]

# 真正受 embargo 保护的交易线索。泛化的 acquisition/merger 仍用于主题统计，
# 但不单独构成“泄露候选”，避免 ResidentIQ 谣言澄清造成假阳性。
EMBARGOED_DEAL_KEYWORDS = [
    "harborcrest",
    "civicloom",
    "residentedge",
    "embargo",
    "6 pm",
    "6:00 pm",
    "definitive agreement",
    "definitive merger",
    "acceleration clause",
    "bilateral consent",
    "mutual consent",
    "co-announce",
]

# 争议产品：回答典型行为/敏感主题演变。
PRODUCT_KEYWORDS = [
    "retention optimizer",
    "service load score",
    "payment friction",
    "exit probability",
    "analytics suite",
    "scoring",
    "re-identification",
    "algorithmic",
    "profiling",
]

# 规避/绕过：个人账号、匿名、技术上可辩护等。
EVASION_KEYWORDS = [
    "personal account",
    "personal capacity",
    "anonymous",
    "off the record",
    "technically defensible",
    "defensible",
    "not officially",
    "unofficial",
    "my own view",
    "as an individual",
    "plausible",
    "gray area",
    "grey area",
    "moot",
    "bilateral consent",
    "mutual consent",
]

# 合理化/自我开脱：不包含 governance/reforms 这类中性治理词。
RATIONALIZE_KEYWORDS = [
    "justified",
    "right thing",
    "no choice",
    "protect the company",
    "protect tenantthread",
    "already out there",
    "public anyway",
    "demanded by our residents",
    "purpose moot",
    "survival",
    "last piece",
    "single bottleneck",
]

# 治理叙事：违规内容常被包装成“改革/透明”的时间线。
GOVERNANCE_KEYWORDS = [
    "independent audit",
    "role-based access",
    "consent management",
    "governance reform",
    "governance timeline",
    "audit",
    "reforms shipped",
    "seven governance",
]

STRESS_KEYWORDS = [
    "critical",
    "urgent",
    "now",
    "immediately",
    "crisis",
    "escalat",
    "breach",
    "panic",
    "firestorm",
    "meltdown",
]

JUDGE_WARNING_KEYWORDS = [
    "compliance",
    "warning",
    "do not",
    "do not post",
    "embargo",
    "prohibited",
    "material nonpublic",
]

MENTION_RE = re.compile(r"@([\w-]+)")
HASHTAG_RE = re.compile(r"#([\w-]+)")
MONEY_RE = re.compile(r"\$\s?\d[\d,\.]*")
TIME_RE = re.compile(
    r"\b\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\b|\b\d{1,2}\s*(?:AM|PM|am|pm)\b"
)


def clean_text(value):
    if value is None:
        return ""
    try:
        import pandas as pd

        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value)


def combine_fields(row, fields):
    return " ".join(clean_text(row.get(field)) for field in fields if clean_text(row.get(field)))


def count_hits(text, keywords):
    t = clean_text(text).lower()
    return sum(t.count(k) for k in keywords)


def any_hit(text, keywords):
    return int(count_hits(text, keywords) > 0)


def split_pipe(value):
    text = clean_text(value)
    if not text:
        return []
    return [x for x in text.split("|") if x]


def resolve_mention_token(token):
    return ROLE_TOKEN_TO_AGENT_ID.get(clean_text(token).lower())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indir", default="cleaned", help="clean_data(1).py 的输出目录")
    ap.add_argument("--outdir", default="features", help="特征输出目录")
    args = ap.parse_args()

    import pandas as pd

    mpath = os.path.join(args.indir, "messages_clean.csv")
    epath = os.path.join(args.indir, "environment_clean.csv")
    ppath = os.path.join(args.indir, "participants_clean.csv")
    apath = os.path.join(args.indir, "agents_dim.csv")
    for path in (mpath, epath, ppath, apath):
        if not os.path.exists(path):
            raise SystemExit(f"[错误] 找不到 {path}，请先运行 clean_data(1).py。")

    msgs = pd.read_csv(mpath)
    env = pd.read_csv(epath)
    parts = pd.read_csv(ppath)
    agents = pd.read_csv(apath)
    os.makedirs(args.outdir, exist_ok=True)

    report = []

    def log(line):
        print(line)
        report.append(line)

    msgs["internal_text"] = msgs.apply(
        lambda row: combine_fields(row, ["reacting", "rationalizing", "deliberating"]),
        axis=1,
    )

    def extract_message_row(row):
        content = clean_text(row.get("content"))
        internal = clean_text(row.get("internal_text"))
        both = f"{content} {internal}"
        internal_only = internal
        mentions = MENTION_RE.findall(content)
        hashtags = HASHTAG_RE.findall(content)
        return pd.Series(
            {
                "mentions": "|".join(mentions),
                "n_mentions": len(mentions),
                "hashtags": "|".join(hashtags),
                "n_hashtags_text": len(hashtags),
                "n_money": len(MONEY_RE.findall(content)),
                "n_time_refs": len(TIME_RE.findall(content)),
                "kw_merger": count_hits(content, MERGER_KEYWORDS),
                "kw_embargoed_deal": count_hits(content, EMBARGOED_DEAL_KEYWORDS),
                "kw_product": count_hits(content, PRODUCT_KEYWORDS),
                "kw_governance": count_hits(content, GOVERNANCE_KEYWORDS),
                "kw_stress": count_hits(both, STRESS_KEYWORDS),
                "kw_evasion": count_hits(both, EVASION_KEYWORDS),
                "kw_rationalize": count_hits(both, RATIONALIZE_KEYWORDS),
                "kw_internal_evasion": count_hits(internal_only, EVASION_KEYWORDS),
                "kw_internal_rationalize": count_hits(internal_only, RATIONALIZE_KEYWORDS),
                "flag_merger": any_hit(content, MERGER_KEYWORDS),
                "flag_embargoed_deal": any_hit(content, EMBARGOED_DEAL_KEYWORDS),
                "flag_product": any_hit(content, PRODUCT_KEYWORDS),
                "flag_governance": any_hit(content, GOVERNANCE_KEYWORDS),
                "flag_evasion": any_hit(both, EVASION_KEYWORDS),
                "flag_rationalize": any_hit(both, RATIONALIZE_KEYWORDS),
                "flag_stress": any_hit(both, STRESS_KEYWORDS),
            }
        )

    feats = msgs.apply(extract_message_row, axis=1)
    mf = pd.concat([msgs, feats], axis=1)

    mf["round_idx"] = mf["round_idx"].astype(int)
    mf["is_pre_embargo_lift"] = (mf["round_idx"] < EMBARGO_LIFT_ROUND).astype(int)
    mf["is_crisis_window"] = (mf["round_idx"] >= CRISIS_START_ROUND).astype(int)
    mf["is_public"] = mf["channel"].isin(PUBLIC_CHANNELS).astype(int)
    mf["is_unofficial_public"] = mf["channel"].isin(UNOFFICIAL_PUBLIC_CHANNELS).astype(int)
    mf["pre_lift_public"] = (mf["is_public"] & mf["is_pre_embargo_lift"]).astype(int)
    mf["pre_lift_unofficial_public"] = (
        mf["is_unofficial_public"] & mf["is_pre_embargo_lift"]
    ).astype(int)
    mf["embargo_sensitive"] = (
        (mf["flag_embargoed_deal"] == 1) & (mf["is_pre_embargo_lift"] == 1)
    ).astype(int)
    mf["embargo_breach_candidate"] = (
        (mf["is_public"] == 1)
        & (mf["flag_embargoed_deal"] == 1)
        & (mf["is_pre_embargo_lift"] == 1)
    ).astype(int)
    mf["governance_wrapper_pre_lift"] = (
        (mf["kw_governance"] > 0)
        & (mf["flag_embargoed_deal"] == 1)
        & (mf["is_pre_embargo_lift"] == 1)
    ).astype(int)
    mf["out_of_role_post"] = (
        (mf["channel"].isin(UNOFFICIAL_PUBLIC_CHANNELS))
        & (mf["agent_role"].isin(["legal", "platform_trust", "intern", "pr_intern"]))
    ).astype(int)
    mf["non_official_release_behavior"] = (
        (mf["channel"].isin(UNOFFICIAL_PUBLIC_CHANNELS))
        & (mf["flag_embargoed_deal"] == 1)
        & (mf["is_pre_embargo_lift"] == 1)
    ).astype(int)

    # Embargo-aware 风险分：R22 解禁后不再给 embargo 泄露风险加分。
    pre = mf["is_pre_embargo_lift"].astype(int)
    mf["breach_risk_score"] = (
        pre * mf["is_public"].astype(int) * 2
        + pre * mf["flag_embargoed_deal"].astype(int) * 4
        + pre * mf["flag_merger"].astype(int)
        + pre * mf["flag_evasion"].astype(int) * 2
        + pre * mf["flag_rationalize"].astype(int)
        + pre * mf["is_unofficial_public"].astype(int) * 2
        + pre * mf["governance_wrapper_pre_lift"].astype(int) * 2
        + pre * mf["out_of_role_post"].astype(int)
        + pre * mf["kw_internal_evasion"].clip(0, 2)
    )

    mf.to_csv(os.path.join(args.outdir, "messages_features.csv"), index=False, encoding="utf-8-sig")

    # 关系边：reply/thread/mention 三类，供 Q1 时间线网络使用。
    id_to_agent = dict(zip(mf["message_id"], mf["agent_id"]))
    edge_rows = []
    for _, row in mf.iterrows():
        src_mid = row["message_id"]
        src_agent = row["agent_id"]
        parent_mid = clean_text(row.get("thread_parent"))
        raw_parent = clean_text(row.get("responding_to_raw"))
        if int(row.get("responding_to_valid", 0)) == 1 and raw_parent:
            edge_rows.append(
                {
                    "edge_type": "reply",
                    "round_idx": int(row["round_idx"]),
                    "timestamp": row["timestamp"],
                    "source_message_id": src_mid,
                    "target_message_id": raw_parent,
                    "source_agent_id": src_agent,
                    "target_agent_id": id_to_agent.get(raw_parent, ""),
                    "target_entity": id_to_agent.get(raw_parent, raw_parent),
                    "channel": row["channel"],
                    "edge_source": "responding_to_valid",
                }
            )
        if parent_mid and parent_mid != raw_parent:
            edge_rows.append(
                {
                    "edge_type": "thread_parent",
                    "round_idx": int(row["round_idx"]),
                    "timestamp": row["timestamp"],
                    "source_message_id": src_mid,
                    "target_message_id": parent_mid,
                    "source_agent_id": src_agent,
                    "target_agent_id": id_to_agent.get(parent_mid, ""),
                    "target_entity": id_to_agent.get(parent_mid, parent_mid),
                    "channel": row["channel"],
                    "edge_source": clean_text(row.get("thread_parent_source")),
                }
            )
        for token in MENTION_RE.findall(clean_text(row.get("content"))):
            target_agent = resolve_mention_token(token)
            edge_rows.append(
                {
                    "edge_type": "mention",
                    "round_idx": int(row["round_idx"]),
                    "timestamp": row["timestamp"],
                    "source_message_id": src_mid,
                    "target_message_id": "",
                    "source_agent_id": src_agent,
                    "target_agent_id": target_agent or "",
                    "target_entity": target_agent or f"@{token}",
                    "channel": row["channel"],
                    "edge_source": "content_mention",
                }
            )
    edges = pd.DataFrame(edge_rows)
    edges.to_csv(os.path.join(args.outdir, "message_edges.csv"), index=False, encoding="utf-8-sig")

    # 环境文本特征：把旁白/新闻/告警也纳入先行指标。
    def extract_env_row(row):
        text = combine_fields(
            row,
            [
                "event_headline",
                "event_narrative",
                "social_state",
                "media_events",
                "external_actor_actions",
                "social_manager_alerts",
                "critical_deadlines",
                "news",
            ],
        )
        hashtags = HASHTAG_RE.findall(text)
        return pd.Series(
            {
                "env_kw_merger": count_hits(text, MERGER_KEYWORDS),
                "env_kw_embargoed_deal": count_hits(text, EMBARGOED_DEAL_KEYWORDS),
                "env_kw_product": count_hits(text, PRODUCT_KEYWORDS),
                "env_kw_evasion": count_hits(text, EVASION_KEYWORDS),
                "env_kw_governance": count_hits(text, GOVERNANCE_KEYWORDS),
                "env_kw_stress": count_hits(text, STRESS_KEYWORDS),
                "env_n_hashtags_text": len(hashtags),
                "env_flag_merger": any_hit(text, MERGER_KEYWORDS),
                "env_flag_embargoed_deal": any_hit(text, EMBARGOED_DEAL_KEYWORDS),
                "env_flag_product": any_hit(text, PRODUCT_KEYWORDS),
                "env_flag_stress": any_hit(text, STRESS_KEYWORDS),
            }
        )

    env_text = pd.concat([env, env.apply(extract_env_row, axis=1)], axis=1)
    env_text.to_csv(
        os.path.join(args.outdir, "environment_text_features.csv"),
        index=False,
        encoding="utf-8-sig",
    )

    # 7 x 23 完整行为指纹网格。
    fp_rows = []
    round_ids = sorted(env["round_idx"].astype(int).unique())
    agent_ids = agents["agent_id"].tolist()
    parts_key = parts.set_index(["round_idx", "agent_id"])
    for ri in round_ids:
        for aid in agent_ids:
            g = mf[(mf["round_idx"] == ri) & (mf["agent_id"] == aid)]
            n = len(g)
            rec = {
                "round_idx": ri,
                "agent_id": aid,
                "n_msgs": n,
                "is_silent": int(n == 0),
                "public_post_rate": float(g["is_public"].mean()) if n else 0.0,
                "backstage_rate": float(g["is_backstage"].mean()) if n else 0.0,
                "frontstage_rate": float(g["is_frontstage"].mean()) if n else 0.0,
                "unofficial_public_rate": float(g["is_unofficial_public"].mean()) if n else 0.0,
                "out_of_role_rate": float(g["out_of_role_post"].mean()) if n else 0.0,
                "rationalize_rate": float(g["flag_rationalize"].sum() / n) if n else 0.0,
                "evasion_rate": float(g["flag_evasion"].sum() / n) if n else 0.0,
                "merger_mention_rate": float(g["flag_merger"].sum() / n) if n else 0.0,
                "embargo_breach_candidate_rate": float(g["embargo_breach_candidate"].sum() / n) if n else 0.0,
                "avg_content_len": float(g["content_len"].mean()) if n else 0.0,
                "avg_breach_risk": float(g["breach_risk_score"].mean()) if n else 0.0,
                "max_breach_risk": float(g["breach_risk_score"].max()) if n else 0.0,
            }
            for ch in CHANNELS:
                rec[f"share_{ch}"] = float((g["channel"] == ch).mean()) if n else 0.0
            if (ri, aid) in parts_key.index:
                part_row = parts_key.loc[(ri, aid)]
                rec["declared_action_verb"] = clean_text(part_row.get("declared_action_verb"))
                rec["action_classification"] = clean_text(part_row.get("action_classification"))
            else:
                rec["declared_action_verb"] = ""
                rec["action_classification"] = ""
            fp_rows.append(rec)
    fp = pd.DataFrame(fp_rows)
    fp.to_csv(
        os.path.join(args.outdir, "agent_round_fingerprint.csv"),
        index=False,
        encoding="utf-8-sig",
    )

    dim_cols = (
        [f"share_{ch}" for ch in CHANNELS]
        + [
            "public_post_rate",
            "backstage_rate",
            "unofficial_public_rate",
            "out_of_role_rate",
            "rationalize_rate",
            "evasion_rate",
            "merger_mention_rate",
            "embargo_breach_candidate_rate",
            "is_silent",
        ]
    )
    dev_rows = []
    for aid, g in fp.groupby("agent_id", sort=False):
        base = g[g["round_idx"] < CRISIS_START_ROUND][dim_cols].astype(float)
        mu = base.mean()
        sd = base.std().replace(0, np.nan).fillna(1)
        for _, row in g.iterrows():
            v = row[dim_cols].astype(float)
            z = (v - mu) / sd
            dev_rows.append(
                {
                    "round_idx": int(row["round_idx"]),
                    "agent_id": aid,
                    "deviation_D": float(np.sqrt((z ** 2).sum())),
                    "is_crisis": int(row["round_idx"] >= CRISIS_START_ROUND),
                }
            )
    dev = pd.DataFrame(dev_rows)
    dev.to_csv(
        os.path.join(args.outdir, "behavior_deviation.csv"),
        index=False,
        encoding="utf-8-sig",
    )

    grp = mf.groupby("round_idx")
    li = grp.agg(
        n_msgs=("message_id", "count"),
        n_side_huddle=("is_backstage", "sum"),
        n_public_posts=("is_public", "sum"),
        n_pre_lift_public=("pre_lift_public", "sum"),
        n_personal_anon=("is_unofficial_public", "sum"),
        n_pre_lift_personal_anon=("pre_lift_unofficial_public", "sum"),
        n_rationalize=("flag_rationalize", "sum"),
        n_evasion=("flag_evasion", "sum"),
        n_merger_mentions=("flag_merger", "sum"),
        n_embargo_breach_candidates=("embargo_breach_candidate", "sum"),
        n_non_official_release_behavior=("non_official_release_behavior", "sum"),
        n_out_of_role=("out_of_role_post", "sum"),
        max_breach_risk=("breach_risk_score", "max"),
    ).reset_index()

    judge = mf[mf["agent_id"] == "judge_agent"].copy()
    judge["judge_warning_hit"] = judge["content"].map(lambda x: any_hit(x, JUDGE_WARNING_KEYWORDS))
    judge_warnings = (
        judge.groupby("round_idx")["judge_warning_hit"].sum().reset_index(name="judge_warnings")
    )
    li = li.merge(judge_warnings, on="round_idx", how="left").fillna({"judge_warnings": 0})
    judge_msgs = judge.groupby("round_idx").size().reset_index(name="judge_n_msgs")
    li = li.merge(judge_msgs, on="round_idx", how="left").fillna({"judge_n_msgs": 0})
    li["judge_silent"] = (li["judge_n_msgs"] == 0).astype(int)

    li = li.merge(
        env_text[
            [
                "round_idx",
                "hour_label",
                "is_crisis_day",
                "stock_price",
                "percent_change",
                "sentiment",
                "sentiment_ordinal",
                "n_hashtags",
                "n_agents_unavailable",
                "env_kw_merger",
                "env_kw_embargoed_deal",
                "env_kw_product",
                "env_kw_stress",
                "env_flag_merger",
                "env_flag_embargoed_deal",
                "env_flag_product",
            ]
        ],
        on="round_idx",
        how="left",
    ).sort_values("round_idx")
    li.to_csv(os.path.join(args.outdir, "leading_indicators.csv"), index=False, encoding="utf-8-sig")

    log("=" * 64)
    log(" MC1 特征提取报告")
    log("=" * 64)
    log(f"输入目录: {args.indir}")
    log("")
    log(f"[1] messages_features.csv: {len(mf)} 行")
    log(f"    并购关键词消息数: {int(mf['flag_merger'].sum())}")
    log(f"    embargoed deal 强信号消息数: {int(mf['flag_embargoed_deal'].sum())}")
    log(f"    规避语言消息数: {int(mf['flag_evasion'].sum())}")
    log(f"    合理化消息数: {int(mf['flag_rationalize'].sum())}")
    log(f"    embargo 解除前公开并购候选泄露: {int(mf['embargo_breach_candidate'].sum())}")
    log(f"    embargo 解除前非官方公开并购行为: {int(mf['non_official_release_behavior'].sum())}")
    log("")
    top = mf.sort_values(["breach_risk_score", "round_idx"], ascending=[False, True])[
        ["round_idx", "timestamp", "agent_id", "channel", "breach_risk_score", "message_id"]
    ].head(10)
    log("    embargo-aware 风险分最高的 10 条消息:")
    for _, row in top.iterrows():
        log(
            f"      R{int(row['round_idx'])} {row['timestamp']} "
            f"{row['agent_id']:18s} {row['channel']:14s} "
            f"score={int(row['breach_risk_score'])} {row['message_id']}"
        )
    log("")
    log(f"[2] message_edges.csv: {len(edges)} 条 reply/thread/mention 边")
    log(f"[3] environment_text_features.csv: {len(env_text)} 行环境文本特征")
    log(f"[4] agent_round_fingerprint.csv: {len(fp)} 行，完整 7x23 网格")
    log(f"[5] behavior_deviation.csv: {len(dev)} 行")
    hi = dev.sort_values("deviation_D", ascending=False).head(8)
    log("    偏离度最高的 8 个 (agent, round):")
    for _, row in hi.iterrows():
        log(f"      R{int(row['round_idx'])} {row['agent_id']:18s} D={row['deviation_D']:.2f}")
    log("")
    log(f"[6] leading_indicators.csv: {len(li)} 行 round 级先行指标")

    with open(os.path.join(args.outdir, "feature_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(report))

    print("\n[完成] 特征提取结束。")


if __name__ == "__main__":
    main()
