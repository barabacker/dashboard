from django.db import migrations


class Migration(migrations.Migration):
    """Renames the proxy model, not a table: `Platform` has never had one of its own.

    A single `RenameModel` operation — not the `DeleteModel` + `CreateModel` a non-interactive
    `makemigrations` would generate for a plain class rename — because `RenameModel` is what lets
    Django's contenttypes framework update the existing `ContentType` row in place instead of
    replacing it. Replacing it would orphan every `control.*_platform` permission already granted
    (e.g. to the `petr` user) and any admin `LogEntry` history recorded against the old
    `ContentType` row.
    """

    dependencies = [
        ("control", "0005_remove_job_collector_version_and_more"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="Platform",
            new_name="Source",
        ),
        migrations.AlterModelOptions(
            name="source",
            options={
                "ordering": ["name"],
                "proxy": True,
                "verbose_name": "Источник",
                "verbose_name_plural": "Источники",
            },
        ),
    ]
