from django.test import TestCase, Client
from users_roles.models import User, SystemRoleCode, Role, Permission, RoleScope, RolePermission, UserPermissionOverride
from academy.models import Academy, AcademyStatus

class RootControlPanelRoutingTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.super_admin = User.objects.create_user(
            email="superadmin@cubixskill.com",
            password="Password123!",
            full_name="Super Admin User",
            role_code=SystemRoleCode.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True
        )
        self.staff_user = User.objects.create_user(
            email="staff.member@cubixskill.com",
            password="Password123!",
            full_name="Staff Member",
            role_code=SystemRoleCode.SUPER_ADMIN_STAFF,
            is_staff=True
        )
        self.student_user = User.objects.create_user(
            email="student@cubixskill.com",
            password="Password123!",
            full_name="Student User",
            role_code=SystemRoleCode.STUDENT
        )
        self.test_academy = Academy.objects.create(
            name="Test Apex Academy",
            email="info@apex.com",
            slug="test-apex-academy",
            status=AcademyStatus.ACTIVE
        )
        self.test_role = Role.objects.create(
            name="Test Custom Role",
            code="TEST_CUSTOM_ROLE",
            description="Custom test role",
            scope=RoleScope.ACADEMY,
            is_system_role=False,
            is_active=True
        )
        self.test_permission = Permission.objects.create(
            name="View Test",
            code="test.view",
            module="TEST"
        )
        RolePermission.objects.create(role=self.test_role, permission=self.test_permission)

    def test_unauthenticated_root_redirects_to_login(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/login/?next=/')

    def test_canonical_login_page_renders_200(self):
        response = self.client.get('/login/')
        self.assertEqual(response.status_code, 200)

    def test_authenticated_unauthorized_user_receives_403(self):
        self.client.force_login(self.student_user)
        response = self.client.get('/academies/')
        self.assertEqual(response.status_code, 403)

    def test_all_root_control_panel_routes_render_200_for_super_admin(self):
        self.client.force_login(self.super_admin)

        routes = [
            '/',
            '/academies/',
            '/academies/create/',
            f'/academies/{self.test_academy.id}/',
            f'/academies/{self.test_academy.id}/edit/',
            f'/academies/{self.test_academy.id}/delete/',
            '/users/',
            '/students/',
            '/students/create/',
            f'/students/{self.student_user.id}/',
            f'/students/{self.student_user.id}/edit/',
            f'/students/{self.student_user.id}/delete/',
            '/courses/',
            '/enrollments/',
            '/plans/',
            '/subscriptions/',
            '/features/',
            '/pricing/',
            '/credit-engine/',
            '/storage/',
            '/usage/',
            '/payments/',
            '/fees/',
            '/coupons/',
            '/credits/',
            '/websites/',
            '/staff/',
            '/super-admin-staff/',
            '/super-admin-staff/create/',
            f'/super-admin-staff/{self.staff_user.id}/',
            f'/super-admin-staff/{self.staff_user.id}/edit/',
            f'/super-admin-staff/{self.staff_user.id}/permissions/',
            f'/super-admin-staff/{self.staff_user.id}/delete/',
            '/roles/',
            '/roles/create/',
            f'/roles/{self.test_role.id}/',
            f'/roles/{self.test_role.id}/edit/',
            f'/roles/{self.test_role.id}/delete/',
            '/permissions/',
            '/support/',
            '/settings/',
        ]

        for route in routes:
            with self.subTest(route=route):
                response = self.client.get(route)
                expected_status = 302 if route in ['/enrollments/', '/features/', '/usage/', '/staff/', '/system/', '/jobs/'] else 200
                self.assertEqual(response.status_code, expected_status, f"Route {route} failed with status {response.status_code}")

    def test_student_create_post_flow(self):
        self.client.force_login(self.super_admin)
        response = self.client.post('/students/create/', {
            'full_name': 'Amal Ali',
            'email': 'amal.ali@example.com',
            'phone': '+91 98765 43210',
            'academy_id': str(self.test_academy.id),
            'is_active': 'true'
        })
        self.assertEqual(response.status_code, 302)
        created_student = User.objects.filter(email='amal.ali@example.com').first()
        self.assertIsNotNone(created_student)
        self.assertEqual(created_student.role_code, SystemRoleCode.STUDENT)
        self.assertEqual(created_student.academy, self.test_academy)

    def test_student_disable_flow(self):
        self.client.force_login(self.super_admin)
        response = self.client.post(f'/students/{self.student_user.id}/disable/')
        self.assertEqual(response.status_code, 302)
        self.student_user.refresh_from_db()
        self.assertFalse(self.student_user.is_active)

    def test_role_create_auto_code_flow(self):
        self.client.force_login(self.super_admin)
        response = self.client.post('/roles/create/', {
            'name': 'Academy Manager',
            'description': 'Manage academies in control panel',
            'is_active': 'true',
            'permissions': [str(self.test_permission.id)]
        })
        self.assertEqual(response.status_code, 302)
        created_role = Role.objects.filter(code='ACADEMY_MANAGER').first()
        self.assertIsNotNone(created_role)
        self.assertEqual(created_role.name, 'Academy Manager')
        self.assertEqual(created_role.code, 'ACADEMY_MANAGER')
