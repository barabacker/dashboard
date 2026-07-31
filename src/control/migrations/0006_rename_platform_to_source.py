from django.db import migrations


class Migration(migrations.Migration):
    """Renames the proxy model, not a table: `Platform` has never had one of its own.

    `RenameModel` — not the `DeleteModel` + `CreateModel` a non-interactive `makemigrations`
    would generate for a plain class rename — because `RenameModel` is what lets Django's
    contenttypes framework update the existing `ContentType` row in place instead of replacing
    it. Replacing it would orphan any admin `LogEntry` history recorded against the old
    `ContentType` row. `AlterModelOptions` follows because the model's `verbose_name` also
    changed in the same rename; without it `makemigrations --check --dry-run` still reports a
    pending change.

    What `RenameModel` does *not* do, verified by hand when this migration was applied: it
    leaves the four `add_platform`/`change_platform`/`delete_platform`/`view_platform`
    `Permission` rows in place under their old codenames rather than renaming them, and it does
    not move any user's or group's existing grants over to the new `*_source` codenames Django
    creates on the next `migrate`. Applying this migration to a database with real permission
    grants (as opposed to a fresh one) needs a manual follow-up: reassign each grant from the
    old-codename `Permission` objects to the new-codename ones, then it is safe to delete the
    old ones once nothing references them.
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
