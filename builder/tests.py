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
