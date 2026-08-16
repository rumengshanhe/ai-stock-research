"""启动入口：自动把项目内 vendor 目录加入 sys.path，无需全局安装依赖。

用法:  python run.py     （默认 http://127.0.0.1:8000）
"""
import os
import sys

# 绕过 Windows 注册表系统代理：部分代理会拦截东财数据接口导致 ProxyError。
# 对本机直连数据源无副作用；如需走代理请注释掉这两行。
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

ROOT = os.path.dirname(os.path.abspath(__file__))
# libs/: 随仓库提交的补丁版 pandas_ta（PyPI 已无 py3.10 兼容版本）
# vendor/: 本地开发时的完整依赖目录（gitignored，云端用 pip install）
VENDOR = os.path.join(ROOT, "vendor")
LIBS = os.path.join(ROOT, "libs")
for p in (VENDOR, LIBS, ROOT):
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

from app.config import settings  # noqa: E402

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)
