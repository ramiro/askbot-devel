from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.test import TestCase
from django.utils import simplejson
from django.utils.translation import ugettext as _

from categories.models import Category

from askbot.conf import settings as askbot_settings
from askbot.models import Tag, Question
from askbot.tests.utils import create_user
from askbot.views.cats import generate_tree


class TreeTests(TestCase):
    def setUp(self):
        root = Category.objects.create(name='Root')
        n1 = Category.objects.create(name='N1', parent=root)
        Category.objects.create(name='N2', parent=root)
        Category.objects.create(name='Child1', parent=n1)
        Category.objects.create(name='Child2', parent=n1)

    def test_python_tree(self):
        """
        Test that django-mptt builds the tree correctly. version 0.4.2 has a
        bug when populating the tree, it incorrectly grafts the Child1 and
        Child2 nodes under the N2 node.
        """
        self.assertEqual(
            {
                "name": u"Root",
                "id": 1,
                "children": [
                    {
                        "name": u"N1",
                        "id": 2,
                        "children": [
                            {
                                "name": u"Child1",
                                "id": 4,
                                "children": []
                            },
                            {
                                "name": u"Child2",
                                "id": 5,
                                "children": []
                            }
                        ]
                    },
                    {
                        "name": u"N2",
                        "id": 3,
                        "children": []
                    }

                ]
            },
            generate_tree()
        )


class EmptyTreeTests(TestCase):
    def test_python_tree(self):
        """Data structure generation shouldn't explode when tree is empty."""
        self.assertEqual({}, generate_tree())


class AjaxTests(TestCase):
    def ajax_get(self, path, data={}, follow=False, **extra):
        extra.update({'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'})
        return self.client.get(path, data, follow, **extra)

    def ajax_post(self, path, data={}, content_type='application/x-www-form-urlencoded', follow=False,
            **extra):
        extra.update({'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'})
        return self.client.post(path, data, content_type, follow, **extra)

    def ajax_post_json(self, path, data):
        return self.ajax_post(path, simplejson.dumps(data))

    def assertAjaxSuccess(self, response):
        """
        Helper method that checks the akjax call was succesful. Returns the
        data decoded from the JSON response.
        """
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        try:
            data = simplejson.loads(response.content)
        except Exception, e:
            self.fail(str(e))
        self.assertEqual(data['status'], 'success')
        return data

    def assertAjaxFailure(self, response):
        """
        Helper method that checks the akjax call failed. Returns the
        data decoded from the JSON response.
        """
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        try:
            data = simplejson.loads(response.content)
        except Exception, e:
            self.fail(str(e))
        self.assertEqual(data['status'], 'error')
        return data


class ViewsTests(AjaxTests):
    def setUp(self):
        # An administrator user
        self.owner = User.objects.create_user(username='owner', email='owner@example.com', password='secret')
        self.owner.is_staff = True
        self.owner.is_superuser = True
        self.owner.save()
        # A moderator
        self.mod1 = create_user(username='mod1', email='mod1@example.com', status='m')
        self.mod1.set_password('modpw')
        self.mod1.save()
        # A normal user
        User.objects.create_user(username='user1', email='user1@example.com', password='123')
        # Setup a small category tree
        self.root = Category.objects.create(name=u'Root')
        self.c1 = Category.objects.create(name=u'Child1', parent=self.root)
        self.c2 = Category.objects.create(name=u'Child2', parent=self.c1)
        c3 = Category.objects.create(name=u'Child3', parent=self.root)

        self.tag1 = Tag.objects.create(name=u'Tag1', created_by=self.owner)
        self.tag2 = Tag.objects.create(name=u'Tag2', created_by=self.owner)
        self.tag2.categories.add(self.c1)
        self.tag3 = Tag.objects.create(name=u'Tag3', created_by=self.owner)
        self.tag3.categories.add(c3)

        askbot_settings.update('ENABLE_CATEGORIES', True)
        askbot_settings.update('CATEGORIES_MAX_TREE_DEPTH', 3)

    def test_categories_off(self):
        """AJAX category-related views shouldn't be published when master switch is off."""
        askbot_settings.update('ENABLE_CATEGORIES', False)
        r = self.ajax_post_json(reverse('add_category'), {'name': u'Entertainment', 'parent': self.root.id})
        self.assertEqual(r.status_code, 404)
        askbot_settings.update('ENABLE_CATEGORIES', True)
        r = self.ajax_post_json(reverse('add_category'), {'name': u'Family', 'parent': self.root.id})
        self.assertEqual(r.status_code, 200)

    # `add_category` view tests

    def test_add_category_no_permission(self):
        """Only administrator users should be able to add a category via the view."""
        self.client.login(username='user1', password='123')
        r = self.ajax_post_json(reverse('add_category'), {'name': u'Health', 'parent': self.root.id})
        data = self.assertAjaxFailure(r)
        self.assertTrue('Sorry, but you cannot access this view' in data['message'])

    def test_add_category_missing_param(self):
        """Add new category: should fail when no name parameter is provided."""
        self.client.login(username='owner', password='secret')
        r = self.ajax_post_json(reverse('add_category'), {})
        data = self.assertAjaxFailure(r)
        self.assertTrue("Missing or invalid new category name parameter" in data['message'])

    def test_add_category_exists(self):
        """Two categories with the same name shouldn't be allowed."""
        self.client.login(username='owner', password='secret')
        # A new category when another with the same name exists at the same level
        r = self.ajax_post_json(reverse('add_category'), {'name': u'Child1', 'parent': self.root.id})
        data = self.assertAjaxFailure(r)
        self.assertTrue('There is already a category with that name' in data['message'])

        # A new category when other with the same name exists at another level
        obj = Category.objects.get(name=u'Child3')
        r = self.ajax_post_json(reverse('add_category'), {'name': u'Child1', 'parent': obj.id})
        data = self.assertAjaxFailure(r)
        self.assertTrue('There is already a category with that name' in data['message'])

    def test_too_deep_tree_level(self):
        """Validation of new category depth level in the tree against the CATEGORIES_MAX_TREE_DEPTH livesetting."""
        self.client.login(username='owner', password='secret')
        r = self.ajax_post_json(reverse('add_category'), {'name': u'ImTooDeep', 'parent': self.c2.id})
        data = self.assertAjaxFailure(r)
        self.assertTrue('Invalid category nesting depth level' in data['message'])

    def add_category_success(self, post_data):
        """Helper method"""
        category_objects = Category.objects.count()
        r = self.ajax_post_json(reverse('add_category'), post_data)
        self.assertAjaxSuccess(r)
        self.assertEqual(category_objects + 1, Category.objects.count())

    def test_add_category_success(self):
        """Valid new categories should be added to the database."""
        self.client.login(username='owner', password='secret')
        # A child of the root node
        self.add_category_success({'name': u'ANewCategory1', 'parent': self.root.id})
        # A child of a non-root node
        self.add_category_success({'name': u'ANewCategory2', 'parent': self.c1.id})

    def test_add_new_tree(self):
        """Insertion of a new root-of-tree node should work."""
        self.client.login(username='owner', password='secret')
        category_objects = Category.objects.count()
        r = self.ajax_post_json(reverse('add_category'), {'name': u'AnotherRoot', 'parent': None})
        self.assertAjaxSuccess(r)
        self.assertEqual(category_objects + 1, Category.objects.count())
        self.assertEqual(Category.tree.root_nodes().filter(name=u'AnotherRoot').count(), 1)

    def test_add_category_invalid_parent(self):
        """Attempts to insert a new category with an invalid parent should fail."""
        self.client.login(username='owner', password='secret')
        r = self.ajax_post_json(reverse('add_category'), {'name': u'Foo', 'parent': 123456})
        data = self.assertAjaxFailure(r)
        self.assertTrue("Requested parent category doesn't exist" in data['message'])

    # `rename_category` view tests

    def test_rename_missing_params(self):
        """Rename category: should fail when no IDs are passed."""
        self.client.login(username='owner', password='secret')
        obj = Category.objects.get(name=u'Child1')
        r = self.ajax_post_json(reverse('rename_category'), {'id': obj.id})
        data = self.assertAjaxFailure(r)
        self.assertTrue("Missing or invalid required parameter" in data['message'])

        r = self.ajax_post_json(reverse('rename_category'), {'name': u'Foo'})
        data = self.assertAjaxFailure(r)
        self.assertTrue("Missing or invalid required parameter" in data['message'])

    def test_rename_success(self):
        """Rename a category"""
        self.client.login(username='owner', password='secret')
        obj = Category.objects.get(name=u'Child1')
        r = self.ajax_post_json(reverse('rename_category'), {'id': obj.id, 'name': u'NewName'})
        self.assertAjaxSuccess(r)
        # Re-fech the object from the DB
        obj = Category.objects.get(id=obj.id)
        self.assertEqual(obj.name, u'NewName')

    def test_rename_exists(self):
        """Renaming to a name that already exists shouldn't be allowed."""
        self.client.login(username='owner', password='secret')
        r = self.ajax_post_json(reverse('rename_category'), {'id': self.root.id, 'name': u'Child1'})
        data = self.assertAjaxFailure(r)
        self.assertTrue('There is already a category with that name' in data['message'])

    def test_rename_invalid_id(self):
        """Attempts to rename a category with an invalid ID should fail."""
        self.client.login(username='owner', password='secret')
        r = self.ajax_post_json(reverse('rename_category'), {'id': 12345, 'name': u'NewName'})
        data = self.assertAjaxFailure(r)
        self.assertTrue("Requested category doesn't exist" in data['message'])

    # `add_tag_to_category` view tests

    def test_tag_missing_params(self):
        """Add tag to category: should fail when no IDs are passed."""
        self.client.login(username='owner', password='secret')
        r = self.ajax_post_json(reverse('add_tag_to_category'), {'cat_id': self.root.id})
        data = self.assertAjaxFailure(r)
        self.assertTrue("Missing required parameter" in data['message'])

        r = self.ajax_post_json(reverse('add_tag_to_category'), {'tag_id': self.tag1.id})
        data = self.assertAjaxFailure(r)
        self.assertTrue("Missing required parameter" in data['message'])

    def test_tag_invalid_ids(self):
        """Attempts to add a tag to a category using invalid IDs should fail."""
        self.client.login(username='owner', password='secret')
        r = self.ajax_post_json(
                reverse('add_tag_to_category'),
                {'cat_id': self.root.id, 'tag_id': 100})
        data = self.assertAjaxFailure(r)
        self.assertTrue("Requested tag doesn't exist" in data['message'])

        r = self.ajax_post_json(
                reverse('add_tag_to_category'),
                {'cat_id': 54321, 'tag_id': self.tag1.id})
        data = self.assertAjaxFailure(r)
        self.assertTrue("Requested category doesn't exist" in data['message'])

    def test_tag_success(self):
        """Adding a tag to a category."""
        self.client.login(username='owner', password='secret')
        associated_cats = self.tag1.categories.filter(id=self.root.id).count()
        r = self.ajax_post_json(
                reverse('add_tag_to_category'),
                {'cat_id': self.root.id, 'tag_id': self.tag1.id})
        self.assertAjaxSuccess(r)
        self.assertEqual(associated_cats + 1, self.tag1.categories.filter(id=self.root.id).count())

    # `get_tag_categories` view tests

    def test_tag_categories_missing_param(self):
        """Get categories for tag: should fail when no tag ID is passed."""
        r = self.ajax_post_json(reverse('get_tag_categories'), {})
        data = self.assertAjaxFailure(r)
        self.assertTrue("Missing tag_id parameter" in data['message'])

    def test_tag_categories_invalid_id(self):
        """Get categories for tag: should fail when invalid tag ID is passed."""
        r = self.ajax_post_json(reverse('get_tag_categories'), {'tag_id': 100})
        data = self.assertAjaxFailure(r)
        self.assertTrue("Requested tag doesn't exist" in data['message'])

    def test_tag_categories_success(self):
        """Get categories for tag."""
        # Empty category set
        r = self.ajax_post_json(reverse('get_tag_categories'), {'tag_id': self.tag1.id})
        data = self.assertAjaxSuccess(r)
        self.assertEqual(len(data['cats']), 0)

        # Non-empty category set
        r = self.ajax_post_json(reverse('get_tag_categories'), {'tag_id': self.tag2.id})
        data = self.assertAjaxSuccess(r)
        self.assertEqual(data['cats'], [{'id': self.c1.id, 'name': self.c1.name}])

    def test_tag_categories_escaping(self):
        self.client.login(username='owner', password='secret')
        # Add a category with a XSS attack
        xss_cat = Category.objects.create(name=u'Item</li></ul><script type="text/javascript">alert(\'Hello\');</script>', parent=self.root)
        # Associate it to a tag
        a_tag = Tag.objects.create(name=u'atag', created_by=self.owner)
        a_tag.categories.add(xss_cat)
        # Now query for the categories associated with the tag
        r = self.ajax_post_json(reverse('get_tag_categories'), {'tag_id': a_tag.id})
        data = self.assertAjaxSuccess(r)
        # It shouldn't have naked HTML tags (a XSS vector)
        self.assertFalse(
            "Item</li></ul><script type=\"text/javascript\">alert('Hello');</script>" in data['cats'][0]['name'],
            "Views that output category names shouldn't be vulnerable to XSS"
        )

    # `remove_tag_from_category` view tests

    def test_remove_tag_category__no_permission(self):
        """Only administrator and moderator users should be able to remove a
        tag from a category via the view."""
        # a normal user
        self.client.login(username='user1', password='123')
        r = self.ajax_post_json(
            reverse('remove_tag_from_category'),
            {
                'cat_id': self.c1.id,
                'tag_id': self.tag2.id
            }
        )
        data = self.assertAjaxFailure(r)
        self.assertTrue('Sorry, but you cannot access this view' in data['message'])
        self.client.logout()

        # a moderator user
        self.client.login(username='mod1', password='modpw')
        r = self.ajax_post_json(
            reverse('remove_tag_from_category'),
            {
                'cat_id': self.c1.id,
                'tag_id': self.tag2.id
            }
        )
        self.assertAjaxSuccess(r)
        self.client.logout()

    def test_remove_tag_category_missing_params(self):
        """Remove tag from category: should fail when no IDs are passed."""
        self.client.login(username='owner', password='secret')
        r = self.ajax_post_json(reverse('remove_tag_from_category'),
                {'tag_id': self.tag2.id})
        data = self.assertAjaxFailure(r)
        self.assertTrue("Missing required parameter" in data['message'])

        r = self.ajax_post_json(reverse('remove_tag_from_category'),
                {'cat_id': self.c1.id})
        data = self.assertAjaxFailure(r)
        self.assertTrue("Missing required parameter" in data['message'])

    def test_remove_tag_category_success(self):
        """Remove tag from category: Success."""
        self.client.login(username='owner', password='secret')
        r = self.ajax_post_json(
            reverse('remove_tag_from_category'),
            {
                'cat_id': self.c1.id,
                'tag_id': self.tag2.id
            }
        )
        self.assertAjaxSuccess(r)

    def test_remove_tag_category_invalid_params(self):
        """Remove tag from category: should fail when invalid IDs are passed."""
        self.client.login(username='owner', password='secret')
        r = self.ajax_post_json(
            reverse('remove_tag_from_category'),
            {
                'cat_id': 13524,
                'tag_id': self.tag2.id
            }
        )
        data = self.assertAjaxFailure(r)
        self.assertTrue("Requested category doesn't exist" in data['message'])

        r = self.ajax_post_json(
            reverse('remove_tag_from_category'),
            {
                'cat_id': self.c1.id,
                'tag_id': 1000
            }
        )
        data = self.assertAjaxFailure(r)
        self.assertTrue("Requested tag doesn't exist" in data['message'])

    # `delete_category` view tests

    def test_delete_category_missing_id(self):
        """Error is reported if the views is called without an id for the category to delete."""
        self.client.login(username='owner', password='secret')
        r = self.ajax_post_json(reverse('delete_category'), {})
        data = self.assertAjaxFailure(r)
        self.assertTrue("Missing or invalid required parameter" in data['message'])

    def test_delete_category_invalid_id(self):
        """Error is reported if the views is called with an invalid id for the category to delete."""
        self.client.login(username='owner', password='secret')
        r = self.ajax_post_json(
            reverse('delete_category'),
            {
                'id': 223344
            }
        )
        data = self.assertAjaxFailure(r)
        self.assertTrue("Requested category doesn't exist" in data['message'])

    def test_delete_category_success(self):
        """Succesful deletion of a category without child categories nor associated tags."""
        self.client.login(username='owner', password='secret')
        obj = Category.objects.get(name=u'Child2')
        r = self.ajax_post_json(
            reverse('delete_category'),
            {
                'id': obj.id
            }
        )
        self.assertAjaxSuccess(r)

    def test_delete_category_no_leaf(self):
        """Error is reported if deletion of a the category with child categories is attempted."""
        self.client.login(username='owner', password='secret')
        obj = Category.objects.get(name=u'Child1')
        r = self.ajax_post_json(
            reverse('delete_category'),
            {
                'id': obj.id
            }
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        try:
            data = simplejson.loads(r.content)
        except Exception, e:
            self.fail(str(e))
        self.assertEqual(data['status'], "cannot_delete_subcategories")

    def test_delete_category_with_tags(self):
        """Deletion of a the category with associated tags."""
        self.client.login(username='owner', password='secret')
        obj = Category.objects.get(name=u'Child3')
        r = self.ajax_post_json(reverse('delete_category'), {'id': obj.id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        try:
            data = simplejson.loads(r.content)
        except Exception, e:
            self.fail(str(e))
        self.assertEqual(data['status'], "need_confirmation")
        self.assertTrue('token' in data)

        # Resubmit using the provided token
        r = self.ajax_post_json(
            reverse('delete_category'),
            {
                'id': obj.id,
                'token': data['token']
            }
        )
        data = self.assertAjaxSuccess(r)
        self.assertFalse('token' in data)

    def test_delete_category_with_tags_invalid_token(self):
        """Deletion of a the category with associated tags."""
        self.client.login(username='owner', password='secret')
        obj = Category.objects.get(name=u'Child3')
        r = self.ajax_post_json(reverse('delete_category'), {'id': obj.id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertContains(r, "need_confirmation")
        try:
            data = simplejson.loads(r.content)
        except Exception, e:
            self.fail(str(e))
        self.assertTrue('token' in data)

        # Resubmit using a corrupt token
        r = self.ajax_post_json(
            reverse('delete_category'),
            {
                'id': obj.id,
                'token': 'this is a fake token'
            }
        )
        data = self.assertAjaxFailure(r)
        self.assertFalse('token' in data)
        self.assertTrue("Invalid token provided" in data['message'])

    # `get_categories` view tests

    def test_category_autocomplete_helper(self):
        # No GET HTTP method
        r = self.client.post(reverse('categories_list'))
        self.assertEqual(r.status_code, 405)

        # No ajax
        r = self.client.get(reverse('categories_list'))
        self.assertEqual(r.status_code, 403)

        # anonymous user
        r = self.ajax_get(reverse('categories_list'))
        self.assertEqual(r.status_code, 403)

        # a normal user
        self.client.login(username='user1', password='123')
        r = self.ajax_get(reverse('categories_list'))
        self.assertEqual(r.status_code, 403)
        self.client.logout()

        # a moderator user
        self.client.login(username='mod1', password='modpw')
        r = self.ajax_get(reverse('categories_list'))
        self.assertEqual(r.status_code, 403)
        self.client.logout()

        # an admin user
        self.client.login(username='owner', password='secret')
        r = self.ajax_get(reverse('categories_list'))
        self.assertEqual(r.status_code, 200)

    def test_category_autocomplete_helper_escaping(self):
        self.client.login(username='owner', password='secret')
        # Add a category with a XSS attack
        xss_cat = Category.objects.create(name=u'Item</li></ul><script type="text/javascript">alert(\'Bye\');</script>', parent=self.root)
        # Associate it to a tag
        a_tag = Tag.objects.create(name=u'atag', created_by=self.owner)
        a_tag.categories.add(xss_cat)
        # query for all categories
        r = self.ajax_get(reverse('categories_list'))
        self.assertEqual(r.status_code, 200)
        # It shouldn't have naked HTML tags (a XSS vector)
        self.assertFalse(
            "Item</li></ul><script type=\"text/javascript\">alert('Bye');</script>" in r.content,
            "Views that output category names shouldn't be vulnerable to XSS"
        )


class BaseFilteringTests(TestCase):
    def setUp(self):
        # An administrator user
        owner = User.objects.create_user(username='owner', email='owner@example.com', password='secret')
        owner.is_staff = True
        owner.is_superuser = True
        owner.save()

        # A normal user
        user1 = User.objects.create_user(username='user1', email='user1@example.com', password='123')

        # Create the following Category - Tag - Question setup:
        #
        #                              tag1 <=*====*=> question q1
        #
        # category1         <=*====*=> tag2 <=*====*=> question q2
        #     |
        #     `-- category2
        #
        # category3         <=*====*=> tag3 <=*==*===> question q3
        #                                          \=> question q4
        #
        # category11        <=*====*=> tag4
        #
        # category4         <=*==*===> tag5 <===*==*=> question q5
        #                          \=> tag6 <=/
        #
        # category5         <===*==*=> tag7 <=*====*=> question q6
        # category6         <=/
        #
        # category7         <=*==*===> tag8 <=*?===*=> question q7
        #                          \=> tag9 <=*====*=> question q8
        #
        # category8
        #
        # category9         <=*====*=> tagA <=*====*=> question q9
        #    |
        #    `-- category10 <=*====*=> tagB <=*====*=> question qA
        #
        root = Category.objects.create(name=u'Everything')
        c1 = Category.objects.create(name=u'category1', parent=root)
        Category.objects.create(name=u'category2', parent=c1)
        c3 = Category.objects.create(name=u'category3', parent=root)
        c4 = Category.objects.create(name=u'category4', parent=root)
        c5 = Category.objects.create(name=u'category5', parent=root)
        c6 = Category.objects.create(name=u'category6', parent=root)
        c7 = Category.objects.create(name=u'category7', parent=root)
        c8 = Category.objects.create(name=u'category8', parent=root)
        c9 = Category.objects.create(name=u'category9', parent=root)
        c10 = Category.objects.create(name=u'category10', parent=c9)
        c11 = Category.objects.create(name=u'category11', parent=c9)

        tag1 = Tag.objects.create(name=u'tag1', created_by=owner)
        tag2 = Tag.objects.create(name=u'tag2', created_by=owner)
        tag2.categories.add(c1)
        tag3 = Tag.objects.create(name=u'tag3', created_by=owner)
        tag3.categories.add(c3)
        tag4 = Tag.objects.create(name=u'tag4', created_by=owner)
        tag4.categories.add(c11)
        # TODO: Why doesn't ``c4.tags.add(tag5, tag6)`` work?
        tag5 = Tag.objects.create(name=u'tag5', created_by=owner)
        tag5.categories.add(c4)
        tag6 = Tag.objects.create(name=u'tag6', created_by=owner)
        tag6.categories.add(c4)
        tag7 = Tag.objects.create(name=u'tag7', created_by=owner)
        tag7.categories.add(c5, c6)
        tag8 = Tag.objects.create(name=u'tag8', created_by=owner)
        tag8.categories.add(c7)
        tag9 = Tag.objects.create(name=u'tag9', created_by=owner)
        tag9.categories.add(c7)
        tagA = Tag.objects.create(name=u'tagA', created_by=owner)
        tagA.categories.add(c9)
        tagB = Tag.objects.create(name=u'tagB', created_by=owner)
        tagB.categories.add(c10)

        # Make sure you use Question.update_tags() when tagging questions so
        # the denormalized internal 'used count' of Tags gets corectly updated
        q1 = Question.objects.create(title=u'Question #1', author=user1, last_activity_by=user1)
        q1.update_tags(u"tag1", user=user1)
        q2 = Question.objects.create(title=u'Question #2', author=user1, last_activity_by=user1)
        q2.update_tags(u"tag2", user=user1)
        q3 = Question.objects.create(title=u'Question #3', author=user1, last_activity_by=user1)
        q4 = Question.objects.create(title=u'Question #4', author=user1, last_activity_by=user1)
        q3.update_tags(u"tag3", user=user1)
        q4.update_tags(u"tag3", user=user1)
        q5 = Question.objects.create(title=u'Question #5', author=user1, last_activity_by=user1)
        q5.update_tags(u"tag5 tag6", user=user1)
        q6 = Question.objects.create(title=u'Question #6', author=user1, last_activity_by=user1)
        q6.update_tags(u"tag7", user=user1)
        q7 = Question.objects.create(title=u'Question #7', author=user1, last_activity_by=user1)
        q7.update_tags(u"tag8", user=user1)
        q8 = Question.objects.create(title=u'Question #8', author=user1, last_activity_by=user1)
        q8.update_tags(u"tag9", user=user1)
        q9 = Question.objects.create(title=u'Question #9', author=user1, last_activity_by=user1)
        q9.update_tags(u"tagA", user=user1)
        qA = Question.objects.create(title=u'Question #A', author=user1, last_activity_by=user1)
        qA.update_tags(u"tagB", user=user1)

        askbot_settings.update('ENABLE_CATEGORIES', True)


class QuestionFilteringTests(BaseFilteringTests):
    def setUp(self):
        super(QuestionFilteringTests, self).setUp()

    def test_root_url_redirect_success(self):
        """Home page should redirect to the questions page without errors"""
        r = self.client.get('/', follow=True)
        self.assertRedirects(r, '/%s' % _('questions/'))

    def test_no_category_simple_success(self):
        """Questions page should work without errors when no category is specified"""
        r = self.client.get('/%s' % _('questions/'))
        self.assertEqual(200, r.status_code)

        # Same thing when master categories switch is off
        askbot_settings.update('ENABLE_CATEGORIES', False)
        r = self.client.get('/%s' % _('questions/'))
        self.assertEqual(200, r.status_code)

    def test_categories_feature_off(self):
        """Filtering shouldn't work when categories features is turned off"""
        # Master categories switch -> off
        askbot_settings.update('ENABLE_CATEGORIES', False)
        r = self.client.get('/%scategory1' % _('questions/'))
        self.assertEqual(404, r.status_code)

    def test_categories_success(self):
        """Basic question filtering by category works"""
        # Category exists
        r = self.client.get('/%scategory2' % _('questions/'))
        self.assertEqual(200, r.status_code)

        # Category doesn't exist
        r = self.client.get('/%sIDontExist' % _('questions/'))
        self.assertEqual(404, r.status_code)

    def test_no_filtering(self):
        """All questions should be shown when no category filtering is in effect"""
        r = self.client.get('/%s' % _('questions/'))
        self.assertEqual(200, r.status_code)
        for q in Question.objects.all():
            self.assertContains(r, q.title)

    def test_filter_empty_category(self):
        """Question filtering by an empty category"""
        # Categories with no associated questions
        for cat in (2, 8, 11):
            r = self.client.get('/%scategory%d' % (_('questions/'), cat))
            self.assertEqual(200, r.status_code)
            for q in Question.objects.all():
                self.assertNotContains(r, q.title)

    def test_filter_1tag_manyqs(self):
        """Filter several questions associated to a category via one tag."""
        r = self.client.get('/%scategory3' % _('questions/'))
        self.assertEqual(200, r.status_code)
        for q in Question.objects.exclude(title__in=[u"Question #3", u"Question #4"]):
            self.assertNotContains(r, q.title)
        self.assertContains(r, u"Question #3")
        self.assertContains(r, u"Question #4")

    def test_filter_manytags_1q(self):
        """Filter one question associated to a category via several tags."""
        r = self.client.get('/%scategory4' % _('questions/'))
        self.assertEqual(200, r.status_code)
        for q in Question.objects.exclude(title=u"Question #5"):
            self.assertNotContains(r, q.title)
        self.assertContains(r, u"Question #5")

    def test_filter_manycats_1tag_1q(self):
        """One question associated to several categories via one tag. Filter by each of the categories"""
        for cat in (5, 6):
            r = self.client.get('/%scategory%d' % (_('questions/'), cat))
            self.assertEqual(200, r.status_code)
            for q in Question.objects.exclude(title=u"Question #6"):
                self.assertNotContains(r, q.title)
            self.assertContains(r, u"Question #6")

    def test_filter_categories_subtree(self):
        """Selection of questions associated to tags associated to sub-categories of a given category."""
        r = self.client.get('/%scategory9' % _('questions/'))
        self.assertEqual(200, r.status_code)
        for q in Question.objects.exclude(
                title__in=[u"Question #9",u"Question #A"]
        ):
            self.assertNotContains(r, q.title)
        self.assertContains(r, u"Question #9")
        self.assertContains(r, u"Question #A")

        # filtering by the sub-category should show only questions associated
        # with it:
        r = self.client.get('/%scategory10' % _('questions/'))
        self.assertEqual(200, r.status_code)
        for q in Question.objects.exclude(title=u"Question #A"):
            self.assertNotContains(r, q.title)
        self.assertContains(r, u"Question #A")

    def test_filter_categories_unique(self):
        """Question associated to a category via multiple paths gets listed once."""
        r = self.client.get('/%scategory4' % _('questions/'))
        self.assertEqual(200, r.status_code)
        for q in Question.objects.exclude(title=u"Question #5"):
            self.assertNotContains(r, q.title)
        self.assertEqual(r.content.count(u"Question #5"), 1)


class TagFilteringTests(BaseFilteringTests):
    def setUp(self):
        super(TagFilteringTests, self).setUp()

    def test_no_category_simple_success(self):
        """Tags page should work without errors when no category is specified"""
        r = self.client.get('/%s' % _('tags/'))
        self.assertEqual(200, r.status_code)

        # Same thing when master categories switch is off
        askbot_settings.update('ENABLE_CATEGORIES', False)
        r = self.client.get('/%s' % _('tags/'))
        self.assertEqual(200, r.status_code)

    def test_categories_feature_off(self):
        """Filtering shouldn't work when categories features is turned off"""
        # Master categories switch -> off
        askbot_settings.update('ENABLE_CATEGORIES', False)
        r = self.client.get('/%scategory1' % _('tags/'))
        self.assertEqual(404, r.status_code)

    def test_categories_success(self):
        """Basic tag filtering by category works"""
        # Category exists
        r = self.client.get('/%scategory2' % _('tags/'))
        self.assertEqual(200, r.status_code)

        # Category doesn't exist
        r = self.client.get('/%sIDontExist' % _('tags/'))
        self.assertEqual(404, r.status_code)

    def test_no_filtering(self):
        """All tags should be shown when no category filtering is in effect"""
        r = self.client.get('/%s' % _('tags/'))
        self.assertEqual(200, r.status_code)
        # We need to skip tag4 because it has no associated question, its
        # used_count is zero and doen't appear in the tag listing page
        #for t in Tag.objects.exclude(name=u"tag4"):
        for t in Tag.objects.exclude(used_count=0):
            self.assertContains(r, t.name)

    def test_filter_empty_category(self):
        """Tag filtering by an empty category"""
        # Categories with no associated tags
        for cat in (2, 8):
            r = self.client.get('/%scategory%d' % (_('questions/'), cat))
            self.assertEqual(200, r.status_code)
            for t in Tag.objects.all():
                self.assertNotContains(r, t.name)

    def test_filter_1tag(self):
        """One tag associated woth one category."""
        r = self.client.get('/%scategory3' % _('questions/'))
        self.assertEqual(200, r.status_code)
        for t in Tag.objects.exclude(used_count=0).exclude(name=u"tag3"):
            self.assertNotContains(r, t.name)
        self.assertContains(r, u"tag3")

    def test_filter_manytags(self):
        """Multiple tags associated to one category."""
        r = self.client.get('/%scategory4' % _('questions/'))
        self.assertEqual(200, r.status_code)
        for t in Tag.objects.exclude(used_count=0).exclude(name__in=[u"tag5", u"tag6"]):
            self.assertNotContains(r, t.name)
        self.assertContains(r, u"tag5")
        self.assertContains(r, u"tag6")

    def test_filter_manycats_1tag(self):
        """Tag associated to multiple categories. Filter by each of the categories"""
        for cat in (5, 6):
            r = self.client.get('/%scategory%d' % (_('questions/'), cat))
            self.assertEqual(200, r.status_code)
            for t in Tag.objects.exclude(used_count=0).exclude(name=u"tag7"):
                self.assertNotContains(r, t.name)
            self.assertContains(r, u"tag7")

    def test_filter_categories_subtree(self):
        """Selection of tags associated to sub-categories of a given category."""
        r = self.client.get('/%scategory9' % _('questions/'))
        self.assertEqual(200, r.status_code)
        for t in Tag.objects.exclude(used_count=0).exclude(
                name__in=[u"tagA", u"tagB"]
                ):
            self.assertNotContains(r, t.name)
        self.assertContains(r, u"tagA")
        self.assertContains(r, u"tagB")

        # filtering by the sub-category should show only tags associated with
        # it:
        r = self.client.get('/%scategory10' % _('questions/'))
        self.assertEqual(200, r.status_code)
        for t in Tag.objects.exclude(used_count=0).exclude(name=u"tagB"):
            self.assertNotContains(r, t.name)
        self.assertContains(r, u"tagB")
