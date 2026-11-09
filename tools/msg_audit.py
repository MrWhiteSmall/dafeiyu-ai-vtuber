# -*- coding: utf-8 -*-
"""消息对账：把 log/messages-YYYY-MM-DD.log 汇总成一眼能看的报表。

用法：
    .\\.venv\\Scripts\\python.exe -u tools\\msg_audit.py            # 今天
    .\\.venv\\Scripts\\python.exe -u tools\\msg_audit.py --date 2026-11-08
    .\\.venv\\Scripts\\python.exe -u tools\\msg_audit.py --kind 弹幕 --tail 30

看什么：
    1) 收到多少 ⇄ 回了多少 ⇄ 丢了多少，对不上就是“漏”
    2) 漏掉的弹幕逐条列出（时间、用户、内容），这就是要排查的对象
    3) 丢弃原因排行，一眼看出是违禁词、纯表情还是别的
"""
import argparse
import datetime
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
LINE_RE = re.compile(
    r"^(?P<ts>\d{2}:\d{2}:\d{2}\.\d{3}) \| #(?P<mid>-|\d+)\s*\| (?P<stage>IN|OUT|DROP|SKIP)\s*"
    r"\| (?P<kind>\S+)\s*\| 用户=(?P<user>.*?) \| 内容=(?P<content>.*?)"
    r"(?: \| (?P<detail>.*))?$"
)


def parse(path):
    recs = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            m = LINE_RE.match(raw.rstrip("\n"))
            if not m:
                continue
            d = m.groupdict()
            d["mid"] = None if d["mid"] == "-" else int(d["mid"])
            recs.append(d)
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--kind", default=None, help="只看某一类，如 弹幕/进场/关注/礼物")
    ap.add_argument("--tail", type=int, default=15, help="漏掉的明细列多少条")
    args = ap.parse_args()

    path = ROOT / "log" / f"messages-{args.date}.log"
    if not path.exists():
        print(f"没有这个文件：{path}")
        print("（说明还没收到过消息，或者今天的日志还没生成）")
        return

    recs = parse(path)
    if args.kind:
        recs = [r for r in recs if r["kind"] == args.kind]

    ins = [r for r in recs if r["stage"] == "IN"]
    outs = [r for r in recs if r["stage"] == "OUT"]
    drops = [r for r in recs if r["stage"] == "DROP"]
    skips = [r for r in recs if r["stage"] == "SKIP"]

    # 每条 IN 有没有结论
    answered = {r["mid"] for r in outs if r["mid"] is not None}
    dropped = {r["mid"] for r in drops if r["mid"] is not None}
    skipped = {r["mid"] for r in skips if r["mid"] is not None}
    silent = [r for r in ins if r["mid"] not in answered | dropped | skipped]

    print(f"文件：{path.name}")
    print(f"收到 {len(ins)} 条 | 回了 {len(outs)} 条 | 丢了 {len(drops)} 条 | 记账未回 {len(skips)} 条"
          f" | 有结论 {len(ins) - len(silent)} / {len(ins)}")
    if ins:
        rate = (len(ins) - len(silent)) / len(ins) * 100
        print(f"对账覆盖率：{rate:.1f}%（{len(silent)} 条没有结论）")

    by_kind = Counter(r["kind"] for r in ins)
    if by_kind:
        print("\n按类型：")
        for k, n in by_kind.most_common():
            kn = sum(1 for r in ins if r["kind"] == k)
            ko = len({r["mid"] for r in outs if r["mid"] in
                      {x["mid"] for x in ins if x["kind"] == k}})
            kd = len({r["mid"] for r in drops if r["mid"] in
                      {x["mid"] for x in ins if x["kind"] == k}})
            ks = len({r["mid"] for r in skips if r["mid"] in
                      {x["mid"] for x in ins if x["kind"] == k}})
            gap = kn - ko - kd - ks
            flag = "  ← 有漏" if gap > 0 else ""
            print(f"  {k:<4} 收到 {kn:>3} | 回 {ko:>3} | 丢 {kd:>3} | 记账 {ks:>3} | 无结论 {gap:>3}{flag}")

    if drops:
        print("\n丢弃原因：")
        for reason, n in Counter(r["detail"] or "未写原因" for r in drops).most_common(10):
            print(f"  {n:>3} × {reason}")

    print(f"\n没有结论的消息（最多列 {args.tail} 条，全量看 log/messages-*.log）：")
    if not silent:
        print("  （无，全部都有结论）")
    for r in silent[-args.tail:]:
        print(f"  {r['ts']} [{r['kind']}] {r['user']}：{r['content']}")

    # 谁问得最多
    top = Counter(r["user"] for r in ins).most_common(5)
    if top:
        print("\n发言最多：" + "，".join(f"{u}({n})" for u, n in top))

    # 提示怎么继续查
    if silent:
        print("\n下一步：")
        print("  Select-String -Path log\\log-*.txt -Pattern '<用户或内容关键字>'   看它经过哪些处理分支")
        print("  或者看同一时间段有没有 [丢弃] 行")


if __name__ == "__main__":
    main()
