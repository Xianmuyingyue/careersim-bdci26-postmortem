"""扫描 Dev 数据集全部事件，统计 status_updates 中出现 Level 变更的选项。

用途：验证「晋升只有半年评审一条通道」这一假设是否成立——
promotion_conditions.PromotionApplicator 每次只 +1，且窗口仅 8 个（M6..M48），
若另一条通道（事件破格提拔）存在，则 L10 的可达性需要重新计算。
"""

from __future__ import annotations

import json
import sys
import zlib
from pathlib import Path

import msgpack

DATASET = Path(
    "<PROJECT_ROOT>/CareerSim-BDCI26/.venv/lib/python3.12/"
    "site-packages/career_emulator_bdci26/dev/dataset"
)

LEVEL_KEYS = {"Level", "level"}


def decode(path: Path):
    raw = path.read_bytes()
    if path.suffix == ".data":
        return msgpack.loads(zlib.decompress(raw[1:], wbits=-15), strict_map_key=False)
    return json.loads(raw.decode("utf-8"))


def walk_status_updates(node, path: str = ""):
    """递归找出所有 status_updates 映射。"""
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"status_updates", "status_update", "effects"} and isinstance(value, dict):
                found.append((f"{path}/{key}", value))
            found.extend(walk_status_updates(value, f"{path}/{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(walk_status_updates(value, f"{path}[{index}]"))
    return found


def main() -> int:
    hits = []
    total_choices = 0
    files = sorted(p for p in DATASET.rglob("*") if p.is_file() and p.suffix in {".json", ".data"})
    for path in files:
        try:
            payload = decode(path)
        except Exception as exc:  # noqa: BLE001
            print(f"[skip] {path.name}: {exc}", file=sys.stderr)
            continue
        for node_path, updates in walk_status_updates(payload):
            total_choices += 1
            level_delta = {k: v for k, v in updates.items() if k in LEVEL_KEYS}
            if level_delta:
                hits.append((path.relative_to(DATASET), node_path, level_delta, updates))

    print(f"扫描文件 {len(files)} 个；含 status_updates 的选项 {total_choices} 个")
    print(f"★ 含 Level 变更的选项：{len(hits)} 个\n")
    for rel, node_path, delta, updates in hits:
        print(f"- {rel} {node_path}")
        print(f"    Level 变更 = {delta}")
        print(f"    全量更新   = {updates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
