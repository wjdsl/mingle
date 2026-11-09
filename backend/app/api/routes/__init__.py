"""API 라우터 모음."""

from app.api.routes import (
    admin,
    chat,
    conversations,
    health,
    marketing,
    notes,
    personas,
    sessions,
    share,
    story,
)

routers = [
    health.router,
    personas.router,
    sessions.router,
    conversations.router,
    chat.router,
    notes.router,
    story.router,
    marketing.router,
    share.router,
    admin.router,
]

__all__ = ["routers"]
