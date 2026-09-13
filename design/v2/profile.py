"""ATRI-v2 A 路线冻结参数。改这里 = 改图纸、BOM、力矩账。"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

SCHEMA = "atri-v2-a-route-2026-09-12"

# SO-ARM100 STEP native shaft position, measured from cylindrical B-rep faces.
# Canonical servo coordinates must be shaft-centred before axis orientation.
CAD_INTERFACE = {"vendor_shaft_x_mm": 12.5, "housing_clock_deg": {"left_shoulder_roll":90.0,"right_shoulder_roll":90.0,"trunk_pitch":180.0},
                 "joint_axis_overrides":{"right_shoulder_pitch":(0.,-1.,0.)},
                 "vendor_accessory_cut_radius_mm": 10.05,
                 "vendor_drive_body_face_mm": 14.4,
                 "vendor_passive_body_face_mm": -14.4,
                 "vendor_cut_extent_mm": 25.0,
                 "drive_hub_inner_y_mm": 14.7,
                 "passive_outer_y_mm": -17.7,
                 "limb_front_plate_y_mm": 19.95,
                 "limb_rear_plate_y_mm": -18.45,
                 "idle_plate_w_mm": 40.0, "idle_plate_h_mm": 32.0,
                 "idle_connector_notch_x_mm": -10.5, "idle_connector_notch_half_h_mm": 10.5}

CASE_MOUNT = {
    'plate_t_mm': 1.5, 'x_span_mm': (-37.,-25.), 'height_mm':38.,
    'bolt_x_mm':-31., 'bolt_z_mm':(-15.,15.), 'hole_mm':3.2,
    'front_face_mm':17., 'rear_face_mm':-17.7, 'bolt_length_mm':45.,
    'qualification':'External clamp: slip, housing distortion and creep require G2 sample',
}

# Revision: open pelvis. Nominal body / shaft offset from STS3215 drawing p6;
# face datums/PCD from supplied mating records, still require C018 sample fit.
PELVIS = {
    "frame_t_mm": 1.5,
    "frame_pad_r_mm": 5.0,
    "frame_web_mm": 8.0,
    "frame_washer_mm": 0.5,
    "frame_standoff_mm": 5.0,
    "frame_bolt_mm": 50.0,
    "frame_top_from_trunk_mm": 10.5,
    "case_spacer_mm": 2.5,
    "rear_face_mm": -17.7,
    "stub_length_mm": 4.1,
    "front_horn_inner_mm": 16.7,
    "horn_t_mm": 2.5,
    "adapter_t_mm": 3.0,
    "adapter_angle_leg_mm": 40.0,
    "adapter_depth_leg_mm": 60.0,
    "adapter_output_half_height_mm": 10.0,
    "adapter_output_y_min_mm": -10.0,
    "adapter_web_mm": 12.0,
    "hip_output_pad_radius_mm": 10.0,
    "hip_output_neck_half_width_mm": 6.0,
    "hip_profile_radius_mm": 1.0,
    "hip_adapter_waypoint_xz_mm": (-12.0,-21.0),
    "trunk_adapter_web_mm": 18.0,
    "trunk_profile_radius_mm": 1.0,
    "trunk_adapter_waypoint_mm": (0.0,20.0),
    "adapter_inner_radius_mm": 3.0,
    "adapter_case_washer_mm": 0.5,
    "adapter_case_screw_mm": 8.0,
    "trunk_roll_z_mm": 18.0,
    "trunk_pitch_offset_mm": 25.0,
    "housing_clock_deg": {"left_hip_roll": 90.0, "right_hip_roll": 90.0, "trunk_roll": -90.0},
    "head_pitch_z_mm": 60.0,
    "mount_screw_mm": 8.0,
    "washer_t_mm": 1.0,
    "mount_thread_engagement_mm": 2.0,
    "mount_interface_status": "sample_fit_required",
}

# Purchased electronics: board versions and mechanical evidence travel together.
ELECTRONICS = {
    "bus_adapter":{"sku":"Waveshare-25514-Bus-Servo-Adapter-A", "pcb_mm":(42.,33.,1.6),
                   "position_mm":(36.,0.,69.6), "clock_deg":90.,
                   "hole_pitch_mm":(37.,28.), "hole_d_mm":2.5,
                   "source":"https://www.waveshare.com/wiki/Bus_Servo_Adapter_(A)"},
    "regulator":{"sku":"DFRobot-DFR0831", "envelope_mm":(43.5,20.3,5.5),
                 "position_mm":(33.,40.,65.15),
                 "input_v":(7.,24.), "output_v":5., "rated_range_a":(0.,4.),
                 "price_cny":20., "source":"https://wiki.dfrobot.com/dfr0831/",
                 "qualification":"3 A continuous thermal test required; do not treat 5 A cooling-dependent peak as normal rating"},
    "camera": {"sku": "Waveshare-33122-OV2735-A", "pcb_mm": (25.,25.,1.6),
               "hole_pitch_mm":21., "hole_d_mm":2., "lens_d_mm":14.,
               "lens_front_mm":16., "total_depth_mm":22.1,
               "position_mm":(20.,0.,28.), "source":"out/reference/OV2735-source.json"},
    "sbc": {"sku":"Raspberry-Pi-4B-2GB", "pcb_mm":(85.,56.,1.6),
            "mass_g":52., "position_mm":(-54.8,-12.5,38.),
            "hole_xy_mm":((3.5,3.5),(61.5,3.5),(61.5,52.5),(3.5,52.5)),
            "hole_d_mm":2.7,
            "mounting_status":"Pi4 official mechanical drawing: 85x56, pitch58x49, holes2.7; mass52g is an allocation"},
    "battery": {"sku":"Gens-Ace-GEA223S25T3GT", "body_mm":(33.,107.,22.),
                "design_clearance_mm":(2.,5.,2.), "position_mm":(34.,0.,42.),
                "mass_g":169., "mass_reserve_g":20.,
                "lead_reserve_mm":120., "balance_lead_reserve_mm":65.,
                "connector":"EC3 with supplied XT60 adapter; reserve adapter space separately"},
}

HEAD = {
    "bounds_mm": (6.5,-23.9,12.7,35.,23.9,44.5),
    "wall_mm":2.4, "seam_x_mm":23., "seam_gap_mm":0.25,
    "lens_hole_mm":16.4, "mount_xz_mm":(20.,18.),
    "front_arm_y_mm":19.95, "rear_arm_y_mm":-18.45,
    "arm_t_mm":1.5, "arm_web_mm":9.,
    "outer_corner_r_mm": 2., "boolean_margin_mm": 1.,
    "usb_slot_xy_mm": (9., 8.), "usb_slot_x_offset_mm": -3.,
    "arm_slot_width_mm": 1.9, "arm_slot_depth_extra_mm": 1.3,
    "arm_bottom_slot_end_mm": 7., "arm_bottom_slot_center_end_mm": 5.,
    "arm_rear_slot_end_mm": 8., "arm_rear_slot_center_end_mm": 6.,
    "mount_boss_r_mm": 4., "mount_hole_d_mm": 3.2,
    "camera_clear_d_mm": 2.2,
    "closure_y_mm": (-18., 18.), "closure_z_mm": 40.,
    "closure_tube_r_mm": 3.7, "closure_clear_d_mm": 2.2,
    "closure_pocket_af_mm": 3.7, "closure_pocket_length_mm": 5.2,
    "closure_pocket_x_offset_mm": -7.6,
    "closure_access_xyz_mm": (5.2, 5., 4.3),
    "closure_access_x_offset_mm": -5., "closure_access_y_offset_mm": 2.5,
    "closure_pillar_af_mm": 3.5, "closure_pillar_length_mm": 5.,
    "closure_pillar_x_offset_mm": -7.5, "closure_retaining_lip_mm": 2.4,
    "closure_screw_length_mm": 20.,
    "tongue_y_mm": (-14., 14.), "tongue_xyz_mm": (2.5, 4., .8),
    "tongue_x_offset_mm": .25, "tongue_z_offset_mm": 2.,
    "tongue_pocket_xyz_mm": (2.7, 4.2, 1.), "tongue_pocket_x_offset_mm": .35,
    "arm_start_xz_mm": ((-9.5,-8.), (-8.5,-9.), (10.,-9.)),
    "arm_end_xz_mm": ((-8.5,9.), (-9.5,8.)),
    "arm_mount_offsets_xz_mm": ((5.,-5.), (5.,5.), (-5.,5.)),
    "arm_center_d_mm": {"front": 6.4, "rear": 8.},
    "al_material": "6061-T6",
    "m2_shank_d_mm": 2., "m2_head_d_mm": 3.8, "m2_head_h_mm": 2.,
    "m2_socket_af_mm": 1.5, "m2_socket_depth_mm": 1.2, "m2_socket_offset_mm": .8,
    "m2_thread_bore_d_mm": 1.6,
    "mount_screw_length_mm": 10., "mount_nut_af_mm": 5.5,
    "mount_nut_h_mm": 2.4, "mount_nut_bore_d_mm": 2.5,
    "passive_screw_length_mm": 4.,
    "camera_pillar_od_mm": 3.5, "camera_pillar_length_mm": 5.,
    "camera_screw_length_mm": 8., "camera_rear_screw_length_mm": 4.,
}

NECK = {
    'base_t_mm':2., 'base_x_mm':(-42.,10.), 'base_y_mm':(-21.,21.),
    'base_z_mm':19.2, 'angle_leg_mm':15., 'angle_t_mm':1.5,
    'angle_inner_r_mm':1.5, 'csk_socket_af_mm':2., 'csk_socket_depth_mm':1.1,
    'angle_length_mm':12., 'angle_hole_z_mm':8., 'angle_hole_offset_mm':6.,
    'base_screw_mm':8., 'side_screw_mm':8., 'bolt_clear_mm':3.2,
    'csk_head_mm':6., 'csk_depth_mm':1.7,
}

LEG = {
    'plate_t_mm':1.5, 'web_mm':12., 'pad_r_mm':5., 'output_r_mm':10.,
    'front_inner_mm':(20.2,26.2,33.2), 'rear_inner_mm':(-19.2,-25.2,-32.2),
    'horn_bolt_mm':(5.,12.,18.), 'clamp_bolt_mm':(45.,60.),
    'clamp_head_washer_mm':(0.,2.), 'foot_height_mm':44.,
    'foot_angle_leg_mm':15., 'foot_angle_length_mm':20., 'foot_angle_t_mm':1.5,
    'foot_angle_hole_x_mm':(-6.,6.), 'foot_angle_inner_r_mm':1.5,
    'foot_angle_vertical_hole_mm':9., 'foot_angle_horizontal_hole_mm':9.,
    'foot_plate_t_mm':3., 'foot_edge_r_mm':8.,
    'spacer_lengths_mm':(10.,6.,5.,3.,2.,1.,.5,.2),
    'foot_lightening_x_ranges_mm':((-32.,-12.),(12.,68.)),
    'foot_lightening_y_mm':(-18.,18.), 'foot_lightening_width_mm':18.,
    'foot_lightening_radius_mm':4.,
    'thigh_rear_web_waypoint_mm':(10.,-22.),
}

ARM = {
    'angle_t_mm':3., 'web_mm':9., 'output_radius_mm':10.,
    'output_front_mm':19.2, 'clip_extent_mm':300.,
    'center_d_mm':8., 'horn_bolt_mm':6., 'inside_r_mm':3.,
    'upper_bridge_drop_mm':22., 'shoulder_offset_mm':44.,
    'output_spacer_mm':{'shoulder':5.,'upper':0.,'fore':13.},
    'fore_spacer_stack_mm':(10.,3.),
    'fore_bridge_drop_mm':46., 'fore_output_waypoint_yz_mm':(-30.,28.),
    'spaced_bolt_base_mm':5., 'spacer_od_mm':5.,
    'finger_t_mm':2., 'finger_length_mm':55.,
    'finger_mount_x_mm':25., 'finger_width_mm':6.,
    'moving_finger_x_mm':30.2,
    'finger_case_bolt_y_mm':31., 'finger_case_bolt_z_mm':(-15.,-36.),
    'finger_aux_bolt_mm':16.,
    'finger_bridge_z_mm':-26., 'fixed_finger_y_mm':-18.,
    'moving_finger_tip_y_mm':-4., 'finger_mount_web_mm':9.,
    'finger_center_d_mm':6.4, 'finger_bolt_mm':16.,
    'finger_spacer_stack_mm':(10.,1.), 'fixed_spacer_face_mm':20.,
    'fixed_spacer_od_mm':6., 'fixed_bolt_mm':50.,
    'pad_y_mm':{'fixed':-14.,'moving':-4.},
    'pad_height_mm':{'fixed':24.,'moving':24.}, 'pad_t_mm':2.,
    'pad_support_stack_mm':(2.,3.), 'pad_support_hole_z_mm':(-49.,-37.),
    'pad_support_hole_mm':2.2, 'pad_support_bolt_mm':10.,
    'material':'6061-T6',
    'stock_equal_leg_mm':(40.,50.,60.,75.,80.,100.),
    'fore_csk_bolt_mm':20., 'csk_head_d_mm':6., 'csk_depth_mm':1.5,
    'button_head_d_mm':5.7, 'button_head_h_mm':1.65,
    'button_socket_af_mm':2., 'button_socket_depth_mm':1.1,
    'button_edge_r_mm':.8,
    'nut_af_mm':5.5, 'nut_h_mm':2.4, 'nut_bore_mm':2.5,
    'shoulder_join_leg_mm':20., 'shoulder_join_length_mm':22.,
    'shoulder_join_hole_inset_mm':10., 'shoulder_join_hole_z_mm':(-5.,5.),
    'shoulder_join_pad_r_mm':5., 'shoulder_join_screw_mm':10.,
    'right_shoulder_spacer_mm':15., 'fore_jaw_long_end_mm':36.,
}

TORSO = {
    'plate_t_mm':1.5, 'front_inner_mm':22.2, 'rear_inner_mm':-21.2,
    'web_mm':12., 'output_radius_mm':10., 'beam_x_mm':-31.,
    'beam_z_offsets_mm':(-15.,15.), 'beam_width_mm':20.,
    'beam_height_mm':10., 'beam_wall_mm':1., 'rod_length_mm':196.,
    'head_clamp_width_mm':20., 'head_clamp_bolt_x_offsets_mm':(-5.,5.),
    'head_clamp_bolt_y_mm':(-15.,15.), 'head_clamp_bolt_mm':55.,
    'head_mount_gap_mm':2.8,
    'sbc_rail_width_mm':8.6, 'sbc_carrier_rear_x_mm':-46.,
    'sbc_carrier_wall_mm':2.4, 'sbc_carrier_clearance_mm':.2,
    'sbc_post_mm':8., 'sbc_post_od_mm':5.,
    'sbc_board_screw_mm':5., 'sbc_carrier_screw_mm':6.,
    'sbc_beam_screw_mm':10., 'sbc_beam_clear_d_mm':3.2,
    'sbc_mount_clear_d_mm':2.7, 'sbc_rail_end_margin_mm':5.,
    'battery_side_y_mm':46., 'battery_bracket_x_mm':(-37.,54.),
    'battery_bracket_bottom_mm':16., 'battery_bracket_web_mm':10.,
    'battery_angle_holes_x_mm':(22.,46.), 'battery_angle_hole_z_mm':20.,
    'battery_angle_length_mm':40., 'battery_angle_leg_mm':15.,
    'battery_angle_t_mm':1.5, 'battery_angle_inner_r_mm':1.5,
    'battery_tray_bounds_mm':(15.,-62.,29.,55.,62.,31.),
    'battery_strap_y_mm':(-32.,32.), 'battery_strap_width_mm':10.,
    'battery_strap_thickness_mm':1., 'battery_strap_length_mm':150.,
    'battery_strap_overlap_mm':20.,
    'bus_bridge_x_mm':(18.,54.), 'bus_bridge_y_mm':(-63.3,63.3),
    'bus_bridge_z_mm':57.6, 'bus_bridge_t_mm':2.4,
    'bus_bridge_leg_x_mm':(22.,50.), 'bus_bridge_leg_width_mm':8.,
    'bus_bridge_foot_depth_mm':9.6, 'bus_bridge_foot_hole_y_mm':57.8,
    'bus_bridge_mount_screw_mm':8., 'bus_post_mm':8.,
    'bus_bridge_window_mm':(18.,26.),
    'bus_mount_d_mm':2., 'bus_mount_clear_mm':2.2,
    'bus_mount_head_d_mm':3.8, 'bus_mount_head_h_mm':2.,
    'bus_mount_socket_mm':1.5, 'bus_post_od_mm':4., 'bus_post_bore_mm':1.6,
    'regulator_cradle_clear_mm':.2, 'regulator_cradle_wall_mm':2.4,
    'regulator_lid_gap_mm':.4, 'regulator_lid_boss_y_offset_mm':15.3,
    'regulator_lid_boss_x_offsets_mm':(-21.,0.),
    'regulator_lid_boss_r_mm':4.8, 'regulator_nut_af_mm':4.,
    'regulator_nut_h_mm':1.6, 'regulator_nut_clear_mm':.2,
    'regulator_nut_z_mm':63., 'regulator_lid_screw_mm':8.,
    'regulator_vent_width_mm':3., 'regulator_vent_length_mm':14.,
    'regulator_vent_x_offsets_mm':(-14.,-7.,0.,7.,14.),
    'regulator_wire_slot_y_mm':10., 'regulator_wire_slot_h_mm':4.,
}

# —— 赛规（官方表，不含「单臂长」）——
CONTEST = {
    "height_max_mm": 600.0,
    "width_max_mm": 300.0,
    "depth_max_mm": 300.0,
    "dof_min": 18,
    "leg_dof_min": 4,
    "upper_torso_min": 10,  # 不含头，除非赛方书面确认
    "voltage_min_v": 7.4,
    "source": "西安交大实践教学中心通知 2026-08-18 PNG 技术要求表",
}

# —— 舵机（飞特 STS3215-C018 / 微雪 ST3215 12V）——
SERVO = {
    "model": "STS3215-C018",
    "body_mm": (45.22, 24.7, 35.0),  # 长 × 宽 × 沿轴厚；标签 A/B/C
    "mass_g": 55.0,
    "rated_nm": 0.98,  # 10 kg·cm
    "stall_nm": 2.94,  # 30 kg·cm
    "rated_a": 0.90,
    "stall_a": 2.7,
    "no_load_a": 0.18,
    "voltage_range_v": (4.0, 14.0),
    "speed_s_per_60deg": 0.222,
    "horn_spline": "25T",
    "horn_pcd_mm": 14.0,
    "horn_hole_square_mm": 9.90,  # 实测 9.90×9.90 → PCD 14.00
    "horn_hole_thread": "M3",
    "horn_clear_mm": 3.2,
    "horn_source": "Feetech ST-3215-C018 A/0 2023-07-20 p7",
    "horn_od_mm": 19.95,
    "horn_total_t_mm": 4.5,
    "horn_flange_t_mm": 2.5,
    "horn_hub_od_mm": 9.0,
    "horn_center_clear_mm": 3.2,
    "horn_spline_depth_mm": 3.6,
    "horn_spline_od_mm": 5.9,
    "output_spline_length_mm": 3.4,
    "rear_stub_length_mm": 4.1,
    "rear_disc_bore_mm": 6.05,
    "rear_disc_total_t_mm": 3.1,
    "rear_disc_flange_t_mm": 2.1,
    "rear_retainer_screw_mm":5., "rear_retainer_head_d_mm":5.6,
    "rear_retainer_head_h_mm":2.4, "rear_retainer_washer_od_mm":7.,
    "rear_retainer_washer_id_mm":3.2, "rear_retainer_washer_t_mm":.5,
    "rear_retainer_status":"PA3x5 from C018 p6; pan-head envelope and washer are sample-fit items",
    "boss_od_mm": 20.0,
    "idle_stub_mm": 6.0,
    "mass_note": "官方/标签 55±1 g",
}

# —— 默认 20 DOF：不赌「头计入上肢躯干」——
# 腿 4+4（暂砍 hip_yaw，G4 转向门禁）+ 臂 4+4 + 躯干 2 + 头 2
JOINTS: List[Dict[str, Any]] = [
    {"name": "head_yaw", "group": "head", "limit_deg": [-90, 90]},
    {"name": "head_pitch", "group": "head", "limit_deg": [-45, 45]},
    {"name": "trunk_roll", "group": "trunk", "limit_deg": [-10, 10]},
    {"name": "trunk_pitch", "group": "trunk", "limit_deg": [-15, 15]},
    {"name": "left_hip_roll", "group": "leg_l", "limit_deg": [0, 25]},
    {"name": "left_hip_pitch", "group": "leg_l", "limit_deg": [-60, 60]},
    {"name": "left_knee_pitch", "group": "leg_l", "limit_deg": [0, 90]},
    {"name": "left_ankle_pitch", "group": "leg_l", "limit_deg": [-40, 40]},
    {"name": "right_hip_roll", "group": "leg_r", "limit_deg": [-25, 0]},
    {"name": "right_hip_pitch", "group": "leg_r", "limit_deg": [-60, 60]},
    {"name": "right_knee_pitch", "group": "leg_r", "limit_deg": [0, 90]},
    {"name": "right_ankle_pitch", "group": "leg_r", "limit_deg": [-40, 40]},
    {"name": "left_shoulder_pitch", "group": "arm_l", "limit_deg": [-90, 90]},
    {"name": "left_shoulder_roll", "group": "arm_l", "limit_deg": [0, 90]},
    {"name": "left_elbow_pitch", "group": "arm_l", "limit_deg": [-120, 0]},
    {"name": "left_gripper", "group": "arm_l", "limit_deg": [0, 60]},
    {"name": "right_shoulder_pitch", "group": "arm_r", "limit_deg": [-90, 90]},
    {"name": "right_shoulder_roll", "group": "arm_r", "limit_deg": [-90, 0]},
    {"name": "right_elbow_pitch", "group": "arm_r", "limit_deg": [-120, 0]},
    {"name": "right_gripper", "group": "arm_r", "limit_deg": [0, 60]},
]

GROUP_DOF = {"head": 2, "trunk": 2, "leg_l": 4, "leg_r": 4, "arm_l": 4, "arm_r": 4}

# 相对现机 22 DOF 去掉的两条 yaw。软件 config.py 已按本表 20 DOF 对齐；转向占位是髋 roll，G4 仍开放。
DROPPED_VS_V1 = ("left_hip_yaw", "right_hip_yaw")

# —— 运动学（mm），站立零位，轴距 ——
K = {
    "foot_l": 120.0,
    "foot_w": 70.0,
    "ankle_from_heel": 42.0,  # 足长 35%
    "foot_to_ankle_z": 44.0,
    "shank": 78.0,
    "thigh": 78.0,
    "hip_stack_z": 32.0,  # hip_roll 壳体 24.7 + 板
    "pelvis_to_shoulder_z": 88.0,
    "shoulder_to_head_yaw": 42.0,
    "head_yaw_to_crown": 104.5,  # head pitch axis 60 + shell crown 44.5
    "hip_width": 80.0,
    "shoulder_width": 150.0,
    "upper_arm": 58.0,
    "forearm": 60.0,
    "gripper": 38.0,
    "torso_depth": 92.0,
    "cover_half": 18.0,
    "sole_t": 2.0,
}


def standing_height_mm() -> float:
    return (
        K["foot_to_ankle_z"]
        + K["shank"]
        + K["thigh"]
        + K["hip_stack_z"]
        + K["pelvis_to_shoulder_z"]
        + K["shoulder_to_head_yaw"]
        + K["head_yaw_to_crown"]
    )


def envelope_mm() -> Dict[str, float]:
    width = max(K["shoulder_width"] + SERVO["body_mm"][2], K["hip_width"] + 70.0)
    depth = K["torso_depth"] + 2.0 * K["cover_half"]
    return {
        "height_mm": round(standing_height_mm(), 1),
        "width_mm": round(width, 1),
        "depth_mm": round(depth, 1),
    }


def dof_counts() -> Dict[str, int]:
    n = {g: 0 for g in GROUP_DOF}
    for j in JOINTS:
        n[j["group"]] += 1
    upper_torso = n["arm_l"] + n["arm_r"] + n["trunk"]  # 不含头
    return {
        "total": len(JOINTS),
        "leg_l": n["leg_l"],
        "leg_r": n["leg_r"],
        "upper_torso": upper_torso,
        "head": n["head"],
        "bus_servos": len(JOINTS),
    }


# —— 质量门（g）——
MASS = {
    "design_limit_g": 2300.0,
    "hard_limit_g": 2450.0,
    "servo_g": 20 * SERVO["mass_g"],
    "electronics_budget_g": 420.0,  # SBC+板+相机+IMU+麦喇+电池+线
    "structure_al_budget_g": 650.0,  # 骨盆夹层两片 120×160
    "petg_budget_g": 220.0,
    "tpu_budget_g": 40.0,
    "fastener_budget_g": 90.0,
    "foot_mass_above_offset_g": 85.0,  # 与现机踝公式同一偏置
}

MATERIALS = {
    "6061-T6": {"density_g_cm3": 2.70, "t_mm": 1.5, "foot_t_mm": 2.0},
    "PETG": {"density_g_cm3": 1.27},
    "TPU95A": {"density_g_cm3": 1.21},
}

# Webots 接触：脚底 TPU95A 对室内塑胶/PVC 地板（赛题未另指定地面）。
# μ 取工程表橡胶-木/橡胶-混凝土/轮胎-路面干态区间的中值，不是实验室测值。
CONTACT = {
    "foot_material": "TPU95A",
    "ground_material": "vinyl_floor",
    "other_material": "PETG",
    "mu_foot_ground": 0.70,
    "mu_other_ground": 0.35,
    "bounce": 0.0,
}

# 踝：τ = (m - m_foot) g r k ；r=25 mm 与现机 CoP 口径一致，禁止再乘安全系数
ANKLE = {
    "cop_m": 0.025,
    "k_walk": 1.4,  # 赛题无竞速；慢步
    "k_hold": 2.0,  # 现机站立保持口径
    "g": 9.81,
    "util_walk_max": 0.85,  # 慢步允许上限（仍要过 G1 温升）
}


def ankle_torque_nm(mass_g: float, k: float) -> float:
    m = (mass_g - MASS["foot_mass_above_offset_g"]) / 1000.0
    return m * ANKLE["g"] * ANKLE["cop_m"] * k


def scale_from_v1(v1_nm: float, v1_g: float, v2_g: float) -> float:
    return v1_nm * (v2_g / v1_g)


# 现机权威（main / 力矩口径模板 2026-09-12）
V1 = {
    "mass_g": 3036.0,
    "ankle_nm": 1.446,
    "knee_nm": 1.384,
    "hip_pitch_nm": 1.314,
    "hip_roll_nm": 1.268,
    "trunk_roll_nm": 0.442,  # 力臂口径订正后；禁止再用 1.899
}


def group_pairs() -> List[Tuple[str, str]]:
    return [(j["name"], j["group"]) for j in JOINTS]


TORSO_SHELL = dict(
    bounds_mm=(-76., -66., 25., 61., 66., 88.), wall_mm=2.4,
    seam_x_mm=-5., seam_gap_mm=.4,
    shoulder_window_xz_mm=(-42.,25.,14.,65.),
    yaw_window_xy_mm=(-40.,-23.,15.,23.),
    rear_window_yz_mm=(-58.,25.,38.,69.),
    front_vent_z_mm=(35.,43.,72.,80.),front_vent_length_mm=78.,front_vent_height_mm=4.,
    front_mount_y_mm=(-58.,58.),front_mount_z_mm=58.8,
    front_ear_start_x_mm=50., front_ear_width_mm=10., front_ear_height_mm=10.,
    rear_mount_z_mm=76.,rear_ear_width_mm=10.4,rear_ear_height_mm=10.,
    rear_ear_inner_x_mm=-43.6,rear_ear_web_x_mm=-46.,
    rear_web_bottom_z_mm=67.,
    nut_af_mm=5.5,nut_h_mm=2.4,nut_pocket_af_mm=5.8,
    nut_pocket_axial_mm=2.6,retaining_lip_mm=3.0,
    bolt_clear_mm=3.2,bolt_length_mm=8.,
)

# Diagnostic space reservation, NOT a qualified connector CAD model.
CONNECTOR_STUDY = {
    'body_xyz_mm':(3.4,5.6,8.), 'center_xy_mm':(-14.05,-22.2),
    'port_z_mm':(-5.2,5.2),
    'status':'Provisional mating-space probe only; dimensions not qualified by C018 connector drawing',
    'source':'C018 p6 specifies 5264/2.54 3P; older reference STEP has approximately 2.4 mm pin pitch. Full plug drawing and revision are unresolved.',
}

# Passive-side arm support candidate, pending full swept-volume qualification.
ARM_DUAL = {
    'shoulder_bridge_z_mm': -50.,
    'shoulder_output_route_mm': ((0.,0.),(-10.,-20.),(-10.,-50.),(20.,-50.)),
    'rear_outer_mm': -23.2,
    'rear_plate_t_mm': 3.,
    'rear_disc_spacer_stack_mm': (2., .5),
    'rear_head_washer_mm': .5,
    'rear_horn_bolt_mm': 8.,
    'rear_horn_thread_engagement_mm': 2.,
    'upper_bridge_drop_mm': 37.,
    'upper_route_y_mm': {'left':24., 'right':20.5},
    'upper_web_mm': {'left':9., 'right':6.},
    'upper_route_elbow_z_mm': -30.,
    'upper_route_bottom_z_mm': -95.,
    'lap_outer_y_mm': 23.,
    'case_bolt_mm':45.,
    'spacer_od_mm':5.,
    'hole_mm':3.2,
}

# Owner-authorized paired hip-roll support revision; assembly qualification open.
HIP_DUAL = {
    'plate_t_mm':3., 'web_mm':12., 'disc_pad_r_mm':10.,
    'rear_outer_x_mm':-26.2, 'side_outer_y_mm':-31.2,
    'pcd_spacer_stack_mm':(5.,.5), 'pcd_head_washer_mm':.5,
    'pcd_bolt_mm':12., 'case_spacer_mm':9., 'case_bolt_mm':55., 'case_seat_d_mm':7.4,
    'inside_radius_mm':3., 'centre_clear_mm':8.2,
}

# Waist roll rear support: paired with the active front angle on the moving link.
WAIST_DUAL = dict(plate_t_mm=3., rear_outer_x_mm=-26.2, side_outer_y_mm=-36.7,
    clamp_x_mm=31., clamp_z_mm=40., return_center_z_mm=35.,
    side_length_mm=62., side_center_x_mm=6., return_join_mm=6.,
    disc_pad_radius_mm=10., centre_clear_mm=8.2, end_radius_mm=5., return_width_mm=18., rear_web_mm=12., inside_radius_mm=3.,
    pcd_spacer_stack_mm=(5., .5), head_washer_mm=.5, pcd_bolt_mm=12.,
    clamp_spacer_stack_mm=(10., 4., .5), clamp_bolt_mm=60.)

# Additive second battery candidate; integration is explicit and requires electrical review.
SECOND_BATTERY = {'sku':'Gens-Ace-GEA223S25T3GT', 'body_mm':(33.,107.,22.), 'position_mm':(86.5,0.,42.), 'mass_g':169., 'tray_bounds_mm':(55.,-62.,29.,108.,62.,31.4), 'status':'candidate mechanical mount; fuse/ORing, charger and thermal validation required'}

BATTERY_EXPANSION = dict(center_mm=(86.5,0.,42.), tray_x_mm=(68.,108.),
    tray_y_mm=(-62.,62.), tray_z_mm=29., thickness_mm=2.,
    bridge_start_x_mm=50., bridge_y_mm=(-58.,58.), bridge_width_mm=8.,
    shell_clearance_mm=.6, strap_y_mm=(-32.,32.), strap_width_mm=10., strap_t_mm=1.)
