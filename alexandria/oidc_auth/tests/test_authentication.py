import hashlib
import json

import pytest
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from mozilla_django_oidc.contrib.drf import OIDCAuthentication
from requests.exceptions import HTTPError
from rest_framework import exceptions, status
from rest_framework.exceptions import AuthenticationFailed


@pytest.mark.parametrize("is_id_token", [True, False])
@pytest.mark.parametrize(
    "authentication_header,authenticated,error",
    [
        ("", False, False),
        ("Bearer", False, True),
        ("Bearer Too many params", False, True),
        ("Basic Auth", False, True),
        ("Bearer Token", True, False),
    ],
)
def test_authentication(
    db,
    rf,
    authentication_header,
    authenticated,
    error,
    is_id_token,
    requests_mock,
    settings,
):
    settings.OIDC_DRF_AUTH_BACKEND = (
        "alexandria.oidc_auth.authentication.AlexandriaAuthenticationBackend"
    )
    userinfo = {"sub": "1"}
    requests_mock.get(settings.OIDC_OP_USER_ENDPOINT, text=json.dumps(userinfo))

    if not is_id_token:
        userinfo = {"client_id": "test_client", "sub": "1"}
        requests_mock.get(
            settings.OIDC_OP_USER_ENDPOINT, status_code=status.HTTP_401_UNAUTHORIZED
        )
        requests_mock.post(
            settings.OIDC_OP_INTROSPECT_ENDPOINT, text=json.dumps(userinfo)
        )

    request = rf.get("/openid", HTTP_AUTHORIZATION=authentication_header)
    try:
        result = OIDCAuthentication().authenticate(request)
    except exceptions.AuthenticationFailed:
        assert error
    else:
        if result:
            key = "userinfo" if is_id_token else "introspection"
            user, auth = result
            assert user.is_authenticated
            assert (
                cache.get(f"auth.{key}.{hashlib.sha256(b'Token').hexdigest()}")
                == userinfo
            )


def test_authentication_idp_502(
    db, rf, requests_mock, settings,
):
    settings.OIDC_DRF_AUTH_BACKEND = (
        "alexandria.oidc_auth.authentication.AlexandriaAuthenticationBackend"
    )
    requests_mock.get(
        settings.OIDC_OP_USER_ENDPOINT, status_code=status.HTTP_502_BAD_GATEWAY
    )

    request = rf.get("/openid", HTTP_AUTHORIZATION="Bearer Token")
    with pytest.raises(HTTPError):
        OIDCAuthentication().authenticate(request)


def test_authentication_idp_missing_claim(
    db, rf, requests_mock, settings,
):
    settings.OIDC_DRF_AUTH_BACKEND = (
        "alexandria.oidc_auth.authentication.AlexandriaAuthenticationBackend"
    )
    settings.OIDC_USERNAME_CLAIM = "missing"
    userinfo = {"sub": "1"}
    requests_mock.get(settings.OIDC_OP_USER_ENDPOINT, text=json.dumps(userinfo))

    request = rf.get("/openid", HTTP_AUTHORIZATION="Bearer Token")
    with pytest.raises(AuthenticationFailed):
        OIDCAuthentication().authenticate(request)


def test_authentication_no_client(
    db, rf, requests_mock, settings,
):
    settings.OIDC_DRF_AUTH_BACKEND = (
        "alexandria.oidc_auth.authentication.AlexandriaAuthenticationBackend"
    )
    requests_mock.get(
        settings.OIDC_OP_USER_ENDPOINT, status_code=status.HTTP_401_UNAUTHORIZED
    )
    requests_mock.post(
        settings.OIDC_OP_INTROSPECT_ENDPOINT, text=json.dumps({"sub": "1"})
    )

    request = rf.get("/openid", HTTP_AUTHORIZATION="Bearer Token")
    with pytest.raises(AuthenticationFailed):
        OIDCAuthentication().authenticate(request)


@pytest.mark.parametrize("debug", [True, False])
def test_authentication_dev(
    db, rf, requests_mock, settings, debug,
):
    settings.DEBUG = debug

    request = rf.get("/openid", HTTP_AUTHORIZATION="Bearer Token")
    if debug:
        user, _ = OIDCAuthentication().authenticate(request)
        assert user.groups == ["dev-group", "secondary-group"]
        assert user.username == "dev"
    else:
        with pytest.raises(ImproperlyConfigured) as exc:
            user = OIDCAuthentication().authenticate(request)
        assert exc.match("The Dev auth backend can only be used in DEBUG mode!")
