from django.contrib import admin
from .models import (
    GameClass, Gem, Build, BuildGem, BuildVote, EquipmentSlot, BuildEquipment,
    Subclass, Dragon, RingHiddenEffect, BuildComment
)


@admin.register(GameClass)
class GameClassAdmin(admin.ModelAdmin):
    list_display = ("name", "primary_role")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Gem)
class GemAdmin(admin.ModelAdmin):
    list_display = ("name", "gem_type", "element", "damage_variant", "max_rank", "restricted_to_class")
    list_filter = ("gem_type", "element", "damage_variant", "restricted_to_class")
    prepopulated_fields = {"slug": ("name",)}


class BuildGemInline(admin.TabularInline):
    model = BuildGem
    extra = 1


class BuildEquipmentInline(admin.TabularInline):
    model = BuildEquipment
    extra = 1


@admin.register(Build)
class BuildAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "primary_class", "secondary_class", "subclass", "is_public", "created_at")
    list_filter = ("is_public", "primary_class", "tags")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [BuildGemInline, BuildEquipmentInline]


@admin.register(EquipmentSlot)
class EquipmentSlotAdmin(admin.ModelAdmin):
    list_display = ("slot_type", "tier", "fixed_stats")
    list_filter = ("slot_type", "tier")


@admin.register(Subclass)
class SubclassAdmin(admin.ModelAdmin):
    list_display = ("name", "game_class", "bonus_stat", "bonus_range")
    list_filter = ("game_class",)


@admin.register(Dragon)
class DragonAdmin(admin.ModelAdmin):
    list_display = ("name", "dragon_type", "power_rank_bonus")
    list_filter = ("dragon_type",)


@admin.register(RingHiddenEffect)
class RingHiddenEffectAdmin(admin.ModelAdmin):
    list_display = ("name", "game_class", "availability")
    list_filter = ("game_class", "availability")


@admin.register(BuildVote)
class BuildVoteAdmin(admin.ModelAdmin):
    list_display = ("build", "user", "value", "created_at")


@admin.register(BuildComment)
class BuildCommentAdmin(admin.ModelAdmin):
    list_display = ("build", "user", "created_at")
    list_filter = ("build",)
