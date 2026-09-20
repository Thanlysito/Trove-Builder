from django.urls import path
from . import views

app_name = "builder"

urlpatterns = [
    path("", views.build_list, name="build_list"),
    path("new/", views.build_create, name="build_create"),
    path("my-builds/", views.my_builds, name="my_builds"),
    path("favoritas/", views.my_favorites, name="my_favorites"),
    path("como-funciona/", views.how_it_works, name="how_it_works"),
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("sitemap.xml", views.sitemap_xml, name="sitemap_xml"),
    path("clases/", views.class_list, name="class_list"),
    path("clases/<slug:class_slug>/", views.class_detail, name="class_detail"),
    path("notificaciones/", views.notifications_view, name="notifications"),
    path("sugerencias/", views.suggestions_view, name="suggestions"),
    path("usuario/<str:username>/", views.user_profile, name="user_profile"),
    path("comment/<int:comment_id>/delete/", views.build_delete_comment, name="build_delete_comment"),
    path("<slug:slug>/vote/", views.build_vote, name="build_vote"),
    path("<slug:slug>/favorite/", views.build_favorite_toggle, name="build_favorite_toggle"),
    path("<slug:slug>/delete/", views.build_delete, name="build_delete"),
    path("<slug:slug>/edit/", views.build_edit, name="build_edit"),
    path("<slug:slug>/duplicate/", views.build_duplicate, name="build_duplicate"),
    path("<slug:slug>/comment/", views.build_add_comment, name="build_add_comment"),
    path("<slug:slug>/", views.build_detail, name="build_detail"),
]
