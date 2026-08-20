# -*- coding: utf-8 -*-
"""helper 测试公共配置：把插件根目录 + plugins 目录注入 sys.path，使包可导入。"""
import os
import sys

_PROJECT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_PLUGINS_DIR = os.path.join(_PROJECT_ROOT, "..")

for p in (_PROJECT_ROOT, _PLUGINS_DIR):
    p = os.path.abspath(p)
    if p not in sys.path:
        sys.path.insert(0, p)
