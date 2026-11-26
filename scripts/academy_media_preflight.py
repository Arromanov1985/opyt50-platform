"""Explicit live infrastructure check, using only a disposable synthetic object.

Never run on import or as a web endpoint. This does not enable uploads.
Operator must review bucket access policies and lifecycle separately.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
import json
import os
from uuid import uuid4

from app.academy_storage import storage_config, build_storage_client
from app.academy_media_scan import ClamAV, validate_image


def _error_code(exc):
    response=getattr(exc,"response",None)
    if not isinstance(response,dict):
        return None
    return str(response.get("Error",{}).get("Code",""))


def _anonymous_denied(client, bucket, key):
    try:
        response=client.get_object(Bucket=bucket,Key=key)
    except Exception as exc:
        return _error_code(exc) in ("AccessDenied","403","404","NoSuchKey","NotFound")
    body=response.get("Body")
    if body is not None:
        body.close()
    return False


def check_storage(*, client, anonymous, bucket: str, payload: bytes) -> dict:
    """Check conditional write, integrity, anonymous denial and cleanup.

    Versioned or suspended buckets are deliberately rejected until version-aware
    deletion is implemented. Cleanup is limited to one random synthetic key.
    """
    report={"versioning_disabled":False,"conditional_write":False,
            "integrity":False,"anonymous_denied":False,"cleanup":False}
    key="academy/preflight/"+uuid4().hex
    try:
        versioning=client.get_bucket_versioning(Bucket=bucket)
        if versioning.get("Status") is not None:
            return report
        report["versioning_disabled"]=True
    except Exception:
        return report
    checksum=sha256(payload).hexdigest()

    def put():
        return client.put_object(Bucket=bucket,Key=key,Body=BytesIO(payload),
            ContentLength=len(payload),ContentType="application/octet-stream",
            ContentDisposition="attachment",IfNoneMatch="*",Metadata={"sha256":checksum})

    attempted=False
    try:
        attempted=True
        try:
            put()
        except Exception as exc:
            # A collision is improbable but must not delete an existing key
            # that this probe did not create. Ambiguous network failures
            # still require reconciliation of our random key.
            if _error_code(exc) in ("PreconditionFailed","412","ConditionalRequestConflict","409"):
                attempted=False
            raise
        try:
            put()
        except Exception as exc:
            report["conditional_write"]=_error_code(exc) in ("PreconditionFailed","412")
        response=client.get_object(Bucket=bucket,Key=key)
        body=response["Body"]
        try:
            data=body.read(len(payload)+1)
            report["integrity"]=(response.get("ContentLength")==len(payload)
                                 and data==payload and sha256(data).hexdigest()==checksum)
        finally:
            body.close()
        report["anonymous_denied"]=_anonymous_denied(anonymous,bucket,key)
    except Exception:
        # No SDK exceptions or credentials in output.
        pass
    finally:
        if attempted:
            try:
                client.delete_object(Bucket=bucket,Key=key)
                try:
                    client.head_object(Bucket=bucket,Key=key)
                except Exception as exc:
                    report["cleanup"]=_error_code(exc) in ("404","NoSuchKey","NotFound")
            except Exception:
                pass
            if not report["cleanup"]:
                # Non-sensitive, synthetic key only; operator needs it for
                # manual reconciliation if an external call was ambiguous.
                report["cleanup_key"]=key
    return report


def _anonymous_client(config):
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config
    return boto3.client("s3",endpoint_url=config.endpoint,region_name=config.region,
                       config=Config(signature_version=UNSIGNED,connect_timeout=5,
                                     read_timeout=15,retries={"total_max_attempts":1},
                                     s3={"addressing_style":"path"}),verify=True)


def synthetic_image():
    from PIL import Image
    output=BytesIO()
    Image.new("RGB",(16,16),"white").save(output,"PNG")
    return output.getvalue()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live",action="store_true",help="Explicitly permit one synthetic S3 write and cleanup")
    args=parser.parse_args()
    if not args.live:
        parser.error("A live storage check requires --live")
    try:
        config=storage_config()
        socket_path=os.getenv("STAZHNO_ACADEMY_CLAMD_SOCKET","")
        if config is None or not os.path.isabs(socket_path):
            raise RuntimeError("Missing private backend configuration")
        payload=synthetic_image()
        scan_ok=ClamAV(socket_path,timeout=20).scan(BytesIO(payload))=="clean"
        decode_ok=validate_image(BytesIO(payload),"image/png")=="clean"
        if not scan_ok or not decode_ok:
            print(json.dumps({"scanner_clean_sample":scan_ok,"decoder":decode_ok,"ready":False}))
            return 1
        result=check_storage(client=build_storage_client(config),anonymous=_anonymous_client(config),
                             bucket=config.bucket,payload=payload)
        ready=all(result.get(k) is True for k in (
            "versioning_disabled","conditional_write","integrity","anonymous_denied","cleanup"))
        print(json.dumps({"scanner_clean_sample":scan_ok,"decoder":decode_ok,
                          "storage":result,"ready":ready},separators=(",",":")))
        return 0 if ready else 1
    except Exception:
        print(json.dumps({"ready":False,"error":"configuration_or_backend_failed"}))
        return 1


if __name__=="__main__":
    raise SystemExit(main())
