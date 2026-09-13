"""盒体静立可视化：能看见连杆，而不是只剩天空。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
    from PIL import Image
except ImportError:  # CI 没装依赖时 skip，不要让 discover 记 ERROR
    np = None
    Image = None

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "webots" / "tools"))
sys.path.insert(0, str(REPO_ROOT / "software" / "atri"))

try:
    import render_stand_video as vis  # noqa: E402
    from atri.stand_balance import stand_base_pose  # noqa: E402
except ImportError:
    vis = None
    stand_base_pose = None


@unittest.skipUnless(
    np is not None and Image is not None and vis is not None,
    "需要 numpy、Pillow、matplotlib",
)
class TestStandVis(unittest.TestCase):
    def test_left_ankle_is_below_pelvis_in_fk(self):
        boxes = {b["name"]: b for b in vis.link_boxes({})}
        z = float(boxes["left_ankle_pitch"]["center"][2])
        self.assertAlmostEqual(z, -0.188, places=3)

    def test_render_frame_shows_more_than_sky(self):
        pose = stand_base_pose()
        boxes = vis.world_boxes(pose, (0.0, 0.0, 0.20), (0.0, 0.0, 0.0))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frame.png"
            vis.render_frame(boxes, path, title="stand")
            im = Image.open(path).convert("RGB")
            arr = np.asarray(im)
            uniq = len({tuple(px) for px in arr.reshape(-1, 3)[::20]})
            self.assertGreater(uniq, 8, msg="画面颜色太少，多半还是空天空")
            # 蓝色连杆应出现
            blue = int(((arr[:, :, 2] > 140) & (arr[:, :, 0] < 100)).sum())
            self.assertGreater(blue, 200, msg="看不见腿部蓝色盒")


if __name__ == "__main__":
    unittest.main()
