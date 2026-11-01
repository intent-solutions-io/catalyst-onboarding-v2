"""Exact Discord member/role endpoint boundary, with no implicit credential loading.

Tests inject the transport. The production factory requires reviewed configuration
and its separate release evidence; the shipped configuration remains disabled.
"""

import http.client
import json
import re
import ssl

from django.conf import settings
from django.utils.module_loading import import_string

ID = re.compile(r"[1-9][0-9]{16,19}\Z")
ROLES = ("Member", "Certified", "Leaders")


class CommunityError(Exception):
    def __init__(
        self,
        code="provider_unknown",
        *,
        status=None,
        retry_after=None,
        provider_code=None,
    ):
        self.code = code if re.fullmatch(r"[a-z_]{1,64}", code) else "provider_unknown"
        self.status, self.retry_after = status, retry_after
        self.provider_code = (
            provider_code
            if type(provider_code) is int and 0 <= provider_code <= 1_000_000
            else None
        )
        super().__init__(self.code)


class DiscordAPI:
    def __init__(self, guild_id, roles, call):
        if not ID.fullmatch(guild_id) or set(roles) != set(ROLES):
            raise CommunityError("invalid_scope")
        if len(set(roles.values())) != 3 or any(
            not ID.fullmatch(r) or r == guild_id for r in roles.values()
        ):
            raise CommunityError("invalid_roles")
        self.guild_id, self.roles, self.call = guild_id, dict(roles), call

    def member(self, user_id):
        if not ID.fullmatch(user_id):
            raise CommunityError("invalid_identity")
        try:
            result = self.call(
                f"/guilds/{self.guild_id}/members/{user_id}", "GET", None
            )
        except CommunityError as exc:
            if exc.status == 404 and exc.provider_code == 10007:
                return None
            raise
        if not isinstance(result, dict) or result.get("user", {}).get("id") != user_id:
            raise CommunityError("readback_identity_mismatch")
        roles, joined = result.get("roles"), result.get("joined_at")
        if (
            result["user"].get("bot")
            or not isinstance(roles, list)
            or any(not isinstance(r, str) or not ID.fullmatch(r) for r in roles)
        ):
            raise CommunityError("invalid_member_readback")
        if not isinstance(joined, str) or not joined:
            raise CommunityError("invalid_membership_epoch")
        return {
            "roles": {name for name, rid in self.roles.items() if rid in roles},
            "joined_at": joined,
        }

    def grant(self, user_id, role):
        self._role(user_id, role, "PUT")

    def revoke(self, user_id, role):
        self._role(user_id, role, "DELETE")

    def _role(self, user_id, role, method):
        if not ID.fullmatch(user_id) or role not in self.roles:
            raise CommunityError("unmanaged_role")
        self.call(
            f"/guilds/{self.guild_id}/members/{user_id}/roles/{self.roles[role]}",
            method,
            None,
        )


def provider():
    path = getattr(settings, "CATALYST_COMMUNITY_ADAPTER", "")
    if not path:
        raise CommunityError("not_configured")
    if path == "provisioning.community_adapter.LiveDiscord":
        from config.guards import community_problems

        if community_problems(settings, {}) or settings.CATALYST_ENV != "production":
            raise CommunityError("live_adapter_not_admitted")
    elif settings.CATALYST_ENV not in (
        "test",
        "development",
        "staging",
    ) or not path.startswith("tests."):
        raise CommunityError("invalid_adapter")
    result = import_string(path)()
    if not isinstance(result, DiscordAPI):
        raise CommunityError("invalid_adapter")
    return result


class HTTPSDiscord:
    """Fixed-origin, verified TLS; no proxy/environment discovery or redirects."""

    def __init__(self, token):
        if not isinstance(token, str) or not re.fullmatch(
            r"[A-Za-z0-9._-]{20,200}", token
        ):
            raise CommunityError("invalid_credential")
        self._token = token

    def __call__(self, path, method, payload):
        if (
            payload is not None
            or method not in ("GET", "PUT", "DELETE")
            or not re.fullmatch(
                r"/(?:users/@me|guilds/[0-9]{17,20}/(?:roles|members/[0-9]{17,20}(?:/roles/[0-9]{17,20})?))",
                path,
            )
        ):
            raise CommunityError("endpoint_refused")
        role_mutation = re.fullmatch(
            r"/guilds/[0-9]{17,20}/members/[0-9]{17,20}/roles/[0-9]{17,20}", path
        )
        if (role_mutation and method not in ("PUT", "DELETE")) or (
            not role_mutation and method != "GET"
        ):
            raise CommunityError("endpoint_method_refused")
        connection = http.client.HTTPSConnection(
            "discord.com", timeout=10, context=ssl.create_default_context()
        )
        try:
            connection.request(
                method,
                "/api/v10" + path,
                headers={
                    "Authorization": "Bot " + self._token,
                    "User-Agent": "CatalystCommunityAccess/1.0",
                    "Accept": "application/json",
                },
            )
            response = connection.getresponse()
            body = response.read(65537)
            if len(body) > 65536:
                raise CommunityError("response_too_large")
            if not 200 <= response.status < 300:
                retry = None
                provider_code = None
                try:
                    provider_code = json.loads(body).get("code")
                except ValueError, TypeError, AttributeError:
                    pass
                if response.status == 429:
                    try:
                        retry = min(
                            3600, max(1, float(json.loads(body)["retry_after"]))
                        )
                    except ValueError, TypeError, KeyError:
                        pass
                raise CommunityError(
                    "provider_refused",
                    status=response.status,
                    retry_after=retry,
                    provider_code=provider_code,
                )
            return json.loads(body) if body else None
        except CommunityError:
            raise
        except Exception:
            raise CommunityError("provider_unknown") from None
        finally:
            connection.close()


class LiveDiscord(DiscordAPI):
    def __init__(self):
        super().__init__(
            settings.CATALYST_COMMUNITY_GUILD_ID,
            settings.CATALYST_COMMUNITY_ROLE_IDS,
            HTTPSDiscord(settings.CATALYST_COMMUNITY_BOT_TOKEN),
        )
        self._scope_verified = False

    def _role(self, user_id, role, method):
        if not self._scope_verified:
            actor = self.call("/users/@me", "GET", None)
            if not actor.get("bot") or not ID.fullmatch(actor.get("id", "")):
                raise CommunityError("bot_identity_required")
            roles = self.call(f"/guilds/{self.guild_id}/roles", "GET", None)
            membership = self.call(
                f"/guilds/{self.guild_id}/members/{actor['id']}", "GET", None
            )
            by_id = {r["id"]: r for r in roles}
            assigned = {self.guild_id, *membership["roles"]}
            permissions = 0
            for rid in assigned:
                permissions |= int(by_id[rid]["permissions"])
            forbidden = sum(
                1 << bit for bit in (1, 2, 3, 4, 5, 7, 13, 17, 27, 29, 30, 33, 34, 40)
            )
            if permissions & forbidden or not permissions & (1 << 28):
                raise CommunityError("scoped_manage_roles_required")
            highest = max(by_id[rid]["position"] for rid in assigned)
            for rid in self.roles.values():
                target = by_id.get(rid)
                if target is None or target["managed"] or target["position"] >= highest:
                    raise CommunityError("role_hierarchy_refused")
                if int(target["permissions"]):
                    raise CommunityError("privileged_target_role_refused")
            self._scope_verified = True
        super()._role(user_id, role, method)


def read_member(api, user_id):
    return api.member(user_id)


def grant_role(api, user_id, role):
    api.grant(user_id, role)


def revoke_role(api, user_id, role):
    api.revoke(user_id, role)
