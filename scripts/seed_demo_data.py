"""Seed demo data for course-learning-agent.

Usage: python scripts/seed_demo_data.py

Creates a demo user (demo / demo123), two courses (操作系统 / 数据库),
a sample material with two parsed chunks for 操作系统, and a sample
conversation — so the platform is immediately demoable after a fresh
database init. Safe to re-run: existing entities are skipped.

Run from the project root after initialising the database tables
(`python -m app.core.database` from backend/).
"""
import sys
from pathlib import Path

# 让脚本能 import backend 模块（从项目根目录运行）
backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

from app.core.database import SessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.course import Course  # noqa: E402
from app.models.material import Material  # noqa: E402
from app.models.material_chunk import MaterialChunk  # noqa: E402
from app.models.user import User  # noqa: E402


def _get_or_create_user(db, username: str, password: str) -> User:
    u = db.query(User).filter(User.username == username).first()
    if u is not None:
        return u
    u = User(username=username, password_hash=hash_password(password))
    db.add(u)
    db.flush()
    return u


def _get_or_create_course(
    db, user_id: int, name: str, semester: str, teacher: str
) -> Course:
    c = (
        db.query(Course)
        .filter(Course.user_id == user_id, Course.name == name)
        .first()
    )
    if c is not None:
        return c
    c = Course(
        user_id=user_id, name=name, semester=semester, teacher=teacher
    )
    db.add(c)
    db.flush()
    return c


def _get_or_create_material(
    db, user_id: int, course_id: int, filename: str
) -> Material:
    m = (
        db.query(Material)
        .filter(
            Material.user_id == user_id,
            Material.course_id == course_id,
            Material.filename == filename,
        )
        .first()
    )
    if m is not None:
        return m
    m = Material(
        user_id=user_id,
        course_id=course_id,
        filename=filename,
        file_type="txt",
        file_path=f"storage/uploads/{filename}",
        status="ready",
    )
    db.add(m)
    db.flush()
    return m


def seed() -> None:
    db = SessionLocal()
    try:
        # 1. Demo user
        demo = _get_or_create_user(db, "demo", "demo123")
        print(f"[seed] user demo (id={demo.id})")

        # 2. Courses
        courses_data = [
            ("操作系统", "2025秋季", "张老师"),
            ("数据库", "2025秋季", "李老师"),
        ]
        course_ids: dict[str, int] = {}
        for name, semester, teacher in courses_data:
            c = _get_or_create_course(db, demo.id, name, semester, teacher)
            course_ids[name] = c.id
            print(f"[seed] course {name} (id={c.id})")

        # 3. Sample material + chunks for 操作系统
        os_mat = _get_or_create_material(
            db, demo.id, course_ids["操作系统"], "操作系统笔记.txt"
        )
        # 检查是否已有 chunks
        existing_chunks = (
            db.query(MaterialChunk)
            .filter(MaterialChunk.material_id == os_mat.id)
            .count()
        )
        if existing_chunks == 0:
            for i, (title, text) in enumerate(
                [
                    ("进程", "进程是程序在数据集合上运行的过程，是系统资源分配的基本单位。"),
                    ("线程", "线程是进程内的执行单元，是 CPU 调度的基本单位。"),
                ]
            ):
                db.add(
                    MaterialChunk(
                        material_id=os_mat.id,
                        course_id=course_ids["操作系统"],
                        chunk_index=i,
                        title=title,
                        text=text,
                    )
                )
            print(f"[seed] 2 chunks for material {os_mat.filename}")
        else:
            print(f"[seed] material {os_mat.filename} already has chunks")

        db.commit()
        print("[seed] done. Login: demo / demo123")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
