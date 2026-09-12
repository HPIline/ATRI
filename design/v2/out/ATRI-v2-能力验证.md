# ATRI-v2能力验证审查

没有真机日志的项目不写成实测通过。

| ID | 项目 | 判定 | 门禁 | 依据 |
|---|---|---|---|---|
| envelope | 赛规包络 | CONDITIONAL | G3 | 实际CAD包络见assembly-snapshot.json；比赛测量姿态与口径尚待书面确认。 |
| dof | 关节数 | CONDITIONAL | G3 | 模型20个revolute；双腿4+4、双臂4+4、躯干2、头2；夹爪是否计入上肢待赛方确认。 |
| offline | 自主脱线 | NOT_TESTED | G6 | 旧软件有离线路径；Pi4B与本20DOF机构尚未完成整机联调。 |
| sensors | IMU/相机/麦/喇叭 | NOT_TESTED | G6 | 已选USB相机；BOM中的IMU和音频件完整型号、安装及实机性能未闭合。 |
| T-01 | 人脸检测与语音 | CONDITIONAL | G6 | 现软件有Mock/OpenCV检测路径，不能等同身份识别或姓名识别；Pi4B实际帧率、光照与音频待测。 |
| T-02 | 二维码指令行走 | CONDITIONAL | G4,G6,G7 | QR与任务卡已有旧软件路径；无hip_yaw转向尚待G4。失败需重新评审，不能自动加yaw或改现机配置。 |
| T-03 | 物品搬运 | CONDITIONAL | G1,G7 | 夹爪几何与关节已建；抓力、物体对准、支撑稳定和重复成功率尚未测量。 |
| T-04 | 踢球 | CONDITIONAL | G1,G7 | 单脚支撑、CoP及动态踝扭矩未验证；不以堵转扭矩替代连续额定值。 |
| T-05 | 舞蹈/语音 | CONDITIONAL | G6,G7 | 旧动作库不构成本机构的可执行证明，需重新做限位、线束和支撑检查。 |
| walk-torque | 双足行走力矩 | CONDITIONAL | G1,G2 | 仅在2300g目标质量和k=1.4假设下符合85%利用率；当前质量账未闭合，k=2保持仍超额定。 |
| structure | 结构静强度 | NOT_TESTED | G2 | 旧双大板的屈曲/弯曲简算不适用于新的开放框架。当前无整体FEA、夹具滑移/蠕变或跌落试验。 |
| runtime | 续航 | CONDITIONAL | G5 | 3S2200mAh标称约24.4Wh；实际负载、稳压效率与保护阈值待测，不承诺连续行走时间。 |
| bus | STS总线与现软件 | CONDITIONAL | G4,G5 | 协议同族；20关节映射、分电电流、线束温升和同步冲击未验证。现机config.py保持22DOF。 |

G4之前不得修改现机22DOF软件或恢复hip_yaw。所有结构与采购更改继续受A路线预算、质量和门禁约束。
