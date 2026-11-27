"""Rootless local Podman adapter for the offline Academy converter.

Only run on a dedicated trusted worker account/host. The scratch filesystem
must have a host-enforced quota. Never mount the runtime socket in the web app.
The converter receives one read-only file and an empty private output directory.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess  # nosec B404 - fixed local executable, no shell
from tempfile import TemporaryFile

from .academy_media import RULES, MiB
from .academy_renditions import parse_manifest, RenditionError

PODMAN = "/usr/bin/podman"
CONTAINER = "stazhno-academy-offline-converter"
MAX_MANIFEST = 65536


class IsolationFailure(RuntimeError):
    pass


class FatalIsolationFailure(SystemExit):
    """A worker must stop if removal of its converter cannot be confirmed."""


def _local_env():
    # No DATABASE_URL, S3 credentials, cloud token, proxy, remote runtime
    # connection or arbitrary host environment is passed to the converter.
    env = {"PATH":"/usr/bin:/bin","LANG":"C","LC_ALL":"C"}
    for name in ("HOME","XDG_RUNTIME_DIR","XDG_CONFIG_HOME","XDG_DATA_HOME"):
        value = os.getenv(name, "")
        if value and Path(value).is_absolute():
            env[name] = value
    return env


class LocalConverter:
    def __init__(self, image_id: str, *, scratch_root: str):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise IsolationFailure("Converter must be pinned to a locally built image ID")
        self.image_id = image_id
        self.scratch_root = Path(scratch_root).resolve(strict=True)
        self.uid = os.geteuid()
        self.gid = os.getegid()
        if self.uid == 0:
            raise IsolationFailure("A non-root dedicated worker account is required")
        if not self.scratch_root.is_dir() or self.scratch_root.stat().st_uid != self.uid:
            raise IsolationFailure("Scratch directory must belong to the dedicated worker")
        if self.scratch_root.stat().st_mode & 0o077:
            raise IsolationFailure("Scratch directory must be private")
        self.env = _local_env()

    def _command(self, *args, timeout=20, stdout=subprocess.DEVNULL):
        return subprocess.run(  # nosec B603 - absolute executable, fixed arguments, no shell
            [PODMAN, "--remote=false", *args], env=self.env, cwd=self.scratch_root,
            stdin=subprocess.DEVNULL, stdout=stdout, stderr=subprocess.DEVNULL,
            timeout=timeout, check=False,
        )

    def _exists(self):
        code = self._command("container","exists",CONTAINER).returncode
        if code not in (0,1):
            raise IsolationFailure("Cannot inspect the local converter runtime")
        return code == 0

    def check_runtime(self):
        with TemporaryFile(mode="w+b",dir=self.scratch_root) as out:
            result = self._command("info","--format","{{.Host.Security.Rootless}}",stdout=out)
            out.seek(0)
            if result.returncode != 0 or out.read(32).strip() != b"true":
                raise IsolationFailure("Local rootless Podman is not available")
        if self._command("image","exists",self.image_id).returncode != 0:
            raise IsolationFailure("Pinned converter image is not installed")
        if self._exists():
            raise IsolationFailure("A prior converter container exists; operator must reconcile it")

    def _cleanup(self):
        try:
            result = self._command("rm","--force","--ignore",CONTAINER,timeout=30)
            if result.returncode != 0 or self._exists():
                raise IsolationFailure("Container removal not confirmed")
        except Exception:
            # This exception intentionally bypasses the conversion worker's
            # ordinary per-file Exception handlers; stop this invocation.
            raise FatalIsolationFailure("Converter cleanup could not be confirmed; worker stopped") from None

    def __call__(self, source, content_type: str, output: Path):
        rule = RULES.get(content_type)
        if rule is None or rule.kind == "image":
            raise RenditionError("Unsupported offline converter input")
        output = output.resolve(strict=True)
        if not output.is_relative_to(self.scratch_root) or not output.is_dir() or any(output.iterdir()):
            raise IsolationFailure("Output must be an empty job directory inside private scratch")
        if output.stat().st_uid != self.uid or output.stat().st_mode & 0o077:
            raise IsolationFailure("Output directory is not private")
        original = output.parent / "source.bin"
        for path in (original,output):
            if any(char in str(path) for char in (":",",","\n","\r")):
                raise IsolationFailure("Unsafe local mount path")
        self.check_runtime()
        created = False
        try:
            size = 0
            with original.open("xb") as local:
                created = True
                while chunk := source.read(MiB):
                    size += len(chunk)
                    if size > rule.limit:
                        raise RenditionError("Source size exceeds format limit")
                    local.write(chunk)
            if size == 0:
                raise RenditionError("Source is empty")
            original.chmod(0o400)
            with TemporaryFile(mode="w+b",dir=self.scratch_root) as manifest:
                try:
                    result = self._command(
                        "run","--rm","--name",CONTAINER,"--pull=never",
                        "--network=none","--read-only","--cap-drop=ALL",
                        "--security-opt=no-new-privileges","--pids-limit=128",
                        "--cpus=2","--memory=1g","--memory-swap=1g",
                        "--userns=keep-id","--user",f"{self.uid}:{self.gid}",
                        "--log-driver=none","--env=HOME=/tmp",
                        "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=768m",
                        "--ulimit=fsize=314572800:314572800",
                        "--volume",str(original)+":/input/source:ro,Z",
                        "--volume",str(output)+":/output:rw,Z",
                        self.image_id,"--content-type",content_type,
                        timeout=1200,stdout=manifest,
                    )
                finally:
                    # Do not import outputs until the converter is stopped.
                    self._cleanup()
                if result.returncode != 0:
                    raise RenditionError("Offline converter failed")
                manifest.seek(0)
                data = manifest.read(MAX_MANIFEST + 1)
            if len(data) > MAX_MANIFEST:
                raise RenditionError("Converter manifest too large")
            try:
                report = json.loads(data)
            except (UnicodeError,ValueError):
                raise RenditionError("Invalid converter manifest") from None
            parse_manifest(content_type,report)
            return report
        finally:
            # Only the exclusively created local file is removed. The outer
            # job's TemporaryDirectory handles its own output files.
            # The source path is not selected by the untrusted converter.
            if created and original.is_file() and not original.is_symlink():
                original.unlink(missing_ok=True)
