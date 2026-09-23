"""
Pruebas automáticas de Trove Builder.

Corre todo con:  python manage.py test builder
(o solo una clase: python manage.py test builder.tests.BuildVoteTests)

Estas pruebas usan una base de datos de prueba aparte que Django crea y
destruye solo — NUNCA tocan tu db.sqlite3 real.
"""

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils.text import slugify

from .models import (
    Build, BuildComment, BuildFavorite, BuildVote, GameClass,
)


class BaseBuilderTestCase(TestCase):
    """Crea un par de usuarios y una clase de juego, comunes a varias pruebas."""

    def setUp(self):
        cache.clear()  # el rate limiting usa el cache; que no se filtre entre pruebas
        self.owner = User.objects.create_user(username="owner", password="testpass123")
        self.other = User.objects.create_user(username="other", password="testpass123")
        self.game_class = GameClass.objects.create(
            name="Test Class", slug="test-class", primary_role="dps", damage_type="physical",
        )

    def make_build(self, owner=None, name="Build de prueba", is_public=True):
        owner = owner or self.owner
        return Build.objects.create(
            owner=owner,
            name=name,
            slug=slugify(name) + "-" + str(owner.id) + "-" + str(Build.objects.count()),
            primary_class=self.game_class,
            is_public=is_public,
        )


class BuildVoteTests(BaseBuilderTestCase):
    def test_vote_requires_login(self):
        build = self.make_build()
        response = self.client.post(reverse("builder:build_vote", args=[build.slug]), {"value": "1"})
        self.assertNotEqual(response.status_code, 200)  # redirige a login, no vota
        self.assertEqual(build.score, 0)

    def test_upvote_increases_score(self):
        build = self.make_build()
        self.client.login(username="other", password="testpass123")
        self.client.post(reverse("builder:build_vote", args=[build.slug]), {"value": "1"})
        self.assertEqual(build.score, 1)

    def test_voting_same_value_twice_removes_vote(self):
        build = self.make_build()
        self.client.login(username="other", password="testpass123")
        url = reverse("builder:build_vote", args=[build.slug])
        self.client.post(url, {"value": "1"})
        cache.clear()  # saltar el rate limit para simular un click bastante despues
        self.client.post(url, {"value": "1"})
        self.assertEqual(build.score, 0)

    def test_one_vote_per_user_per_build(self):
        build = self.make_build()
        self.client.login(username="other", password="testpass123")
        self.assertEqual(BuildVote.objects.filter(build=build, user=self.other).count(), 0)
        self.client.post(reverse("builder:build_vote", args=[build.slug]), {"value": "1"})
        self.assertEqual(BuildVote.objects.filter(build=build, user=self.other).count(), 1)

    def test_vote_rate_limit_blocks_rapid_double_vote(self):
        build = self.make_build()
        self.client.login(username="other", password="testpass123")
        url = reverse("builder:build_vote", args=[build.slug])
        self.client.post(url, {"value": "1"})
        self.client.post(url, {"value": "-1"})  # deberia ser ignorado por el rate limit
        self.assertEqual(BuildVote.objects.get(build=build, user=self.other).value, 1)


class BuildCommentTests(BaseBuilderTestCase):
    def test_comment_requires_login(self):
        build = self.make_build()
        self.client.post(reverse("builder:build_add_comment", args=[build.slug]), {"text": "hola"})
        self.assertEqual(build.comments.count(), 0)

    def test_author_can_delete_own_comment(self):
        build = self.make_build()
        comment = BuildComment.objects.create(build=build, user=self.other, text="mi comentario")
        self.client.login(username="other", password="testpass123")
        self.client.post(reverse("builder:build_delete_comment", args=[comment.id]))
        self.assertFalse(BuildComment.objects.filter(id=comment.id).exists())

    def test_build_owner_can_moderate_others_comment(self):
        build = self.make_build(owner=self.owner)
        comment = BuildComment.objects.create(build=build, user=self.other, text="spam")
        self.client.login(username="owner", password="testpass123")
        response = self.client.post(reverse("builder:build_delete_comment", args=[comment.id]))
        self.assertFalse(BuildComment.objects.filter(id=comment.id).exists())
        self.assertNotEqual(response.status_code, 403)

    def test_random_user_cannot_delete_others_comment(self):
        build = self.make_build(owner=self.owner)
        stranger = User.objects.create_user(username="stranger", password="testpass123")
        comment = BuildComment.objects.create(build=build, user=self.other, text="comentario ajeno")
        self.client.login(username="stranger", password="testpass123")
        response = self.client.post(reverse("builder:build_delete_comment", args=[comment.id]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(BuildComment.objects.filter(id=comment.id).exists())

    def test_comment_rate_limit_blocks_rapid_second_comment(self):
        build = self.make_build()
        self.client.login(username="other", password="testpass123")
        url = reverse("builder:build_add_comment", args=[build.slug])
        self.client.post(url, {"text": "primero"})
        self.client.post(url, {"text": "segundo, deberia bloquearse"})
        self.assertEqual(build.comments.count(), 1)


class BuildPermissionTests(BaseBuilderTestCase):
    def test_only_owner_can_edit(self):
        build = self.make_build(owner=self.owner)
        self.client.login(username="other", password="testpass123")
        response = self.client.get(reverse("builder:build_edit", args=[build.slug]))
        self.assertEqual(response.status_code, 403)

    def test_only_owner_can_delete(self):
        build = self.make_build(owner=self.owner)
        self.client.login(username="other", password="testpass123")
        response = self.client.post(reverse("builder:build_delete", args=[build.slug]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Build.objects.filter(id=build.id).exists())

    def test_private_build_hidden_from_others(self):
        build = self.make_build(owner=self.owner, is_public=False)
        self.client.login(username="other", password="testpass123")
        response = self.client.get(reverse("builder:build_detail", args=[build.slug]))
        self.assertEqual(response.status_code, 404)

    def test_private_build_visible_to_owner(self):
        build = self.make_build(owner=self.owner, is_public=False)
        self.client.login(username="owner", password="testpass123")
        response = self.client.get(reverse("builder:build_detail", args=[build.slug]))
        self.assertEqual(response.status_code, 200)


class BuildDuplicateTests(BaseBuilderTestCase):
    def test_duplicate_creates_private_copy_with_new_owner(self):
        build = self.make_build(owner=self.owner)
        self.client.login(username="other", password="testpass123")
        self.client.post(reverse("builder:build_duplicate", args=[build.slug]))
        copy = Build.objects.filter(owner=self.other, name__startswith=build.name).first()
        self.assertIsNotNone(copy)
        self.assertFalse(copy.is_public)

    def test_cannot_duplicate_private_build_of_another_user(self):
        build = self.make_build(owner=self.owner, is_public=False)
        self.client.login(username="other", password="testpass123")
        response = self.client.post(reverse("builder:build_duplicate", args=[build.slug]))
        self.assertEqual(response.status_code, 403)


class BuildFavoriteTests(BaseBuilderTestCase):
    def test_toggle_favorite_on_then_off(self):
        build = self.make_build()
        self.client.login(username="other", password="testpass123")
        url = reverse("builder:build_favorite_toggle", args=[build.slug])
        self.client.post(url)
        self.assertTrue(BuildFavorite.objects.filter(build=build, user=self.other).exists())
        cache.clear()  # saltar el rate limit para simular un segundo click bien despues
        self.client.post(url)
        self.assertFalse(BuildFavorite.objects.filter(build=build, user=self.other).exists())

    def test_favorites_page_lists_only_my_favorites(self):
        mine_fav = self.make_build(name="Favorita")
        not_fav = self.make_build(name="No favorita")
        self.client.login(username="other", password="testpass123")
        self.client.post(reverse("builder:build_favorite_toggle", args=[mine_fav.slug]))
        response = self.client.get(reverse("builder:my_favorites"))
        self.assertContains(response, "Favorita")
        self.assertNotContains(response, "No favorita")


class PageLoadTests(BaseBuilderTestCase):
    """Que las paginas principales carguen sin reventar (humo/smoke tests)."""

    def test_build_list_loads(self):
        self.assertEqual(self.client.get(reverse("builder:build_list")).status_code, 200)

    def test_how_it_works_loads(self):
        self.assertEqual(self.client.get(reverse("builder:how_it_works")).status_code, 200)

    def test_class_list_loads(self):
        self.assertEqual(self.client.get(reverse("builder:class_list")).status_code, 200)

    def test_class_detail_loads(self):
        url = reverse("builder:class_detail", args=[self.game_class.slug])
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_user_profile_loads(self):
        url = reverse("builder:user_profile", args=[self.owner.username])
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_build_detail_loads(self):
        build = self.make_build()
        response = self.client.get(reverse("builder:build_detail", args=[build.slug]))
        self.assertEqual(response.status_code, 200)

    def test_robots_txt_loads(self):
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Sitemap:", response.content)

    def test_sitemap_xml_loads_and_lists_public_build(self):
        build = self.make_build(is_public=True)
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        self.assertIn(build.slug.encode(), response.content)


class NotificationTests(BaseBuilderTestCase):
    def test_comment_notifies_build_owner(self):
        build = self.make_build(owner=self.owner)
        self.client.login(username="other", password="testpass123")
        self.client.post(reverse("builder:build_add_comment", args=[build.slug]), {"text": "hola"})
        self.assertEqual(self.owner.notifications.count(), 1)
        notif = self.owner.notifications.first()
        self.assertEqual(notif.verb, "comment")
        self.assertEqual(notif.actor, self.other)
        self.assertFalse(notif.is_read)

    def test_vote_notifies_build_owner(self):
        build = self.make_build(owner=self.owner)
        self.client.login(username="other", password="testpass123")
        self.client.post(reverse("builder:build_vote", args=[build.slug]), {"value": "1"})
        self.assertEqual(self.owner.notifications.filter(verb="vote").count(), 1)

    def test_no_self_notification(self):
        build = self.make_build(owner=self.owner)
        self.client.login(username="owner", password="testpass123")
        self.client.post(reverse("builder:build_add_comment", args=[build.slug]), {"text": "mi propio comentario"})
        self.assertEqual(self.owner.notifications.count(), 0)

    def test_visiting_notifications_page_marks_as_read(self):
        build = self.make_build(owner=self.owner)
        self.client.login(username="other", password="testpass123")
        self.client.post(reverse("builder:build_add_comment", args=[build.slug]), {"text": "hola"})
        self.client.logout()

        self.client.login(username="owner", password="testpass123")
        self.client.get(reverse("builder:notifications"))
        self.assertEqual(self.owner.notifications.filter(is_read=False).count(), 0)


class BuildVersioningTests(BaseBuilderTestCase):
    """Builds vivos: versiones del juego, revisiones, remix e idioma."""

    def setUp(self):
        super().setUp()
        from .models import GameVersion
        import datetime
        GameVersion.objects.all().delete()  # la migracion de datos crea "Rematch"
        self.v1 = GameVersion.objects.create(
            name="Parche viejo", released_on=datetime.date(2026, 1, 1), is_current=True,
        )

    def _post_create(self, name="Build nueva", **extra):
        self.client.login(username="owner", password="testpass123")
        data = {"name": name, "primary_class": self.game_class.id, "is_public": "on"}
        data.update(extra)
        self.client.post(reverse("builder:build_create"), data)
        return Build.objects.get(owner=self.owner, name=name)

    def test_only_one_current_version(self):
        from .models import GameVersion
        import datetime
        v2 = GameVersion.objects.create(
            name="Parche nuevo", released_on=datetime.date(2026, 9, 15), is_current=True,
        )
        self.v1.refresh_from_db()
        self.assertFalse(self.v1.is_current)
        self.assertEqual(GameVersion.current(), v2)

    def test_create_records_first_revision_with_current_version(self):
        build = self._post_create(language="en")
        self.assertEqual(build.revisions.count(), 1)
        rev = build.latest_revision()
        self.assertEqual(rev.number, 1)
        self.assertEqual(rev.game_version, self.v1)
        self.assertEqual(rev.data["name"], "Build nueva")
        self.assertEqual(build.game_version, self.v1)
        self.assertEqual(build.language, "en")
        self.assertIsNotNone(build.verified_at)

    def test_invalid_language_falls_back_to_spanish(self):
        build = self._post_create(language="xx")
        self.assertEqual(build.language, "es")

    def test_edit_without_changes_does_not_add_revision(self):
        build = self._post_create()
        url = reverse("builder:build_edit", args=[build.slug])
        self.client.post(url, {"name": "Build nueva", "primary_class": self.game_class.id, "is_public": "on"})
        self.assertEqual(build.revisions.count(), 1)

    def test_edit_with_changes_adds_revision(self):
        build = self._post_create()
        url = reverse("builder:build_edit", args=[build.slug])
        self.client.post(url, {
            "name": "Build renombrada", "primary_class": self.game_class.id,
            "description": "Nueva guía", "is_public": "on",
        })
        self.assertEqual(build.revisions.count(), 2)
        self.assertEqual(build.latest_revision().data["name"], "Build renombrada")

    def test_build_from_older_version_is_flagged(self):
        from .models import GameVersion
        import datetime
        build = self._post_create()
        GameVersion.objects.create(
            name="Parche nuevo", released_on=datetime.date(2026, 9, 15), is_current=True,
        )
        build.refresh_from_db()
        self.assertTrue(build.is_outdated_version)
        response = self.client.get(reverse("builder:build_detail", args=[build.slug]))
        self.assertContains(response, "Revisar")

    def test_remix_keeps_credit_and_items(self):
        from .models import EquipmentItem
        ally = EquipmentItem.objects.create(
            kind="ally", name="Aliado", slug="aliado", source_path="item/ally/test",
        )
        build = self.make_build(owner=self.owner)
        build.ally = ally
        build.language = "en"
        build.save()
        self.client.login(username="other", password="testpass123")
        self.client.post(reverse("builder:build_duplicate", args=[build.slug]))
        remix = Build.objects.get(owner=self.other)
        self.assertEqual(remix.remixed_from, build)
        self.assertEqual(remix.ally, ally)
        self.assertEqual(remix.language, "en")
        self.assertEqual(remix.revisions.count(), 1)
        self.assertIn(remix, build.remixes.all())

    def test_detail_shows_remix_credit(self):
        build = self.make_build(owner=self.owner, name="Original")
        remix = self.make_build(owner=self.other, name="Mi remix")
        remix.remixed_from = build
        remix.save()
        response = self.client.get(reverse("builder:build_detail", args=[remix.slug]))
        self.assertContains(response, "Remix de")
        self.assertContains(response, "Original")
        response = self.client.get(reverse("builder:build_detail", args=[build.slug]))
        self.assertContains(response, "Remixes de la comunidad")


class BuildSlugTests(BaseBuilderTestCase):
    def _create(self, name):
        self.client.login(username="owner", password="testpass123")
        return self.client.post(reverse("builder:build_create"), {
            "name": name, "primary_class": self.game_class.id, "is_public": "on",
        })

    def test_same_user_same_name_gets_unique_slugs(self):
        first = self._create("Mi build")
        cache.clear()  # el antispam bloquea 2 creaciones en menos de 3 segundos
        second = self._create("Mi build")
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        slugs = sorted(Build.objects.filter(owner=self.owner).values_list("slug", flat=True))
        self.assertEqual(slugs, [f"mi-build-{self.owner.id}", f"mi-build-{self.owner.id}-2"])

    def test_name_without_letters_still_gets_slug(self):
        self._create("???")
        build = Build.objects.get(owner=self.owner)
        self.assertEqual(build.slug, f"build-{self.owner.id}")
        response = self.client.get(build.get_absolute_url())
        self.assertEqual(response.status_code, 200)


class PatchReviewTests(BaseBuilderTestCase):
    """Fase 1: publicar un parche marca builds afectadas y el autor confirma."""

    def setUp(self):
        super().setUp()
        import datetime
        from .models import GameVersion
        GameVersion.objects.all().delete()
        self.old = GameVersion.objects.create(
            name="Viejo", released_on=datetime.date(2026, 1, 1), is_current=True,
        )
        self.other_class = GameClass.objects.create(
            name="Otra Clase", slug="otra-clase", primary_role="tank", damage_type="magic",
        )
        self.affected_build = self.make_build(name="Afectada")
        self.safe_build = self.make_build(name="Segura")
        self.safe_build.primary_class = self.other_class
        self.safe_build.save()
        Build.objects.update(game_version=self.old, status="current")
        self.new = GameVersion.objects.create(name="Nuevo", released_on=datetime.date(2026, 9, 15))
        self.new.affected_classes.add(self.game_class)

    def test_publish_flags_only_affected_builds_and_notifies(self):
        from .models import Notification, GameVersion
        flagged = self.new.publish()
        self.assertEqual(flagged, 1)
        self.affected_build.refresh_from_db()
        self.safe_build.refresh_from_db()
        self.assertEqual(self.affected_build.status, "review")
        self.assertEqual(self.affected_build.game_version, self.old)
        self.assertEqual(self.safe_build.status, "current")
        self.assertEqual(self.safe_build.game_version, self.new)
        self.assertEqual(GameVersion.current(), self.new)
        note = Notification.objects.get(verb="review")
        self.assertEqual(note.recipient, self.owner)
        self.assertEqual(note.build, self.affected_build)

    def test_publish_twice_does_not_duplicate_notifications(self):
        from .models import Notification
        self.new.publish()
        self.new.publish()
        self.assertEqual(Notification.objects.filter(verb="review").count(), 1)

    def test_owner_sees_callout_and_confirms(self):
        self.new.publish()
        self.client.login(username="owner", password="testpass123")
        url = reverse("builder:build_detail", args=[self.affected_build.slug])
        self.assertContains(self.client.get(url), "Sigue al día")
        response = self.client.post(
            reverse("builder:build_confirm_current", args=[self.affected_build.slug])
        )
        self.assertEqual(response.status_code, 302)
        self.affected_build.refresh_from_db()
        self.assertEqual(self.affected_build.status, "current")
        self.assertEqual(self.affected_build.game_version, self.new)
        self.assertEqual(self.affected_build.revisions.count(), 0)  # confirmar no crea revision
        self.assertNotContains(self.client.get(url), "review-callout")

    def test_other_user_cannot_confirm_or_see_callout(self):
        self.new.publish()
        self.client.login(username="other", password="testpass123")
        url = reverse("builder:build_detail", args=[self.affected_build.slug])
        self.assertNotContains(self.client.get(url), "review-callout")
        response = self.client.post(
            reverse("builder:build_confirm_current", args=[self.affected_build.slug])
        )
        self.assertEqual(response.status_code, 403)
        self.affected_build.refresh_from_db()
        self.assertEqual(self.affected_build.status, "review")

    def test_review_notification_page_renders(self):
        self.new.publish()
        self.client.login(username="owner", password="testpass123")
        response = self.client.get(reverse("builder:notifications"))
        self.assertContains(response, "El nuevo parche puede afectar tu build")

    def test_admin_marking_current_publishes(self):
        User.objects.filter(pk=self.owner.pk).update(is_staff=True, is_superuser=True)
        self.client.login(username="owner", password="testpass123")
        url = reverse("admin:builder_gameversion_change", args=[self.new.pk])
        response = self.client.post(url, {
            "name": "Nuevo", "released_on": "2026-09-15", "patch_notes_url": "",
            "is_current": "on", "affected_classes": [self.game_class.pk], "notes": "",
        })
        self.assertEqual(response.status_code, 302)
        self.affected_build.refresh_from_db()
        self.assertEqual(self.affected_build.status, "review")


class LanguageTests(BaseBuilderTestCase):
    """Selector ES/EN: español por defecto, inglés al elegirlo o por el navegador."""

    def test_spanish_is_default(self):
        response = self.client.get(reverse("builder:build_list"))
        self.assertContains(response, "Arma tu build de Trove")
        self.assertContains(response, '<html lang="es">')

    def test_browser_in_english_gets_english(self):
        response = self.client.get(reverse("builder:build_list"), HTTP_ACCEPT_LANGUAGE="en-US,en;q=0.9")
        self.assertContains(response, "Build your Trove character")
        self.assertContains(response, '<html lang="en">')

    def test_switcher_changes_language_and_remembers_it(self):
        response = self.client.post(
            reverse("set_language"), {"language": "en", "next": reverse("builder:class_list")},
        )
        self.assertRedirects(response, reverse("builder:class_list"), fetch_redirect_response=False)
        response = self.client.get(reverse("builder:class_list"))
        self.assertContains(response, "Trove classes")
        self.client.post(reverse("set_language"), {"language": "es", "next": "/"})
        self.assertContains(self.client.get(reverse("builder:class_list")), "Clases de Trove")

    def test_how_it_works_has_english_version(self):
        self.client.post(reverse("set_language"), {"language": "en", "next": "/"})
        self.assertContains(self.client.get(reverse("builder:how_it_works")), "How Trove Builder works")

    def test_messages_are_translated(self):
        self.client.post(reverse("set_language"), {"language": "en", "next": "/"})
        build = self.make_build(owner=self.owner, name="Mi build")
        self.client.login(username="owner", password="testpass123")
        response = self.client.post(
            reverse("builder:build_edit", args=[build.slug]),
            {"name": "Mi build", "primary_class": self.game_class.id}, follow=True,
        )
        self.assertContains(response, "Build updated.")
        self.assertContains(response, "Up to date")

    def test_translate_link_only_when_languages_differ(self):
        build = self.make_build(owner=self.owner, name="Guia")
        build.description = "Usa gemas de fuego"
        build.save()
        url = reverse("builder:build_detail", args=[build.slug])
        self.assertNotContains(self.client.get(url), "translate.google.com/?sl=auto&amp;tl=es&amp;op=translate&amp;text=Usa")
        self.client.post(reverse("set_language"), {"language": "en", "next": "/"})
        response = self.client.get(url)
        self.assertContains(response, "Translate with Google")
        self.assertContains(response, "text=Usa%20gemas%20de%20fuego")

    def test_all_template_text_is_translatable(self):
        """Falla si alguna plantilla tiene texto en español sin {% translate %}."""
        from .i18n_check import untranslated_texts
        problems = untranslated_texts()
        detail = "\n".join(f"  {name}, línea {line}: {text!r}" for name, line, text in problems)
        self.assertEqual(
            problems, [],
            "Estos textos están en español pero no se van a traducir. "
            "Envuélvelos en {% translate \"...\" %}:\n" + detail,
        )

    def test_game_data_is_translated_in_english(self):
        """Los datos del juego usan locale/en/game_data.json cuando la página está en inglés."""
        import json
        import tempfile
        from pathlib import Path
        from unittest import mock
        from . import game_text

        self.game_class.description = "Guerrero cuerpo a cuerpo."
        self.game_class.save()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "game_data.json"
            path.write_text(json.dumps({"Guerrero cuerpo a cuerpo.": "Melee warrior."}), encoding="utf-8")
            with mock.patch.object(game_text, "GAME_DATA_PATH", path), \
                    mock.patch.dict(game_text._cache, {"mtime": None, "data": {}}):
                url = reverse("builder:class_detail", args=[self.game_class.slug])
                self.assertContains(self.client.get(url), "Guerrero cuerpo a cuerpo.")
                self.client.post(reverse("set_language"), {"language": "en", "next": "/"})
                response = self.client.get(url)
                self.assertContains(response, "Melee warrior.")
                self.assertNotContains(response, "Guerrero cuerpo a cuerpo.")
