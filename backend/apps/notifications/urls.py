"""Routes de l'application Notifications.

Voir docs/Documentation-API/03-reference-api.md section 9.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("notifications/", views.NotificationListView.as_view(), name="notifications-list"),
    path(
        "notifications/unread-count/",
        views.UnreadCountView.as_view(),
        name="notifications-unread-count",
    ),
    path(
        "notifications/read-all/",
        views.MarkAllReadView.as_view(),
        name="notifications-read-all",
    ),
    path(
        "notifications/<int:pk>/read/",
        views.MarkReadView.as_view(),
        name="notifications-read",
    ),
]
