import os
from django.db import migrations

def create_superuser_if_needed(apps, schema_editor):
    User = apps.get_model('portal', 'User')
    
    # Only create if NO users exist at all (fresh database)
    if User.objects.count() == 0:
        admin_password = os.environ.get('ADMIN_PASSWORD', 'default-password-change-me')
        User.objects.create_superuser(
            username='admin',
            email='analyticswithothello@gmail.com',
            password=admin_password,
            first_name='Adam',
            last_name='User'
        )
        print("✅ Superuser created successfully (fresh database)!")
    else:
        print(f"⚠️ Database already has {User.objects.count()} users. Skipping superuser creation.")

class Migration(migrations.Migration):
    dependencies = [
        ('portal', '0004_remove_course_instructor_remove_user_course_and_more'),
    ]

    operations = [
        migrations.RunPython(create_superuser_if_needed),
    ]