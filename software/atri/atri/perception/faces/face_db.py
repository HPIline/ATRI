"""人脸注册库：特征向量的持久化与比对。

设计要点：

1. **schema 版本化**。库文件里写死 ``schema_version`` / ``embedder`` / ``dim``，
   加载时不匹配就报错。理由：换个 embedder 后旧向量和新的根本不在同一空间，
   静默继续用会得到"看起来很合理"的错答案。
2. **只存向量，不存原图**。原图是生物特征的高敏形式，另行存放且不入库。
   但请注意：**向量本身也是生物特征**（可用于比对），不是脱敏数据。
3. **阈值来自实测**（见 tools/face_eval.py 的标定），不在这里拍脑袋给默认值；
   没有阈值就直接拒绝构造，逼调用方给出有出处的数字。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from ..base import PerceptionError

SCHEMA_VERSION = 1


@dataclass
class Person:
    name: str
    vectors: List[List[float]] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "vectors": self.vectors, "meta": self.meta}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Person":
        name = data.get("name")
        if not name:
            raise PerceptionError("注册项缺少 name")
        vectors = data.get("vectors") or []
        if not isinstance(vectors, list):
            raise PerceptionError(f"注册项 {name} 的 vectors 必须是列表")
        return cls(name=str(name), vectors=vectors, meta=dict(data.get("meta") or {}))


@dataclass
class MatchResult:
    """一次比对的结果。

    recognized=False 表示**拒识**：最高分没过阈值，或库是空的。
    拒识时 name 为 None —— 宁可说"不认识"，也不能报错名字。
    """

    name: Optional[str]
    similarity: float
    recognized: bool
    second_best_name: Optional[str] = None
    second_best_similarity: float = 0.0

    @property
    def margin(self) -> float:
        """最高分与次高分之差。margin 小说明库里有长相接近的人，结论不稳。"""
        return self.similarity - self.second_best_similarity

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "similarity": round(self.similarity, 4),
            "recognized": self.recognized,
            "margin": round(self.margin, 4),
        }


class FaceDB:
    """人脸特征库。"""

    def __init__(
        self,
        embedder: str,
        dim: int,
        threshold: float,
        people: Optional[List[Person]] = None,
        created_at: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        if dim <= 0:
            raise PerceptionError(f"dim 必须为正整数，收到 {dim}")
        if not (0.0 < threshold <= 1.0):
            raise PerceptionError(
                f"threshold 必须落在 (0, 1]，收到 {threshold}；"
                "阈值应由 tools/face_eval.py 标定得出，不要手填"
            )
        self.embedder = embedder
        self.dim = int(dim)
        self.threshold = float(threshold)
        self.people: List[Person] = list(people or [])
        self.created_at = created_at or datetime.now(timezone.utc).astimezone().isoformat(
            timespec="seconds"
        )
        self.meta = dict(meta or {})
        self._matrix_cache: Optional[np.ndarray] = None
        self._names_cache: List[str] = []

    # ---------- 持久化 ----------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "embedder": self.embedder,
            "dim": self.dim,
            "threshold": self.threshold,
            "created_at": self.created_at,
            "meta": self.meta,
            "people": [p.to_dict() for p in self.people],
        }

    def save(self, path: str | Path) -> str:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return str(target)

    @classmethod
    def load(cls, path: str | Path) -> "FaceDB":
        source = Path(path)
        if not source.exists():
            raise PerceptionError(f"人脸库不存在: {source}")
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PerceptionError(f"人脸库 JSON 解析失败: {exc}") from exc

        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise PerceptionError(
                f"人脸库 schema_version={version}，本代码只认 {SCHEMA_VERSION}。"
                "旧格式（4 维占位向量）无法用于识别，请用 tools/face_eval.py 重新生成"
            )
        dim = int(data.get("dim") or 0)
        db = cls(
            embedder=str(data.get("embedder") or ""),
            dim=dim,
            threshold=float(data.get("threshold") or 0.0),
            people=[Person.from_dict(p) for p in data.get("people") or []],
            created_at=data.get("created_at"),
            meta=data.get("meta"),
        )
        # 维度自检：向量长度对不上说明库是别的 embedder 生成的
        for person in db.people:
            for vec in person.vectors:
                if len(vec) != dim:
                    raise PerceptionError(
                        f"{person.name} 的向量长度 {len(vec)} ≠ 库声明的 dim {dim}"
                    )
        return db

    # ---------- 写入 ----------

    def enroll(self, name: str, vectors: List[Any], meta: Optional[Dict[str, Any]] = None) -> int:
        """登记一个人（可多人多次调用累积向量）。返回该人当前的向量总数。"""
        if not name:
            raise PerceptionError("name 不能为空")
        clean: List[List[float]] = []
        for vec in vectors:
            arr = np.asarray(vec, dtype=np.float32).reshape(-1)
            if arr.size != self.dim:
                raise PerceptionError(
                    f"向量维度 {arr.size} ≠ 库声明的 dim {self.dim}"
                )
            clean.append([float(v) for v in arr])
        if not clean:
            raise PerceptionError("vectors 为空，没有可登记的特征")

        for person in self.people:
            if person.name == name:
                person.vectors.extend(clean)
                if meta:
                    person.meta.update(meta)
                self._matrix_cache = None
                return len(person.vectors)

        self.people.append(Person(name=name, vectors=clean, meta=dict(meta or {})))
        self._matrix_cache = None
        return len(clean)

    # ---------- 比对 ----------

    @property
    def names(self) -> List[str]:
        return [p.name for p in self.people]

    def __len__(self) -> int:
        return sum(len(p.vectors) for p in self.people)

    def _matrix(self) -> np.ndarray:
        if self._matrix_cache is None:
            rows: List[List[float]] = []
            names: List[str] = []
            for person in self.people:
                for vec in person.vectors:
                    rows.append(vec)
                    names.append(person.name)
            self._matrix_cache = (
                np.asarray(rows, dtype=np.float32) if rows else np.zeros((0, self.dim), np.float32)
            )
            self._names_cache = names
        return self._matrix_cache

    def match(self, vector: Any) -> MatchResult:
        """与库中全部向量做余弦比对（向量已 L2 归一化，故等价于点积）。"""
        matrix = self._matrix()
        if matrix.shape[0] == 0:
            return MatchResult(name=None, similarity=0.0, recognized=False)

        query = np.asarray(vector, dtype=np.float32).reshape(-1)
        if query.size != self.dim:
            raise PerceptionError(f"查询向量维度 {query.size} ≠ 库声明的 dim {self.dim}")
        scores = matrix @ query

        best_idx = int(np.argmax(scores))
        best_name = self._names_cache[best_idx]
        best_score = float(scores[best_idx])

        second_name: Optional[str] = None
        second_score = 0.0
        order = np.argsort(scores)[::-1]
        for idx in order:
            if self._names_cache[int(idx)] != best_name:
                second_name = self._names_cache[int(idx)]
                second_score = float(scores[int(idx)])
                break

        return MatchResult(
            name=best_name if best_score >= self.threshold else None,
            similarity=best_score,
            recognized=best_score >= self.threshold,
            second_best_name=second_name,
            second_best_similarity=second_score,
        )

    def pair_scores(self, vec_a: Any, vec_b: Any) -> float:
        """两个向量的余弦相似度（评测标定用）。"""
        a = np.asarray(vec_a, dtype=np.float32).reshape(-1)
        b = np.asarray(vec_b, dtype=np.float32).reshape(-1)
        if a.size != b.size:
            raise PerceptionError(f"向量维度不一致: {a.size} vs {b.size}")
        return float(a @ b)
