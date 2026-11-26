# Academy: infrastructure activation checklist

This release does not turn on uploading, conversion or publication.
The Timeweb web application, trusted processing service, offline converter
and S3 storage are separate trust boundaries.

## 1. Private S3 and scanner

Provision a private, non-versioned S3 bucket for Academy only. Ensure no
public read/list policies or ACLs; restrict access to the Academy prefix and
dedicated service identities. Current deletion logic is not version-aware,
so versioned/suspended buckets are blocked by preflight.

Use server-side environment variables from docs/ACADEMY_MEDIA.md.
Do not place credentials in Git, chat messages, screenshots or browser code.
Do not set IMAGE_UPLOAD_ENABLED or RENDITION_PREVIEW_ENABLED yet.

On a trusted processing host install the optional requirements:
`python -m pip install -r requirements-postgres.txt -r requirements-academy-storage.txt`.
Configure a local ClamAV daemon with updated signatures. Ensure that its
INSTREAM and archive scan limits cover the actual allowed upload sizes and
that over-limit scans fail closed. Test both a known harmless sample and
the operator's standard antivirus detection test.

Run the explicit synthetic probe:
```sh
python -m scripts.academy_media_preflight --live
```
It creates one random object under academy/preflight/, verifies conditional
write rejection, exact read-back, anonymous denial and cleanup. No user
files or course records are read or modified. If cleanup cannot be confirmed,
the output includes the synthetic key for manual removal. This probe is
necessary but not sufficient: it does not attest every bucket policy,
backup, anonymous endpoint or malware signature.

## 2. Worker host

Keep the converter separate from the web process. The trusted worker can
read its own database and object storage; the offline converter must not.
Use a dedicated host/container environment, rootless runtime where feasible,
resource limits and an isolated scratch volume. The converter image already
exists in Dockerfile.academy-converter. Do not mount the host runtime socket
inside the web app. No worker or real credentials are provisioned by this PR.

## 3. Web integration

Only after the storage probe and scanner detection test pass, install the
optional dependencies in the web runtime. Confirm reverse-proxy upload caps,
temporary disk limits, security log handling and private routing.
Verify authentication and access revocation with test accounts. Start with
images and keep multimedia publication disabled. Rich-media browser upload
and production worker supervision are separate release gates.

## 4. Activation/rollback

Confirm privacy export/deletion of original objects and every derivative,
including abandoned reservations, before accepting real user content.
Keep explicit feature switches off until the end-to-end environment check.
Rollback by disabling the web upload and preview switches and stopping the
worker; do not delete existing database rows or objects on rollback.
Record the deployed commit and health verification. Legal approval remains
a separate launch gate.
