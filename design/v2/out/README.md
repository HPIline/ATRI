# ATRI-v2 当前同源审查输出

状态：未放行整机打样。完整线束、质量和G0–G4尚未闭合。

- 当前完整装配：`cad/ATRI-v2-review.step`。
- 逐件清单：`manufacturing/manifest.json`；激光毛坯在`manufacturing/laser/`，不是旧`dxf/`。
- PETG/TPU：`manufacturing/print/`的定向STL和mm单位3MF；切片和配合需样件。
- 角铝：`stock-templates`只是翼面参考轮廓，结合STEP及工艺说明询价，不是折弯展开图。
- 网页：`preview/ATRI-v2.html`；URDF：`sim/atri_v2.urdf`，尚未真导入Webots。
- `blender/renders`是GPU光追CAD图，不是实物照片。
- 质量见`质量账.md`；门禁见`gates.json`；所有未知质量不得填0。

在工作树根目录运行`PYTHONPATH=design python3 -m v2.generate`重新生成。旧局部审查和`legacy-superseded`文件不作为加工入口。
