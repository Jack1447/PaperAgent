#!/usr/bin/env python3
"""
PaperAgent — 多智能体论文检索与阅读工作台

Usage:
    python app.py          # 启动 Web 服务 (FastAPI + 自定义前端)
    python app.py --help   # 查看帮助
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from web.main import main

if __name__ == "__main__":
    main()
