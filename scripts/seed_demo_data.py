"""Thin wrapper that delegates to backend/scripts/seed_demo_data.py.

T0-2: 项目只有一套 demo seed 实现（backend/scripts/seed_demo_data.py，
账号 demo / demo123456），根目录脚本仅做转发，方便从项目根目录执行。
"""
import runpy
from pathlib import Path

target = (
    Path(__file__).resolve().parent.parent
    / "backend"
    / "scripts"
    / "seed_demo_data.py"
)
runpy.run_path(str(target), run_name="__main__")
