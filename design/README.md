# 设计

当前机构是 **ATRI-v2 A 路线**：20 DOF、无 `hip_yaw`，6061 铝夹层 + 2.4 mm PETG，单电池，单舵机两指夹爪。入口 [`v2/README.md`](v2/README.md)。

参数只从 [`v2/profile.py`](v2/profile.py) 出。同源审查产物在 `v2/out/`。

`geometry.py` 是给当前 Webots 生成器用的几何基元。舵机协议在 `reference/sts3215/`。

旧 22 DOF CAD / URDF / 世界整包在 [`archive/v1-22dof/`](../archive/v1-22dof/README.md)，不是当前方案。
