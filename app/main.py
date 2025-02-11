import uvicorn
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from app.core.application import create_application
from app.api.routes import router
from app.config.settings import settings

# 创建FastAPI应用
app = create_application()

# 添加session中间件
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET_KEY,
    max_age=settings.SESSION_MAX_AGE,
    same_site=settings.SESSION_COOKIE_SAMESITE,
    https_only=settings.SESSION_COOKIE_SECURE,
)

# 注册路由
app.include_router(router)

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8087,
        reload=settings.ENV == "development",  # 只在开发环境启用自动重载
        reload_dirs=["app"],  # 只监控app目录
        reload_excludes=["*.pyc", "*.pyo", "*.log"],  # 排除这些文件
        log_level="info",  # 显示详细日志，包括监控信息
    )
