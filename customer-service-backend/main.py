# itwwy/main.py

"""
启动uvicorn
"""
import uvicorn

from conf.config import settings

if __name__ == '__main__':
    # 应用实例统一在 api/app.py 中组装（含 lifespan 数据库初始化 + chat_router 路由）
    # 这里只负责启动，不要再创建第二个 FastAPI 实例
    uvicorn.run(
        app="api.app:app",
        host=settings.app_host,
        port=settings.app_port
    )