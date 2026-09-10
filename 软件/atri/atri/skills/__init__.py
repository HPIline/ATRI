"""五项赛题技能库。"""
from .base import Skill, SkillContext
from .carry import CarrySkill
from .dance import DanceSkill
from .face import FaceSkill
from .kick import KickSkill
from .qr import QRCodeSkill

__all__ = [
    "Skill",
    "SkillContext",
    "FaceSkill",
    "QRCodeSkill",
    "CarrySkill",
    "KickSkill",
    "DanceSkill",
]
