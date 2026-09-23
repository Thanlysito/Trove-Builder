from django.contrib import admin
from .models import (
    GameClass, Gem, Build, BuildGem, BuildVote, EquipmentSlot, BuildEquipment,
    Subclass, Dragon, RingHiddenEffect, BuildComment, BuildFavorite, Notification, Suggestion,
    EquipmentItem, GameVersion, BuildRevision,
)


@admin.register(GameVersion)
class GameVersionAdmin(admin.ModelAdmin):
    list_display = ("name", "released_on", "is_current", "build_count")
    list_filter = ("is_current",)
    search_fields = ("name",)
    filter_horizontal = ("affected_classes",)
    actions = ["publish_version"]

    def save_model(self, request, obj, form, change):
        # Si en este guardado se marco "is_current", se publica despues de
        # guardar las clases afectadas (save_related), no antes.
        request._publish_version_after_save = "is_current" in form.changed_data and obj.is_current
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if getattr(request, "_publish_version_after_save", False):
            flagged = form.instance.publish()
            self.message_user(
                request,
                f"{form.instance.name} es ahora la versión actual. "
                f"{flagged} build(s) quedaron para revisar y sus autores fueron notificados.",
            )

    @admin.action(description="Publicar como versión actual (marca builds afectadas)")
    def publish_version(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Elige exactamente una versión.", level="error")
            return
        version = queryset.first()
        flagged = version.publish()
        self.message_user(
            request,
            f"{version.name} es ahora la versión actual. "
            f"{flagged} build(s) quedaron para revisar y sus autores fueron notificados.",
        )

    @admin.display(description="Builds atadas")
    def build_count(self, obj):
        return obj.builds.count()


@admin.register(GameClass)
class GameClassAdmin(admin.ModelAdmin):
    list_display = ("name", "primary_role", "damage_type")
    list_filter = ("primary_role", "damage_type")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Gem)
class GemAdmin(admin.ModelAdmin):
    list_display = ("name", "gem_type", "element", "damage_variant", "max_rank", "restricted_to_class")
    list_filter = ("gem_type", "element", "damage_variant", "restricted_to_class")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


class BuildGemInline(admin.TabularInline):
    model = BuildGem
    extra = 1


class BuildEquipmentInline(admin.TabularInline):
    model = BuildEquipment
    extra = 1


class BuildRevisionInline(admin.TabularInline):
    model = BuildRevision
    extra = 0
    can_delete = False
    fields = ("number", "game_version", "author", "created_at")
    readonly_fields = fields
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(BuildRevision)
class BuildRevisionAdmin(admin.ModelAdmin):
    list_display = ("build", "number", "game_version", "author", "created_at")
    list_filter = ("game_version",)
    search_fields = ("build__name",)
    readonly_fields = ("build", "number", "game_version", "author", "data", "created_at")


class BuildCommentInline(admin.TabularInline):
    model = BuildComment
    extra = 0
    readonly_fields = ("user", "text", "created_at")
    can_delete = True


@admin.register(Build)
class BuildAdmin(admin.ModelAdmin):
    list_display = (
        "name", "owner", "primary_class", "is_public", "status", "game_version",
        "language", "vote_score", "comment_count", "created_at",
    )
    list_filter = ("is_public", "status", "game_version", "language", "primary_class", "tags", "created_at")
    search_fields = ("name", "owner__username", "description")
    date_hierarchy = "created_at"
    list_per_page = 50
    prepopulated_fields = {"slug": ("name",)}
    raw_id_fields = ("remixed_from",)
    inlines = [BuildGemInline, BuildEquipmentInline, BuildRevisionInline, BuildCommentInline]

    @admin.display(description="Score")
    def vote_score(self, obj):
        return obj.score

    @admin.display(description="Comentarios")
    def comment_count(self, obj):
        return obj.comments.count()


@admin.register(EquipmentSlot)
class EquipmentSlotAdmin(admin.ModelAdmin):
    list_display = ("slot_type", "tier", "fixed_stats")
    list_filter = ("slot_type", "tier")


@admin.register(Subclass)
class SubclassAdmin(admin.ModelAdmin):
    list_display = ("name", "game_class", "bonus_stat", "bonus_range")
    list_filter = ("game_class",)
    search_fields = ("name", "game_class__name")


@admin.register(Dragon)
class DragonAdmin(admin.ModelAdmin):
    list_display = ("name", "dragon_type", "power_rank_bonus")
    list_filter = ("dragon_type",)
    search_fields = ("name",)


@admin.register(RingHiddenEffect)
class RingHiddenEffectAdmin(admin.ModelAdmin):
    list_display = ("name", "game_class", "availability")
    list_filter = ("game_class", "availability")
    search_fields = ("name",)


@admin.register(BuildVote)
class BuildVoteAdmin(admin.ModelAdmin):
    list_display = ("build", "user", "value", "created_at")
    list_filter = ("value", "created_at")
    search_fields = ("build__name", "user__username")
    date_hierarchy = "created_at"


@admin.register(BuildComment)
class BuildCommentAdmin(admin.ModelAdmin):
    list_display = ("build", "user", "text_preview", "created_at")
    list_filter = ("created_at",)
    search_fields = ("text", "user__username", "build__name")
    date_hierarchy = "created_at"

    @admin.display(description="Comentario")
    def text_preview(self, obj):
        return obj.text[:60] + ("…" if len(obj.text) > 60 else "")


@admin.register(BuildFavorite)
class BuildFavoriteAdmin(admin.ModelAdmin):
    list_display = ("build", "user", "created_at")
    search_fields = ("build__name", "user__username")
    date_hierarchy = "created_at"


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "actor", "verb", "build", "is_read", "created_at")
    list_filter = ("verb", "is_read", "created_at")
    search_fields = ("recipient__username", "actor__username", "build__name")
    date_hierarchy = "created_at"


@admin.register(EquipmentItem)
class EquipmentItemAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "category", "mastery", "power_rank", "tradable", "synced_at")
    list_filter = ("kind", "category", "tradable")
    search_fields = ("name", "description", "source_path")


@admin.register(Suggestion)
class SuggestionAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "category", "status", "created_at")
    list_filter = ("category", "status", "created_at")
    search_fields = ("title", "description", "user__username")
    date_hierarchy = "created_at"
    list_editable = ("status",)
    readonly_fields = ("user", "category", "title", "description", "created_at")
    fields = ("user", "category", "title", "description", "status", "created_at")


