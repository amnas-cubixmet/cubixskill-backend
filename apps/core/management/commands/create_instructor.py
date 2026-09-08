from academy.models import Academy
from django.core.management.base import BaseCommand
from users_roles.models import SystemRoleCode, User


class Command(BaseCommand):
    help = 'Creates default Instructor / Academy Admin account'

    def add_arguments(self, parser):
        parser.add_argument('--email', type=str, default='instructor@cubixskill.com', help='Instructor email')
        parser.add_argument('--password', type=str, default='Password123!', help='Instructor password')
        parser.add_argument('--name', type=str, default='Demo Instructor', help='Instructor full name')
        parser.add_argument('--academy-slug', type=str, default='cubixskill-academy', help='Academy slug')

    def handle(self, *args, **options):
        email = options['email']
        password = options['password']
        name = options['name']
        academy_slug = options['academy_slug']

        academy, created = Academy.objects.get_or_create(
            slug=academy_slug,
            defaults={
                'name': 'CubixSkill Main Academy',
                'email': 'admin@cubixskill.com',
                'phone': '+1234567890',
                'is_active': True,
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created Academy: {academy.name} ({academy.slug})"))

        user, user_created = User.objects.get_or_create(
            email=email,
            defaults={
                'full_name': name,
                'role_code': SystemRoleCode.ACADEMY_ADMIN,
                'academy': academy,
                'is_email_verified': True,
                'password_setup_completed': True,
                'is_active': True,
                'is_staff': True,
            }
        )

        user.set_password(password)
        user.is_email_verified = True
        user.password_setup_completed = True
        user.is_active = True
        user.academy = academy
        user.role_code = SystemRoleCode.ACADEMY_ADMIN
        user.save()

        if user_created:
            self.stdout.write(self.style.SUCCESS(f"Successfully created instructor user: {email}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Successfully updated instructor user: {email}"))
