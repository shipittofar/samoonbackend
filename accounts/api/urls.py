from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from accounts.api.views import (
    SendOTPView,
    VerifyOTPView,
    PasswordLoginView,
    SetPasswordView,
    ChangePasswordView,
    ForgetPasswordRequestView,
    ForgetPasswordConfirmView,
    RequestPhoneVerificationView,
    ConfirmPhoneVerificationView,
    RequestEmailVerificationView,
    ConfirmEmailVerificationView,
    VerifyAccountView,
    UserListView,
    UserDetailView,
    UpdateProfileView,
    SoftDeleteAccountView,
    SetAvatarView,
    DeleteAvatarView,
    RegisterUserView,
    LogoutView,
    MeView
)
from accounts.api.views.me_permissions import MePermissionsView
from accounts.api.views.me_effective_permissions import MeEffectivePermissionsView


app_name = "accounts"

urlpatterns = [
    # Auth - authentication
    path("send-otp/", SendOTPView.as_view(), name="send-otp"),
    path("verify-otp/", VerifyOTPView.as_view(), name="verify-otp"),
    path("register/", RegisterUserView.as_view(), name="register-user"),
    path("password-login/", PasswordLoginView.as_view(), name="password-login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", MeView.as_view(), name="me"),
    path("me/permissions/", MePermissionsView.as_view(), name="me-permissions"),
    path("me/effective-permissions/", MeEffectivePermissionsView.as_view(), name="me-effective-permissions"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),

    # Auth - password
    path("set-password/", SetPasswordView.as_view(), name="set-password"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),
    path("forget-password/request/", ForgetPasswordRequestView.as_view(),
         name="forget-password-request"),
    path("forget-password/confirm/", ForgetPasswordConfirmView.as_view(),
         name="forget-password-confirm"),

    # Auth - verification
    path("verify-phone/request/", RequestPhoneVerificationView.as_view(),
         name="verify-phone-request"),
    path("verify-phone/confirm/", ConfirmPhoneVerificationView.as_view(),
         name="verify-phone-confirm"),
    path("verify-email/request/", RequestEmailVerificationView.as_view(),
         name="verify-email-request"),
    path("verify-email/confirm/", ConfirmEmailVerificationView.as_view(),
         name="verify-email-confirm"),
    path("verify-account/", VerifyAccountView.as_view(), name="verify-account"),

    # Accounts - users
    path("users/", UserListView.as_view(), name="user-list"),
    path("users/<uuid:user_id>/", UserDetailView.as_view(), name="user-detail"),

    # Accounts - profile
    path("profile/update/", UpdateProfileView.as_view(), name="profile-update"),
    path("profile/delete/", SoftDeleteAccountView.as_view(), name="profile-delete"),

    # Accounts - avatar
    path("profile/avatar/", SetAvatarView.as_view(), name="avatar-set"),
    path("profile/avatar/delete/", DeleteAvatarView.as_view(), name="avatar-delete"),
]
