from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from accounts.models import MagicLinkToken, User


@admin.register(User)
class RentMeBroUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Role", {"fields": ("role",)}),)
    list_display = ("username", "email", "role", "is_staff")


@admin.register(MagicLinkToken)
class MagicLinkTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "expires_at", "used_at")
    readonly_fields = ("token_hash", "created_at")
