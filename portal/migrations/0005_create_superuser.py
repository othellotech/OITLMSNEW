import os
from django.db import migrations

def create_superuser(apps, schema_editor):
    User = apps.get_model('portal', 'User')
    
    # Check if superuser already exists
    if not User.objects.filter(email='analyticswithothello@gmail.com').exists():
        admin_password = os.environ.get('ADMIN_PASSWORD', 'default-password-change-me')
        User.objects.create_superuser(
            username='admin',
            email='analyticswithothello@gmail.com',
            password=admin_password,  # ← Now it works!
            first_name='Adam',
            last_name='User'
        )
        print("✅ Superuser created successfully!")
    else:
        print("⚠️ Superuser already exists.")

class Migration(migrations.Migration):
    dependencies = [
        ('portal', '0004_remove_course_instructor_remove_user_course_and_more'),
    ]

    operations = [
        migrations.RunPython(create_superuser),
    ]