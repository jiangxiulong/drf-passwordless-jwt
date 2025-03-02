from datetime import timedelta
import re

from django.conf import settings
from django.utils import timezone
from drfpasswordless.models import CallbackToken
from drfpasswordless.views import ObtainAuthTokenFromCallbackToken
from drfpasswordless.views import ObtainEmailCallbackToken
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .consts import LONG_LIVE_TIME
from .serializers import EmailAuthWhiteListSerializer
from .serializers import JWTSerializer
from .testaccount import exists_test_account
from .testaccount import get_test_account_token
from .utils import generate_jwt


class ObtainEmailTokenView(ObtainEmailCallbackToken):
    serializer_class = EmailAuthWhiteListSerializer

    def post(self, request, *args, **kwargs):
        email = request.data["email"]
        if exists_test_account(email):
            return Response(
                {
                    "detail": f"test account email {email!r} available",
                },
            )

        return super().post(request, *args, **kwargs)


class ObtainJWTView(ObtainAuthTokenFromCallbackToken):
    def post(self, request, *args, **kwargs):
        email = request.data["email"]
        if exists_test_account(email):
            if request.data["token"] == get_test_account_token(email):
                return Response(
                    {
                        "email": email,
                        "token": generate_jwt(email),
                    },
                )

        resp = super().post(request, *args, **kwargs)
        token = generate_jwt(email)
        resp.data["email"] = email
        resp.data["token"] = token

        current_time = timezone.now()
        remove_time = current_time - timedelta(
            seconds=settings.OTP_TOKEN_CLEAN_SECONDS,
        )
        tokens = CallbackToken.objects.filter(created_at__lt=remove_time)
        tokens.delete()

        return resp


class VerifyJWTView(APIView):
    permission_classes = [AllowAny]
    serializer_class = JWTSerializer

    def post(self, request, *args, **kwargs):
        email = request.data.get("email")
        if email and exists_test_account(email):
            return Response(
                {
                    "email": email,
                    "exp": LONG_LIVE_TIME,
                },
            )

        serializer = self.serializer_class(
            data=request.data,
            context={"request": request},
        )
        if serializer.is_valid(raise_exception=False):
            return Response(
                serializer.validated_data["token"],
                status=status.HTTP_200_OK,
            )

        return Response(status=status.HTTP_401_UNAUTHORIZED)


class VerifyJWTHeaderView(APIView):
    permission_classes = [AllowAny]
    serializer_class = JWTSerializer

    def get(self, request, *args, **kwargs):
        request_method = request.headers.get("X-Forwarded-Method")

        if request_method == "OPTIONS":
            return Response(status=status.HTTP_200_OK)

        authorization_header = request.headers.get("Authorization")

        authorization_cookie = ""
        cookies = request.headers.get("Cookie")
        if cookies and 'Authorization' in cookies:
            match = re.search(r'Authorization=([^;]+)', cookies)
            if match:
                authorization_cookie = match.group(1)

        if not authorization_header and not authorization_cookie:
            return Response(
                status=status.HTTP_401_UNAUTHORIZED,
                data={"error": "Authorization header must be provided"},
            )

        authorization = ""
        if authorization_cookie:
            authorization = authorization_cookie
        if authorization_header:
            authorization = authorization_header

        try:
            _, token = authorization.split()
        except ValueError:
            return Response(
                status=status.HTTP_401_UNAUTHORIZED,
                data={"error": "Invalid Authorization header format"},
            )

        email = request.headers.get("x-email")
        if email and exists_test_account(email):
            return Response(
                {
                    "email": email,
                    "exp": LONG_LIVE_TIME,
                },
            )

        serializer = self.serializer_class(
            data={"token": token},
            context={"request": request},
        )
        if serializer.is_valid(raise_exception=False):
            return Response(
                serializer.validated_data["token"],
                status=status.HTTP_200_OK,
            )

        return Response(status=status.HTTP_401_UNAUTHORIZED)
