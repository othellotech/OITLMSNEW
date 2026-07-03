from django.db import migrations

def backfill_unlocks(apps, schema_editor):
    PlaylistAccessCode = apps.get_model('portal', 'PlaylistAccessCode')
    PlaylistUnlock = apps.get_model('portal', 'PlaylistUnlock')

    used_codes = PlaylistAccessCode.objects.filter(is_used=True, user__isnull=False)
    created = 0
    for pac in used_codes:
        _, was_created = PlaylistUnlock.objects.get_or_create(
            user_id=pac.user_id, playlist_id=pac.playlist_id,
            defaults={'source': 'single_code'}
        )
        created += int(was_created)
    print(f"Backfilled {created} PlaylistUnlock rows.")

def reverse_noop(apps, schema_editor):
    pass

class Migration(migrations.Migration):
    dependencies = [
        ('portal', '0008_multiplaylistaccesscode_playlistunlock'),
    ]
    operations = [migrations.RunPython(backfill_unlocks, reverse_noop)]