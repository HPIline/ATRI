"""五项赛题技能库。

``DEFAULT_SKILLS`` 是技能注册表的唯一事实源：Brain 按它实例化技能，
任务卡的 VALID_SKILLS 也由它派生，避免校验层与运行层漂移。
"""
from .base import Skill, SkillContext
from .carry import CarrySkill
from .dance import DanceSkill
from .face import FaceSkill
from .kick import KickSkill
from .qr import QRCodeSkill

DEFAULT_SKILLS = {
    FaceSkill.name: FaceSkill,
    QRCodeSkill.name: QRCodeSkill,
    CarrySkill.name: CarrySkill,
    KickSkill.name: KickSkill,
    DanceSkill.name: DanceSkill,
}

SKILL_NAMES = frozenset(DEFAULT_SKILLS)

__all__ = [
    "Skill",
    "SkillContext",
    "DEFAULT_SKILLS",
    "SKILL_NAMES",
    "FaceSkill",
    "QRCodeSkill",
    "CarrySkill",
    "KickSkill",
    "DanceSkill",
]
