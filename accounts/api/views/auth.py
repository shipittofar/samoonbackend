from rest_framework import status, serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework.generics import (
    CreateAPIView,
    ListAPIView,
    RetrieveAPIView,
    UpdateAPIView,
    DestroyAPIView,
)
from drf_spectacular.utils import OpenApiExample, extend_schema

from accounts.models import OTPType
from accounts.selectors import UserDataAccessLayer
from accounts.services import (
    OTPBusinessLogiclayer,
    AuthBusinessLogicLayer,
    PasswordAuthBusinessLogicLayer,
    ProfileBusinessLogicLayer,
    UserBusinessLogicLayer,
    ForgetPasswordBusinessLogicLayer,
    PhoneVerificationBusinessLogicLayer,
    EmailVerificationBusinessLogicLayer,
    AccountVerificationBusinessLogicLayer,
)
from accounts.api.serializers.request import (
    SendOTPInputSerializer,
    VerifyOTPInputSerializer,
    SetPasswordInputSerializer,
    ChangePasswordInputSerializer,
    PasswordLoginInputSerializer,
    UpdateProfileInputSerializer,
    SetAvatarInputSerializer,
    ForgetPasswordRequestInputSerializer,
    ForgetPasswordConfirmInputSerializer,
    PhoneVerificationRequestInputSerializer,
    PhoneVerificationConfirmInputSerializer,
    EmailVerificationRequestInputSerializer,
    EmailVerificationConfirmInputSerializer,
    RegisterInputSerializer,
    LogoutInputSerializer,
)
from accounts.api.serializers.response import (
    VerifyOTPOutputSerializer,
    TokenOutputSerializer,
    UserOutputSerializer,
    AccountVerifyOutputSerializer,
    UserMeOutputSerializer,
)
from access.services.rbac_session_bll import rbac_session_bll
from core.exceptions import (
    UserInactiveException,
)


otp_bll = OTPBusinessLogiclayer()
auth_bll = AuthBusinessLogicLayer()
password_auth_bll = PasswordAuthBusinessLogicLayer()
profile_bll = ProfileBusinessLogicLayer()
user_bll = UserBusinessLogicLayer()
user_dal = UserDataAccessLayer()
forget_password_bll = ForgetPasswordBusinessLogicLayer()
phone_verification_bll = PhoneVerificationBusinessLogicLayer()
email_verification_bll = EmailVerificationBusinessLogicLayer()
account_verification_bll = AccountVerificationBusinessLogicLayer()


# ---------- Auth - authentication ----------

@extend_schema(
    tags=["Auth - authentication"],
    summary="Send OTP",
    description="Generate and send a one-time password to a phone number or email for login/signup.",
)
class SendOTPView(CreateAPIView):
    serializer_class = SendOTPInputSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        otp_bll.generate(
            identifier=serializer.validated_data["identifier"],
            otp_type=OTPType.LOGIN_SIGNUP,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["Auth - authentication"],
    summary="Verify OTP & Login/Signup",
    description="Verify the sent OTP code. If no account exists for that identifier, a new account is created and tokens are issued.",
)
class VerifyOTPView(CreateAPIView):
    serializer_class = VerifyOTPInputSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        otp_bll.verify(identifier=data["identifier"], code=data["code"], otp_type=OTPType.LOGIN_SIGNUP)
        user = user_dal.get_by_identifier(data["identifier"])

        if user is None:
            return Response(
                VerifyOTPOutputSerializer({"is_new_user": True, "tokens": None, "user": None}).data,
                status=status.HTTP_200_OK,
            )

        if not user.is_active:
            raise UserInactiveException()

        tokens = auth_bll.issue_tokens(user)
        return Response(
            VerifyOTPOutputSerializer({"is_new_user": False, "tokens": tokens, "user": user}).data,
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Auth - authentication"],
    summary="Register",
    description="Complete signup after OTP verification. Requires email or phone_number "
                "(whichever was verified via OTP) plus first_name/last_name.",
)
class RegisterUserView(CreateAPIView):
    serializer_class = RegisterInputSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = auth_bll.register(
            identifier=data["identifier"],
            is_email=data["is_email"],
            first_name=data["first_name"],
            last_name=data.get("last_name", ""),
            country_code=data.get("country_code"),
        )
        tokens = auth_bll.issue_tokens(user)
        return Response(
            VerifyOTPOutputSerializer({"is_new_user": True, "tokens": tokens, "user": user}).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Auth - authentication"],
    summary="Logout",
    description="Blacklist the given refresh token to end the session.",
)
class LogoutView(CreateAPIView):
    serializer_class = LogoutInputSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        auth_bll.logout(serializer.validated_data["refresh"])
        return Response(status=status.HTTP_205_RESET_CONTENT)


@extend_schema(
    tags=["Auth - authentication"],
    summary="Login with Password",
    description="Log in with email and password, or phone number (with country_code) and password. "
                "Provide exactly one of email or phone_number.",
)
class PasswordLoginView(CreateAPIView):
    serializer_class = PasswordLoginInputSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        tokens = password_auth_bll.login(
            identifier=data["identifier"],
            is_email=data["is_email"],
            password=data["password"],
        )
        return Response(TokenOutputSerializer(tokens).data, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Auth - authentication"],
    summary="Current User",
    description="Retrieve the authenticated user's own profile.",
)
class MeView(RetrieveAPIView):
    serializer_class = UserMeOutputSerializer
    permission_classes = [IsAuthenticated]

    def retrieve(self, request, *args, **kwargs):
        payload = rbac_session_bll.build_me(user=request.user, request=request)
        serializer = self.get_serializer(payload, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

# ---------- Auth - password ----------

@extend_schema(
    tags=["Auth - password"],
    summary="Set Password",
    description="Set a password for the authenticated user. Only allowed once, the first time. "
                "Subsequent password changes must go through the Change Password endpoint.",
)
class SetPasswordView(CreateAPIView):
    serializer_class = SetPasswordInputSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        password_auth_bll.set_password(
            user=request.user,
            password=data["password"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["Auth - password"],
    summary="Change Password",
    description="Change the authenticated user's password by providing the current password.",
)
class ChangePasswordView(CreateAPIView):
    serializer_class = ChangePasswordInputSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        password_auth_bll.change_password(
            user=request.user,
            old_password=data["old_password"],
            new_password=data["new_password"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["Auth - password"],
    summary="Request Forget Password",
    description="Send a verification code to the given phone number to recover a forgotten password.",
)
class ForgetPasswordRequestView(CreateAPIView):
    serializer_class = ForgetPasswordRequestInputSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        forget_password_bll.request_reset(phone_number=serializer.validated_data["phone_number"])
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["Auth - password"],
    summary="Confirm Forget Password",
    description="Verify the sent code and set a new password.",
)
class ForgetPasswordConfirmView(CreateAPIView):
    serializer_class = ForgetPasswordConfirmInputSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        forget_password_bll.confirm_reset(
            phone_number=data["phone_number"],
            code=data["code"],
            new_password=data["new_password"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------- Auth - verification ----------

@extend_schema(
    tags=["Auth - verification"],
    summary="Request Phone Verification",
    description="Send a verification code to register a phone number. If the user already has a phone number set, it cannot be changed.",
)
class RequestPhoneVerificationView(CreateAPIView):
    serializer_class = PhoneVerificationRequestInputSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone_verification_bll.request_verification(user=request.user, **serializer.validated_data)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["Auth - verification"],
    summary="Confirm Phone Verification",
    description="Verify the code and permanently set the phone number on the account (only if not already set).",
)
class ConfirmPhoneVerificationView(CreateAPIView):
    serializer_class = PhoneVerificationConfirmInputSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = phone_verification_bll.confirm_verification(user=request.user, **serializer.validated_data)
        return Response(
            UserOutputSerializer(user, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Auth - verification"],
    summary="Request Email Verification",
    description="Send a verification code to register an email. If the user already has an email set, it cannot be changed.",
)
class RequestEmailVerificationView(CreateAPIView):
    serializer_class = EmailVerificationRequestInputSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email_verification_bll.request_verification(user=request.user, **serializer.validated_data)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["Auth - verification"],
    summary="Confirm Email Verification",
    description=(
        "Confirm a 6-digit email OTP and permanently attach that email to the "
        "authenticated user (only if the account does not already have an email).\n\n"
        "**HTTP 200 means:** the OTP was valid, the email was saved on the user, "
        "and the response body is that updated user (`UserOutputSerializer`). "
        "The `email` field is the confirmed address.\n\n"
        "**`is_verified` is not the email-OTP result.** It is account-level "
        "profile completeness (`first_name`, `last_name`, `phone_number`, `email`) "
        "and is set only by `POST /api/auth/verify-account/`. After a successful "
        "email confirm, `is_verified` may still be `false`.\n\n"
        "This endpoint does not issue tokens, return a success message envelope, "
        "or mark the account verified."
    ),
    request=EmailVerificationConfirmInputSerializer,
    responses={200: UserOutputSerializer},
    examples=[
        OpenApiExample(
            "Confirm email OTP",
            value={"email": "user@example.com", "code": "123456"},
            request_only=True,
        ),
        OpenApiExample(
            "Email attached; account not necessarily verified",
            value={
                "id": "00000000-0000-0000-0000-000000000001",
                "email": "user@example.com",
                "phone_number": None,
                "first_name": "John",
                "last_name": "Doe",
                "avatar": None,
                "role": "customer",
                "is_verified": False,
                "is_superuser": False,
                "created_at": "2026-01-01T12:00:00Z",
            },
            response_only=True,
            status_codes=["200"],
        ),
    ],
)
class ConfirmEmailVerificationView(CreateAPIView):
    serializer_class = EmailVerificationConfirmInputSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = email_verification_bll.confirm_verification(user=request.user, **serializer.validated_data)
        return Response(
            UserOutputSerializer(user, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Auth - verification"],
    summary="Verify Account Completion",
    description=(
        "Account-level verification: if `first_name`, `last_name`, `phone_number`, "
        "and `email` are all set, sets `is_verified` to true. Otherwise returns "
        "`is_verified: false` and `missing_fields`.\n\n"
        "This is not email OTP confirmation. Attaching an email via "
        "`POST /api/auth/verify-email/confirm/` does not set `is_verified`. "
        "Always HTTP 200; incomplete profiles are not an error."
    ),
    responses={200: AccountVerifyOutputSerializer},
)
class VerifyAccountView(CreateAPIView):
    serializer_class = serializers.Serializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        is_verified, missing_fields = account_verification_bll.verify_account(request.user)
        output = AccountVerifyOutputSerializer({
            "is_verified": is_verified,
            "missing_fields": missing_fields,
        })
        return Response(output.data, status=status.HTTP_200_OK)


# ---------- Accounts - users ----------

@extend_schema(
    tags=["Accounts - users"],
    summary="List Users",
    description="Retrieve the list of all registered users.",
)
class UserListView(ListAPIView):
    serializer_class = UserOutputSerializer
    permission_classes = [IsAuthenticated]  # RBAC to be added later

    def get_queryset(self):
        return user_bll.list_users()


@extend_schema(
    tags=["Accounts - users"],
    summary="Retrieve User by ID",
    description="Retrieve a single user's data by their id.",
)
class UserDetailView(RetrieveAPIView):
    serializer_class = UserOutputSerializer
    permission_classes = [IsAuthenticated]  # RBAC to be added later
    lookup_url_kwarg = "user_id"

    def get_object(self):
        return user_bll.get_user(self.kwargs["user_id"])


# ---------- Accounts - profile ----------

@extend_schema(
    tags=["Accounts - profile"],
    summary="Update Profile",
    description="Update the authenticated user's basic profile fields (first_name, last_name).",
)
class UpdateProfileView(UpdateAPIView):
    serializer_class = UpdateProfileInputSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = profile_bll.update_profile(request.user, **serializer.validated_data)
        return Response(
            UserOutputSerializer(user, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Accounts - profile"],
    summary="Soft Delete Account",
    description="Soft delete the authenticated user's account. The account becomes inactive and can no longer log in normally.",
)
class SoftDeleteAccountView(DestroyAPIView):
    serializer_class = serializers.Serializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    def destroy(self, request, *args, **kwargs):
        profile_bll.soft_delete(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------- Accounts - avatar ----------

@extend_schema(
    tags=["Accounts - avatar"],
    summary="Set / Change Avatar",
    description="Upload a new avatar for the authenticated user. If an avatar already exists, it is replaced.",
)
class SetAvatarView(UpdateAPIView):
    serializer_class = SetAvatarInputSerializer
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = profile_bll.set_avatar(
            request.user,
            avatar=data.get("avatar"),
            avatar_asset_id=data.get("avatar_asset_id"),
            avatar_provided="avatar" in data,
            avatar_asset_id_provided="avatar_asset_id" in data,
        )
        return Response(
            UserOutputSerializer(user, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Accounts - avatar"],
    summary="Delete Avatar",
    description="Remove the authenticated user's current avatar.",
)
class DeleteAvatarView(DestroyAPIView):
    serializer_class = serializers.Serializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    def destroy(self, request, *args, **kwargs):
        user = profile_bll.delete_avatar(request.user)
        return Response(
            UserOutputSerializer(user, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )
