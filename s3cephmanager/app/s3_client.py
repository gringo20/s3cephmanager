"""S3 operations wrapper using boto3 (compatible with Ceph RGW)."""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from app.config import MULTIPART_THRESHOLD, MULTIPART_CHUNKSIZE
import humanize

log = logging.getLogger("cephs3mgr.s3")


def _make_client(endpoint: str, access_key: str, secret_key: str,
                 region: str = "us-east-1", verify_ssl: bool = True):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        verify=verify_ssl,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


class ProgressCallback:
    """Thread-safe upload/download progress tracker with speed + ETA.

    Callback signature: fn(pct, done_str, total_str, speed_str, eta_str)
    """

    def __init__(self, total: int, on_progress: Callable):
        self._total = total
        self._seen  = 0
        self._lock  = threading.Lock()
        self._cb    = on_progress
        self._start = time.monotonic()

    def __call__(self, bytes_amount: int) -> None:
        with self._lock:
            self._seen += bytes_amount
            elapsed = max(time.monotonic() - self._start, 0.001)
            pct     = (self._seen / self._total * 100) if self._total else 0.0
            speed   = self._seen / elapsed
            rem     = (self._total - self._seen) / speed if speed > 0 else 0
            self._cb(
                pct,
                humanize.naturalsize(self._seen),
                humanize.naturalsize(self._total),
                humanize.naturalsize(speed) + "/s",
                f"{int(rem)}s" if rem > 1 else "—",
            )


class S3Manager:
    def __init__(self, endpoint: str, access_key: str, secret_key: str,
                 region: str = "us-east-1", verify_ssl: bool = True,
                 public_endpoint: str = ""):
        log.debug("S3Manager connecting to %s (region=%s, ssl=%s)", endpoint, region, verify_ssl)
        self.client = _make_client(endpoint, access_key, secret_key, region, verify_ssl)
        # Separate boto3 client for presigned URL generation.
        # If a public/external endpoint is set, presigned URLs will contain
        # the public hostname so they can be opened by browsers outside k8s.
        # A separate client is required because SigV4 signs the Host header;
        # simply replacing the URL after signing would invalidate the signature.
        _pub = (public_endpoint or "").strip()
        if _pub and _pub.rstrip("/") != endpoint.rstrip("/"):
            log.debug("S3Manager presign client → %s", _pub)
            self._presign_client = _make_client(_pub, access_key, secret_key, region, verify_ssl)
        else:
            self._presign_client = self.client
        self._transfer_config = boto3.s3.transfer.TransferConfig(
            multipart_threshold=MULTIPART_THRESHOLD,
            multipart_chunksize=MULTIPART_CHUNKSIZE,
            max_concurrency=4,
        )

    # ── Buckets ───────────────────────────────────────────────────────────────

    def list_buckets(self) -> list[dict]:
        resp = self.client.list_buckets()
        return resp.get("Buckets", [])

    def create_bucket(self, name: str, region: str = "us-east-1") -> None:
        if region == "us-east-1":
            self.client.create_bucket(Bucket=name)
        else:
            self.client.create_bucket(
                Bucket=name,
                CreateBucketConfiguration={"LocationConstraint": region},
            )

    def delete_bucket(self, name: str, force: bool = False) -> None:
        if force:
            self._empty_bucket(name)
        self.client.delete_bucket(Bucket=name)

    def _empty_bucket(self, name: str) -> None:
        # versioned objects
        try:
            pag = self.client.get_paginator("list_object_versions")
            for page in pag.paginate(Bucket=name):
                objs = [
                    {"Key": v["Key"], "VersionId": v["VersionId"]}
                    for v in page.get("Versions", [])
                ] + [
                    {"Key": m["Key"], "VersionId": m["VersionId"]}
                    for m in page.get("DeleteMarkers", [])
                ]
                if objs:
                    self.client.delete_objects(Bucket=name, Delete={"Objects": objs})
        except ClientError:
            pass
        # non-versioned objects
        pag = self.client.get_paginator("list_objects_v2")
        for page in pag.paginate(Bucket=name):
            objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if objs:
                self.client.delete_objects(Bucket=name, Delete={"Objects": objs})

    def get_bucket_location(self, name: str) -> str:
        try:
            r = self.client.get_bucket_location(Bucket=name)
            return r.get("LocationConstraint") or "us-east-1"
        except ClientError:
            return "unknown"

    # ── Objects ───────────────────────────────────────────────────────────────

    def list_objects(self, bucket: str, prefix: str = "",
                     delimiter: str = "/", max_keys: int = 1000,
                     continuation_token: Optional[str] = None) -> dict:
        kwargs: dict = dict(Bucket=bucket, Prefix=prefix,
                            Delimiter=delimiter, MaxKeys=max_keys)
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token
        resp = self.client.list_objects_v2(**kwargs)
        return {
            "objects": resp.get("Contents", []),
            "prefixes": [p["Prefix"] for p in resp.get("CommonPrefixes", [])],
            "truncated": resp.get("IsTruncated", False),
            "next_token": resp.get("NextContinuationToken"),
        }

    def upload_fileobj(self, bucket: str, key: str, fileobj,
                       callback: Optional[Callable] = None) -> None:
        extra = {"ContentType": _guess_content_type(key)}
        self.client.upload_fileobj(
            fileobj, bucket, key,
            ExtraArgs=extra,
            Config=self._transfer_config,
            Callback=callback,
        )

    def upload_file(self, bucket: str, key: str, local_path: str,
                    callback: Optional[Callable] = None) -> None:
        extra = {"ContentType": _guess_content_type(local_path)}
        self.client.upload_file(
            local_path, bucket, key,
            ExtraArgs=extra,
            Config=self._transfer_config,
            Callback=callback,
        )

    def download_file(self, bucket: str, key: str, local_path: str,
                      callback: Optional[Callable] = None) -> None:
        self.client.download_file(bucket, key, local_path, Callback=callback)

    def delete_object(self, bucket: str, key: str) -> None:
        self.client.delete_object(Bucket=bucket, Key=key)

    def delete_objects(self, bucket: str, keys: list[str]) -> dict:
        return self.client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": k} for k in keys]},
        )

    def copy_object(self, src_bucket: str, src_key: str,
                    dst_bucket: str, dst_key: str) -> None:
        self.client.copy_object(
            CopySource={"Bucket": src_bucket, "Key": src_key},
            Bucket=dst_bucket,
            Key=dst_key,
        )

    def presigned_url(self, bucket: str, key: str, expiry: int = 3600) -> str:
        return self._presign_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expiry,
        )

    def presigned_upload_url(self, bucket: str, key: str, expiry: int = 3600) -> str:
        return self._presign_client.generate_presigned_url(
            "put_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expiry,
        )

    def get_object_info(self, bucket: str, key: str) -> dict:
        return self.client.head_object(Bucket=bucket, Key=key)

    def list_all_objects_flat(self, bucket: str, prefix: str = "") -> list[dict]:
        """Recursively list ALL objects under prefix without delimiter."""
        results: list[dict] = []
        pag = self.client.get_paginator("list_objects_v2")
        for page in pag.paginate(Bucket=bucket, Prefix=prefix):
            results.extend(page.get("Contents", []))
        return results

    def delete_prefix_objects(
        self,
        bucket: str,
        prefix: str,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> int:
        """Delete all objects whose Key starts with *prefix*.
        Calls on_progress(deleted, total) after each batch of 1000.
        Returns total deleted count.
        """
        objs    = self.list_all_objects_flat(bucket, prefix)
        total   = len(objs)
        deleted = 0
        for i in range(0, total, 1000):
            batch = [{"Key": o["Key"]} for o in objs[i : i + 1000]]
            self.client.delete_objects(Bucket=bucket, Delete={"Objects": batch})
            deleted += len(batch)
            if on_progress:
                on_progress(deleted, total)
        return deleted

    # ── Bucket Policy ─────────────────────────────────────────────────────────

    def get_bucket_policy(self, bucket: str) -> str:
        """Return the raw JSON policy string, or '' if none."""
        try:
            r = self.client.get_bucket_policy(Bucket=bucket)
            return r.get("Policy", "")
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchBucketPolicy":
                return ""
            raise

    def put_bucket_policy(self, bucket: str, policy_json: str) -> None:
        self.client.put_bucket_policy(Bucket=bucket, Policy=policy_json)

    def delete_bucket_policy(self, bucket: str) -> None:
        self.client.delete_bucket_policy(Bucket=bucket)

    # ── Bucket User Permissions (via S3 Bucket Policy) ────────────────────────
    #
    # Permissions are stored as standard S3 bucket policy statements whose
    # Sid begins with "_CephS3Mgr-".  Any other statements are preserved.
    #
    # Levels:
    #   "read"       → GetObject, ListBucket (download / browse)
    #   "write"      → PutObject, DeleteObject (upload / delete)
    #   "read_write" → read + write
    #   "full"       → s3:*

    _PERM_SID_PREFIX = "_CephS3Mgr-"
    _PERM_ACTIONS: "dict[str, list[str]]" = {
        "read": [
            "s3:GetObject", "s3:GetObjectVersion", "s3:GetObjectAcl",
            "s3:ListBucket", "s3:ListBucketVersions",
            "s3:GetBucketLocation", "s3:ListMultipartUploadParts",
            "s3:ListBucketMultipartUploads",
        ],
        "write": [
            "s3:PutObject", "s3:DeleteObject",
            "s3:AbortMultipartUpload", "s3:PutObjectAcl",
        ],
        "read_write": [
            "s3:GetObject", "s3:GetObjectVersion", "s3:GetObjectAcl",
            "s3:ListBucket", "s3:ListBucketVersions",
            "s3:GetBucketLocation", "s3:ListMultipartUploadParts",
            "s3:ListBucketMultipartUploads",
            "s3:PutObject", "s3:DeleteObject",
            "s3:AbortMultipartUpload", "s3:PutObjectAcl",
        ],
        "full": ["s3:*"],
    }

    def get_bucket_user_permissions(self, bucket: str) -> "dict[str, str]":
        """Parse bucket policy and return {uid: level} for CephS3Mgr statements."""
        import json as _j
        raw = self.get_bucket_policy(bucket) or ""
        if not raw:
            return {}
        try:
            policy = _j.loads(raw)
        except Exception:
            return {}
        result: "dict[str, str]" = {}
        pfx = self._PERM_SID_PREFIX
        for stmt in policy.get("Statement", []):
            sid = stmt.get("Sid", "")
            if not sid.startswith(pfx):
                continue
            uid = sid[len(pfx):]
            actions = stmt.get("Action", [])
            if isinstance(actions, str):
                actions = [actions]
            aset = set(actions)
            if "s3:*" in aset:
                result[uid] = "full"
            elif {"s3:PutObject", "s3:GetObject"} <= aset:
                result[uid] = "read_write"
            elif "s3:PutObject" in aset:
                result[uid] = "write"
            else:
                result[uid] = "read"
        return result

    def set_bucket_user_permissions(
        self, bucket: str, permissions: "dict[str, str]"
    ) -> None:
        """Apply user access permissions to bucket via S3 bucket policy.

        Existing statements NOT created by CephS3Manager are preserved.
        Passing an empty *permissions* dict removes all manager statements;
        if no other statements remain, the policy is deleted entirely.
        """
        import json as _j
        raw = self.get_bucket_policy(bucket) or ""
        try:
            existing = _j.loads(raw) if raw else {"Version": "2012-10-17", "Statement": []}
        except Exception:
            existing = {"Version": "2012-10-17", "Statement": []}

        pfx = self._PERM_SID_PREFIX
        # Keep statements not owned by this manager
        kept = [
            s for s in existing.get("Statement", [])
            if not s.get("Sid", "").startswith(pfx)
        ]
        # Build new statements for each user
        new_stmts = []
        for uid, level in permissions.items():
            uid = uid.strip()
            if not uid or level not in self._PERM_ACTIONS:
                continue
            new_stmts.append({
                "Sid":       f"{pfx}{uid}",
                "Effect":    "Allow",
                "Principal": {"AWS": [f"arn:aws:iam:::user/{uid}"]},
                "Action":    self._PERM_ACTIONS[level],
                "Resource":  [
                    f"arn:aws:s3:::{bucket}",
                    f"arn:aws:s3:::{bucket}/*",
                ],
            })

        all_stmts = kept + new_stmts
        if all_stmts:
            policy = {"Version": "2012-10-17", "Statement": all_stmts}
            self.put_bucket_policy(bucket, _j.dumps(policy))
        else:
            try:
                self.delete_bucket_policy(bucket)
            except Exception:
                pass

    # ── CORS ──────────────────────────────────────────────────────────────────

    def get_bucket_cors(self, bucket: str) -> list[dict]:
        """Return list of CORS rules, or [] if none configured."""
        try:
            r = self.client.get_bucket_cors(Bucket=bucket)
            return r.get("CORSRules", [])
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchCORSConfiguration", "CORSConfigurationNotFound"):
                return []
            raise

    def put_bucket_cors(self, bucket: str, rules: list[dict]) -> None:
        self.client.put_bucket_cors(
            Bucket=bucket,
            CORSConfiguration={"CORSRules": rules},
        )

    def delete_bucket_cors(self, bucket: str) -> None:
        self.client.delete_bucket_cors(Bucket=bucket)

    # ── Versioning ────────────────────────────────────────────────────────────

    def get_bucket_versioning(self, bucket: str) -> str:
        """Return 'Enabled', 'Suspended', or '' (never configured)."""
        r = self.client.get_bucket_versioning(Bucket=bucket)
        return r.get("Status", "")

    def put_bucket_versioning(self, bucket: str, status: str) -> None:
        """status: 'Enabled' or 'Suspended'."""
        self.client.put_bucket_versioning(
            Bucket=bucket,
            VersioningConfiguration={"Status": status},
        )

    def get_object_size(self, bucket: str, key: str) -> int:
        try:
            return self.client.head_object(Bucket=bucket, Key=key)["ContentLength"]
        except ClientError:
            return 0

    def search_objects(self, bucket: str, query: str,
                       prefix: str = "") -> list[dict]:
        results = []
        pag = self.client.get_paginator("list_objects_v2")
        for page in pag.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                if query.lower() in obj["Key"].lower():
                    results.append(obj)
                if len(results) >= 200:
                    return results
        return results


def _guess_content_type(filename: str) -> str:
    import mimetypes
    ct, _ = mimetypes.guess_type(filename)
    return ct or "application/octet-stream"


# ── Factory ───────────────────────────────────────────────────────────────────

def get_s3_from_conn(conn: dict) -> S3Manager:
    return S3Manager(
        endpoint=conn["endpoint"],
        access_key=conn["access_key"],
        secret_key=conn["secret_key"],
        region=conn.get("region", "us-east-1"),
        verify_ssl=conn.get("verify_ssl", True),
        public_endpoint=conn.get("public_endpoint", "") or "",
    )
