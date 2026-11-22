"""API 라우터 모음."""

from app.api.routes import (
    admin,
    chat,
    conversations,
    events,
    health,
    marketing,
    notes,
    personas,
    sessions,
    share,
    story,
    story_chat,
)

routers = [
    health.router,
    personas.router,
    sessions.router,
    conversations.router,
    chat.router,
    notes.router,
    story.router,
    story_chat.router,
    marketing.router,
    share.router,
    events.router,
    admin.router,
]

__all__ = ["routers"]
