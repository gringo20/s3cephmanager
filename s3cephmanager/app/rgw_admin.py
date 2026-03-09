"""Ceph RGW Admin Ops API client with SigV4 signing.

All Admin Ops parameters travel as URL query-string params (not a request body).
The helper `_req` keeps query params in a single dict so SigV4 signing and the
actual HTTP request always see the same canonical query string.

Quota note
----------
Ceph reports quota sizes in *bytes* (field ``max_size``) and *kilobytes*
(field ``max_size_kb``).  We read ``max_size_kb`` for display and write
``max-size-kb`` on save; both old and new Ceph versions understand this.

Error handling
--------------
All non-2xx responses raise ``RGWError`` with the Ceph error code and message
extracted from the JSON body when available.
"""
from __future__ import annotations

import json as _json
import logging
from typing import Any, Optional

import requests
import urllib3
from botocore.auth import SigV4Auth, UNSIGNED_PAYLOAD as _UNSIGNED_PAYLOAD
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = logging.getLogger("cephs3mgr.rgw")


# ── SigV4 signing helper ──────────────────────────────────────────────────────

class _RGWAdminAuth(SigV4Auth):
    """SigV4Auth that uses UNSIGNED-PAYLOAD for the canonical payload hash.

    boto3's S3 client uses UNSIGNED-PAYLOAD (not the actual SHA-256 of the
    body) in the canonical request.  Ceph RGW Admin API enforces the same
    convention: it expects the ``x-amz-content-sha256`` header to be present
    and set to ``UNSIGNED-PAYLOAD``.  Using the actual empty-body hash
    (``e3b0c44298...``) causes ``SignatureDoesNotMatch`` even when the key
    and secret are correct.
    """

    def payload(self, request: AWSRequest) -> str:  # type: ignore[override]
        return _UNSIGNED_PAYLOAD


# ── Custom exception ──────────────────────────────────────────────────────────

class RGWError(Exception):
    """Raised when the RGW Admin API returns a non-2xx response."""


# ── Client ────────────────────────────────────────────────────────────────────

class RGWAdminClient:
    """Thin wrapper around the Ceph RGW Admin Ops REST API."""

    def __init__(
        self,
        admin_endpoint: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        verify_ssl: bool = True,
    ) -> None:
        self.base_url    = admin_endpoint.rstrip("/")
        self.credentials = Credentials(access_key, secret_key)
        self.region      = region
        self.verify_ssl  = verify_ssl
        self._session    = requests.Session()

    # ── Core request helper ───────────────────────────────────────────────────

    def _req(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
    ) -> Any:
        """Sign and execute one Admin Ops request.

        *path* is relative to ``/admin``, e.g. ``"/user"`` or ``"/bucket"``.
        Some RGW paths embed an action qualifier after ``?``
        (e.g. ``"/user?quota"``, ``"/user?key"``, ``"/user?subuser"``).
        These tokens are extracted and merged into the query-string params
        dict *before* SigV4 signing so that every query parameter that will
        appear in the real HTTP request is also present in the canonical
        query string.  Omitting them causes ``SignatureDoesNotMatch`` even
        when the credentials are correct.

        *params* are placed in the query string (never the request body).
        All param values are coerced to ``str`` so botocore can build a
        consistent canonical query string.
        """
        # Promote any action-qualifier embedded in the path into the qp dict.
        # "/user?quota"  → path_only="/user", embedded={"quota": ""}
        # "/user?key"    → path_only="/user", embedded={"key": ""}
        if "?" in path:
            path_only, qs = path.split("?", 1)
            embedded: dict = {}
            for token in qs.split("&"):
                if "=" in token:
                    k, v = token.split("=", 1)
                    embedded[k] = v
                elif token:
                    embedded[token] = ""
        else:
            path_only = path
            embedded  = {}

        url  = f"{self.base_url}/admin{path_only}"
        qp   = {**embedded, **{k: str(v) for k, v in (params or {}).items()}}
        log.debug("RGW %s /admin%s params=%s", method.upper(), path_only, list(qp.keys()))

        # Sign with SigV4 using UNSIGNED-PAYLOAD convention (matches boto3 S3).
        # The x-amz-content-sha256 header must be present and signed;
        # Ceph RGW Admin API returns SignatureDoesNotMatch if it is absent
        # or if the actual SHA-256 hash is used instead of UNSIGNED-PAYLOAD.
        aws_req = AWSRequest(
            method=method.upper(), url=url, params=qp, data=b"",
            headers={"x-amz-content-sha256": _UNSIGNED_PAYLOAD},
        )
        _RGWAdminAuth(self.credentials, "s3", self.region).add_auth(aws_req)

        resp = self._session.request(
            method, url,
            headers=dict(aws_req.headers),
            params=qp,
            verify=self.verify_ssl,
            timeout=30,
        )

        if not resp.ok:
            # Log full response body so the exact Ceph error code is visible
            # (SignatureDoesNotMatch / AccessDenied / InvalidAccessKeyId …)
            log.warning(
                "RGW %s /admin%s → HTTP %s  body=%r",
                method.upper(), path_only, resp.status_code,
                resp.text[:300],
            )
            _raise_rgw_error(resp)

        return resp.json() if resp.content else {}

    # ── Users ─────────────────────────────────────────────────────────────────

    def list_users(self) -> list[str]:
        result = self._req("GET", "/metadata/user")
        return result if isinstance(result, list) else []

    def get_user(self, uid: str) -> dict:
        return self._req("GET", "/user", {"uid": uid})

    def get_user_stats(self, uid: str) -> dict:
        """Returns user info including ``stats`` sub-dict."""
        return self._req("GET", "/user", {"uid": uid, "stats": "true"})

    def create_user(
        self,
        uid: str,
        display_name: str,
        email: str = "",
        max_buckets: int = 1000,
        generate_key: bool = True,
    ) -> dict:
        params: dict = {
            "uid":           uid,
            "display-name":  display_name,
            "max-buckets":   max_buckets,
            "generate-key":  "true" if generate_key else "false",
        }
        if email:
            params["email"] = email
        return self._req("PUT", "/user", params)

    def modify_user(self, uid: str, **kwargs) -> dict:
        """Update one or more user fields.  Keyword args map to API params."""
        params = {"uid": uid}
        params.update(kwargs)
        return self._req("POST", "/user", params)

    def delete_user(self, uid: str, purge_data: bool = False) -> dict:
        return self._req("DELETE", "/user", {
            "uid":        uid,
            "purge-data": "true" if purge_data else "false",
        })

    def suspend_user(self, uid: str, suspended: bool = True) -> dict:
        return self._req("POST", "/user", {
            "uid":       uid,
            "suspended": "1" if suspended else "0",
        })

    # ── Keys ──────────────────────────────────────────────────────────────────

    def create_key(
        self,
        uid: str,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
    ) -> list[dict]:
        """Generate (or import) an S3 key pair.  Returns the full key list."""
        params: dict = {"uid": uid, "key-type": "s3", "generate-key": "true"}
        if access_key:
            params["access-key"] = access_key
        if secret_key:
            params["secret-key"] = secret_key
        result = self._req("PUT", "/user?key", params)
        return result if isinstance(result, list) else []

    def delete_key(self, uid: str, access_key: str) -> None:
        self._req("DELETE", "/user?key", {
            "uid":        uid,
            "key-type":   "s3",
            "access-key": access_key,
        })

    # ── Quota ─────────────────────────────────────────────────────────────────

    def get_user_quota(self, uid: str, quota_type: str = "user") -> dict:
        """Return quota config dict with keys: enabled, max_size_kb, max_objects."""
        return self._req("GET", "/user?quota", {
            "uid":        uid,
            "quota-type": quota_type,
        })

    def set_user_quota(
        self,
        uid: str,
        quota_type: str = "user",
        max_size_kb: int = -1,
        max_objects: int = -1,
        enabled: bool = True,
    ) -> None:
        self._req("PUT", "/user?quota", {
            "uid":         uid,
            "quota-type":  quota_type,
            "max-size-kb": max_size_kb,
            "max-objects": max_objects,
            "enabled":     "true" if enabled else "false",
        })

    # ── Buckets (admin view) ──────────────────────────────────────────────────

    def list_buckets(self, uid: Optional[str] = None) -> list[str]:
        params: dict = {}
        if uid:
            params["uid"] = uid
        result = self._req("GET", "/bucket", params)
        return result if isinstance(result, list) else []

    def get_bucket_info(self, bucket: str) -> dict:
        return self._req("GET", "/bucket", {"bucket": bucket})

    def remove_bucket(self, bucket: str, purge_objects: bool = False) -> dict:
        return self._req("DELETE", "/bucket", {
            "bucket":        bucket,
            "purge-objects": "true" if purge_objects else "false",
        })

    def link_bucket(self, bucket: str, uid: str, bucket_id: str) -> dict:
        return self._req("PUT", "/bucket", {
            "bucket":    bucket,
            "uid":       uid,
            "bucket-id": bucket_id,
        })

    # ── Subusers ──────────────────────────────────────────────────────────────

    def create_subuser(
        self,
        uid: str,
        subuser: str,
        permissions: str = "full",
    ) -> dict:
        return self._req("PUT", "/user?subuser", {
            "uid":             uid,
            "subuser":         subuser,
            "access":          permissions,
            "key-type":        "s3",
            "generate-secret": "true",
        })

    def delete_subuser(
        self,
        uid: str,
        subuser: str,
        purge_keys: bool = True,
    ) -> dict:
        return self._req("DELETE", "/user?subuser", {
            "uid":        uid,
            "subuser":    subuser,
            "purge-keys": "true" if purge_keys else "false",
        })

    # ── Usage / Stats ─────────────────────────────────────────────────────────

    def get_usage(self, uid: Optional[str] = None) -> dict:
        params: dict = {"show-entries": "true", "show-summary": "true"}
        if uid:
            params["uid"] = uid
        return self._req("GET", "/usage", params)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _raise_rgw_error(resp: requests.Response) -> None:
    """Parse Ceph JSON error body and raise RGWError with a readable message."""
    try:
        body = resp.json()
        code = body.get("Code") or body.get("code") or str(resp.status_code)
        msg  = body.get("Message") or body.get("message") or resp.reason or ""
    except (ValueError, KeyError):
        code = str(resp.status_code)
        msg  = resp.text or resp.reason or ""
    raise RGWError(f"{code}: {msg}" if msg else code)


# ── Factory ───────────────────────────────────────────────────────────────────

def get_rgw_from_conn(conn: dict) -> Optional[RGWAdminClient]:
    """Build an RGWAdminClient from an active connection dict.

    Returns ``None`` if the connection has no ``admin_endpoint`` set.
    """
    ep = conn.get("admin_endpoint", "").strip()
    if not ep:
        return None
    return RGWAdminClient(
        admin_endpoint=ep,
        access_key=conn["access_key"],
        secret_key=conn["secret_key"],
        region=conn.get("region", "us-east-1"),
        verify_ssl=conn.get("verify_ssl", True),
    )
