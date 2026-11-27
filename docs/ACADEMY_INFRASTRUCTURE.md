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


## 5. Timeweb Cloud read-only API access through GitHub

The repository is public. Never commit credentials, place them in Actions
variables, PR comments or chat, or print raw Timeweb API responses.

1. In Timeweb Cloud → API and Terraform issue a restricted API token for
   the STAZHNO project only. Initially grant read-only access to App Platform,
   S3 and cloud servers; deny unrelated services. Leave API deletion bypass
   disabled. Use a short validity period when available.
2. In GitHub Settings → Environments create an environment named
   `timeweb-stazhno`. Restrict deployment branches to exactly `main`
   and enable approval by a trusted owner if available. Add an
   **environment secret**, not a variable, named `TIMEWEB_CLOUD_TOKEN`.
3. After the workflow is merged into the default branch, manually run
   **Timeweb STAZHNO read-only access check** in GitHub Actions. Use only the
   main branch. Optionally enter the numeric STAZHNO project ID to verify
   access to its specific server and S3 resource-list endpoints.
4. The workflow makes only fixed-host HTTPS GET requests and emits HTTP
   status codes; it does not print API response bodies or use the token to
   mutate resources. A 200 is an API access check, not proof that a
   particular resource is correctly configured or all permissions are safe.

A separate management token, with narrowly scoped permissions and explicit
approval, may be required for future changes. Do not enable any paid
resources, alter existing databases, change feature switches or widen
permissions as part of the read-only check. S3 object access credentials
are separate from the cloud API token; store them only in the appropriate
trusted server configuration. Revoke the cloud API token in Timeweb when
no longer needed and remove its GitHub environment secret.


## 6. Read-only infrastructure inventory

After the token connection check, run **Timeweb STAZHNO infrastructure
inventory** manually on main. It selects the already confirmed Common
project (Общий проект) by exact name and checks the known app
opytno-production by exact name. The project ID is optional. No raw API
payloads, resource names/IDs, IP addresses, credentials or environment
variables are logged. The summary contains HTTP codes, resource-presence
booleans, and the target app's CPU/RAM configuration if provided.
An unknown value is not evidence that a resource is absent.

The App Platform list does not establish project membership on its own.
The project-level server/bucket results are only presence checks for that
selected project, not a claim that an existing resource can be reused.
Inspect resource ownership, geography, existing workloads and access
privately before selecting or provisioning infrastructure. No paid
services are ordered and no API permissions are widened by this workflow.
