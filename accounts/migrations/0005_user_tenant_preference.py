# Generated manually for user tenant branch preferences.

import uuid

from django.db import migrations, models
import django.db.models.deletion


def backfill_user_tenant_preferences(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    UserTenantPreference = apps.get_model("accounts", "UserTenantPreference")
    Branch = apps.get_model("tenants", "Branch")
    StaffMembership = apps.get_model("access", "StaffMembership")
    Owner = apps.get_model("tenants", "Owner")
    Tenant = apps.get_model("tenants", "Tenant")

    def user_tenant_ids(user):
        tenant_ids = set()
        try:
            owner = Owner.objects.get(user_id=user.id)
            tenant_ids.update(
                Tenant.objects.filter(owner_id=owner.id).values_list("id", flat=True)
            )
        except Owner.DoesNotExist:
            pass
        tenant_ids.update(
            StaffMembership.objects.filter(user_id=user.id, status="active")
            .values_list("tenant_id", flat=True)
        )
        return tenant_ids

    def user_can_access_branch(user, branch):
        try:
            owner = Owner.objects.get(user_id=user.id)
            if Tenant.objects.filter(id=branch.tenant_id, owner_id=owner.id).exists():
                return True
        except Owner.DoesNotExist:
            pass
        membership = StaffMembership.objects.filter(
            user_id=user.id,
            tenant_id=branch.tenant_id,
            status="active",
        ).first()
        if membership is None:
            return False
        StaffAssignment = apps.get_model("access", "StaffAssignment")
        StaffAssignmentLocation = apps.get_model("access", "StaffAssignmentLocation")
        assignments = StaffAssignment.objects.filter(
            membership_id=membership.id,
            status__in=["active", "future"],
        )
        for assignment in assignments:
            if assignment.all_locations:
                return True
            if StaffAssignmentLocation.objects.filter(
                assignment_id=assignment.id,
                branch_id=branch.id,
            ).exists():
                return True
        return False

    def resolve_fallback(user, tenant_id):
        for branch in Branch.objects.filter(tenant_id=tenant_id).order_by(
            "-is_default", "created_at"
        ):
            if user_can_access_branch(user, branch):
                return branch
        return None

    for user in User.objects.all().iterator():
        for tenant_id in user_tenant_ids(user):
            preferred_id = None
            if user.active_tenant_id and str(user.active_tenant_id) == str(tenant_id):
                if user.active_branch_id:
                    branch = Branch.objects.filter(pk=user.active_branch_id).first()
                    if branch and user_can_access_branch(user, branch):
                        preferred_id = branch.id
            if preferred_id is None and user.active_branch_id:
                branch = Branch.objects.filter(pk=user.active_branch_id).first()
                if (
                    branch
                    and str(branch.tenant_id) == str(tenant_id)
                    and user_can_access_branch(user, branch)
                ):
                    preferred_id = branch.id
            if preferred_id is None:
                fallback = resolve_fallback(user, tenant_id)
                preferred_id = fallback.id if fallback else None
            if preferred_id is None:
                continue
            UserTenantPreference.objects.update_or_create(
                user_id=user.id,
                tenant_id=tenant_id,
                defaults={"preferred_branch_id": preferred_id},
            )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_favorite"),
        ("tenants", "0007_branch_cuisines_amenities"),
        ("access", "0017_alter_permissionaudit_action"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserTenantPreference",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "preferred_branch",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="tenants.branch",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="user_branch_preferences",
                        to="tenants.tenant",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tenant_branch_preferences",
                        to="accounts.user",
                    ),
                ),
            ],
            options={
                "db_table": "user_tenant_preference",
            },
        ),
        migrations.AddIndex(
            model_name="usertenantpreference",
            index=models.Index(
                fields=["user", "tenant"], name="user_tenant_pref_user_tenant_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="usertenantpreference",
            index=models.Index(fields=["tenant"], name="user_tenant_pref_tenant_idx"),
        ),
        migrations.AddConstraint(
            model_name="usertenantpreference",
            constraint=models.UniqueConstraint(
                fields=("user", "tenant"), name="unique_user_tenant_branch_preference"
            ),
        ),
        migrations.RunPython(backfill_user_tenant_preferences, migrations.RunPython.noop),
    ]
