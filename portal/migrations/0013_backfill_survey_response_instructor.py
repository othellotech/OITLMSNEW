from django.db import migrations


def backfill_survey_response_instructor(apps, schema_editor):
    """Fixes the 'blank instructor rating' bug: any SurveyResponse saved
    before its course had an instructor linked was left with instructor=NULL
    forever (the model only sets it once, at creation). This walks every
    such row and fills it in from the course's current instructor, so
    existing ratings actually show up on the instructor's dashboard."""
    SurveyResponse = apps.get_model('portal', 'SurveyResponse')
    fixed = 0
    for response in SurveyResponse.objects.filter(instructor__isnull=True).select_related('course'):
        first_instructor = response.course.instructors.first()
        if first_instructor:
            response.instructor_id = first_instructor.id
            response.save(update_fields=['instructor'])
            fixed += 1
    if fixed:
        print(f'Backfilled instructor on {fixed} SurveyResponse row(s).')


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0012_assignedtask_required_lesson_count_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_survey_response_instructor, noop_reverse),
    ]
