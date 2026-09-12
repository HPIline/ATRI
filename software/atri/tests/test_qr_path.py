"""二维码路径 schema 测试：解析、校验、向后兼容。

重点锁三件事：
1. 旧格式（单条指令）**必须继续可用**——现场已经印好的二维码不能作废；
2. 非法路径要在**解析阶段**就拦下，而不是跑一半才发现；
3. 生成端与执行端共用同一套边界（这里是它的唯一实现）。
"""
from __future__ import annotations

import json
import unittest

from atri.config import MAX_STEPS, MAX_TURN_DEG
from atri.path_plan import (
    MAX_PATH_SEGMENTS,
    MAX_PATH_TOTAL_STEPS,
    PATH_SCHEMA,
    Path,
    PathError,
    PathSegment,
    build_path,
    normalize_segment,
    parse_payload,
    validate_segment,
    wrap_legacy,
)


class TestLegacyCompatibility(unittest.TestCase):
    def test_single_action_is_wrapped_as_one_segment(self):
        path = parse_payload({"action": "walk", "steps": 3})
        self.assertEqual(len(path.segments), 1)
        self.assertEqual(path.segments[0].action, "walk")
        self.assertEqual(path.segments[0].params["steps"], 3)
        self.assertTrue(path.is_legacy)
        self.assertEqual(path.source, "legacy")

    def test_legacy_round_trips_to_legacy_shape(self):
        """旧格式解析后再序列化，应该还是旧格式——不然现场二维码对不上。"""
        original = {"action": "turn", "deg": 90}
        path = parse_payload(original)
        self.assertEqual(path.to_payload(), {"action": "turn", "deg": 90.0})

    def test_json_string_payload_is_accepted(self):
        path = parse_payload('{"action":"walk","steps":2}')
        self.assertEqual(path.total_steps, 2)

    def test_wrap_legacy_helper(self):
        path = wrap_legacy("walk", {"steps": 4})
        self.assertEqual(path.total_steps, 4)

    def test_legacy_defaults_are_filled(self):
        path = parse_payload({"action": "walk"})
        self.assertEqual(path.segments[0].params["steps"], 3)  # 与旧默认值一致


class TestPathFormat(unittest.TestCase):
    def test_parses_multi_segment_path(self):
        payload = {
            "schema": PATH_SCHEMA,
            "path": [
                {"action": "walk", "steps": 3},
                {"action": "turn", "deg": 90},
                {"action": "walk", "steps": 2},
            ],
        }
        path = parse_payload(json.dumps(payload))
        self.assertEqual([s.action for s in path.segments], ["walk", "turn", "walk"])
        self.assertEqual(path.total_steps, 5)
        self.assertEqual(path.total_turn_deg, 90.0)
        self.assertFalse(path.is_legacy)

    def test_round_trip(self):
        segments = [{"action": "walk", "steps": 2}, {"action": "turn", "deg": -45}]
        path = build_path(segments)
        again = parse_payload(path.to_json())
        self.assertEqual(
            [s.to_dict() for s in again.segments], [s.to_dict() for s in path.segments]
        )

    def test_describe_is_human_readable(self):
        path = build_path([{"action": "walk", "steps": 3}, {"action": "turn", "deg": 90}])
        self.assertEqual(path.describe(), "走 3 步 → 转 90.0°")

    def test_schema_defaults_to_current_when_absent(self):
        path = parse_payload({"path": [{"action": "walk", "steps": 1}]})
        self.assertEqual(path.schema, PATH_SCHEMA)

    def test_unknown_schema_is_rejected_not_guessed(self):
        """不认识的 schema 要报错，不能"猜着兼容"——猜错在现场是不可恢复的。"""
        with self.assertRaises(PathError) as ctx:
            parse_payload({"schema": "atri.path.v99", "path": [{"action": "walk", "steps": 1}]})
        self.assertIn("schema", str(ctx.exception))


class TestPathValidation(unittest.TestCase):
    def test_empty_path_rejected(self):
        with self.assertRaises(PathError):
            parse_payload({"path": []})

    def test_too_many_segments_rejected(self):
        segments = [{"action": "walk", "steps": 1}] * (MAX_PATH_SEGMENTS + 1)
        with self.assertRaises(PathError) as ctx:
            parse_payload({"path": segments})
        self.assertIn("段数", str(ctx.exception))

    def test_total_step_budget_enforced(self):
        """单段合法但整条路径超预算，也要拦下——20 段 × 20 步现场跑不完。"""
        per_segment = MAX_PATH_TOTAL_STEPS // 4 + 1
        segments = [{"action": "walk", "steps": per_segment}] * 4
        with self.assertRaises(PathError) as ctx:
            parse_payload({"path": segments})
        self.assertIn("总步数", str(ctx.exception))

    def test_segment_index_is_reported(self):
        payload = {"path": [{"action": "walk", "steps": 1}, {"action": "turn", "deg": 999}]}
        with self.assertRaises(PathError) as ctx:
            parse_payload(payload)
        self.assertIn("path[1]", str(ctx.exception))

    def test_non_dict_payload_rejected(self):
        for bad in ([1, 2], "hello", 42, None):
            with self.subTest(bad=bad):
                with self.assertRaises(PathError):
                    parse_payload(bad)

    def test_payload_without_action_or_path_rejected(self):
        with self.assertRaises(PathError):
            parse_payload({"schema": PATH_SCHEMA})

    def test_path_field_must_be_list(self):
        with self.assertRaises(PathError):
            parse_payload({"path": {"action": "walk"}})


class TestSegmentValidation(unittest.TestCase):
    def test_accepts_valid_segments(self):
        validate_segment("walk", {"steps": 3})
        validate_segment("turn", {"deg": 45})
        validate_segment("dance", {"bars": 2})

    def test_rejects_unknown_action(self):
        with self.assertRaises(PathError):
            validate_segment("fly", {})

    def test_rejects_bool_as_number(self):
        """True 在 Python 里等于 1，但"真"不是"1 步"。"""
        with self.assertRaises(PathError):
            validate_segment("walk", {"steps": True})

    def test_rejects_nan_and_inf(self):
        with self.assertRaises(PathError):
            validate_segment("turn", {"deg": float("nan")})
        with self.assertRaises(PathError):
            validate_segment("turn", {"deg": float("inf")})

    def test_rejects_over_limit(self):
        with self.assertRaises(PathError):
            validate_segment("walk", {"steps": MAX_STEPS + 1})
        with self.assertRaises(PathError):
            validate_segment("turn", {"deg": MAX_TURN_DEG + 1})

    def test_normalize_fills_defaults(self):
        self.assertEqual(normalize_segment("walk", {})["steps"], 3)
        self.assertEqual(normalize_segment("turn", {})["deg"], 30.0)
        self.assertEqual(normalize_segment("dance", {})["bars"], 2)

    def test_normalize_keeps_extra_params(self):
        clean = normalize_segment("walk", {"steps": 2, "remark": "现场 A"})
        self.assertEqual(clean["remark"], "现场 A")


class TestPathObject(unittest.TestCase):
    def test_segment_describe(self):
        self.assertEqual(PathSegment("walk", {"steps": 2}).describe(), "走 2 步")
        self.assertEqual(PathSegment("turn", {"deg": 90}).describe(), "转 90°")
        self.assertEqual(PathSegment("dance", {"bars": 1}).describe(), "舞 1 小节")
        self.assertEqual(PathSegment("kick", {}).describe(), "kick")

    def test_to_dict_has_summary_fields(self):
        path = build_path([{"action": "walk", "steps": 2}])
        data = path.to_dict()
        self.assertEqual(data["total_steps"], 2)
        self.assertEqual(data["source"], "path")
        self.assertIn("describe", data)

    def test_empty_segments_rejected_at_construction(self):
        with self.assertRaises(PathError):
            Path(segments=[])


if __name__ == "__main__":
    unittest.main()
