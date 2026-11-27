"""Read-only public infrastructure evidence for STAZHNO, not launch approval.

Fixed public hosts only. No passwords, cookies, SMTP authentication, mail
delivery, registration, production database reads, or mutation requests.
Do not log raw DNS answers, certificates, IPs, response bodies or exceptions.
"""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import re
import shlex
import shutil
import ssl
import subprocess

DOMAIN = "stazhno.ru"
PREVIEW = "arromanov1985-opyt50-platform-fdd8.twc1.net"
DNS_QUERIES = frozenset({
    (DOMAIN, "A"), (DOMAIN, "AAAA"), (DOMAIN, "MX"),
    (DOMAIN, "TXT"), ("_dmarc." + DOMAIN, "TXT"),
})


def parse_dns(output: str, host: str, rrtype: str) -> tuple[str, list[str]]:
    match = re.search(r"\bstatus:\s*([A-Z]+)\b", output)
    if not match:
        return "unverified", []
    status = match.group(1)
    if status == "NXDOMAIN":
        return "nxdomain", []
    if status != "NOERROR":
        return "unverified", []
    records = []
    for line in output.splitlines():
        if not line or line.startswith(";"):
            continue
        fields = line.split(None, 4)
        if len(fields) == 5 and fields[2].upper() == "IN" and fields[3].upper() == rrtype:
            # Ignore records for unrelated names. A CNAME by itself does not
            # prove the requested record at the domain exists.
            if fields[0].rstrip(".").casefold() == host.casefold():
                records.append(fields[4])
    return ("present" if records else "absent"), records


def dns_query(host: str, rrtype: str) -> tuple[str, list[str]]:
    if (host, rrtype) not in DNS_QUERIES:
        raise ValueError("Unsupported DNS query")
    binary = shutil.which("dig")
    if not binary:
        return "unverified", []
    try:
        completed = subprocess.run(
            [binary, "+time=3", "+tries=1", "+noall", "+comments", "+answer", host, rrtype],
            capture_output=True, text=True, timeout=8, check=False,
        )
        if completed.returncode or len(completed.stdout) > 65536:
            return "unverified", []
        return parse_dns(completed.stdout, host, rrtype)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return "unverified", []


def txt_value(record: str) -> str:
    # dig prints TXT strings in quoted chunks; concatenate within one RR.
    try:
        return "".join(shlex.split(record))
    except ValueError:
        return ""


def mx_state(result: tuple[str, list[str]]) -> str:
    status, records = result
    if status != "present":
        return status
    parsed = []
    for record in records:
        fields = record.split()
        if len(fields) != 2 or not fields[0].isdigit() or not 0 <= int(fields[0]) <= 65535:
            return "invalid"
        parsed.append((int(fields[0]), fields[1]))
    if parsed == [(0, ".")]:
        return "null-mx"
    if any(target == "." for _, target in parsed):
        return "invalid"
    return "present"


def policy_state(result: tuple[str, list[str]], prefix: str) -> str:
    status, records = result
    if status != "present":
        return status
    values = [txt_value(record).strip() for record in records]
    policies = [value for value in values if value.split(None, 1)[0:1] == [prefix]]
    if prefix == "v=DMARC1":
        policies = [value for value in values if value.split(";", 1)[0].strip() == prefix]
    if not policies:
        return "absent"
    if len(policies) != 1:
        return "multiple"
    # This is a record-presence check, not a full evaluation of SPF/DMARC,
    # included mechanisms, alignment, DNS lookup budgets or policy validity.
    return "single-record"


def https_health(host: str) -> dict:
    if host not in {DOMAIN, PREVIEW}:
        raise ValueError("Unsupported HTTPS host")
    connection = None
    try:
        connection = http.client.HTTPSConnection(host, timeout=8, context=ssl.create_default_context())
        connection.request("GET", "/api/health", headers={
            "User-Agent": "Stazhno-Public-Prelaunch-ReadOnly/1.0",
            "Accept": "application/json", "Cache-Control": "no-cache",
        })
        response = connection.getresponse()
        result = {"tls": "verified", "http": response.status, "health": "unverified"}
        if response.status != 200:
            return result
        if not response.headers.get("Content-Type", "").lower().startswith("application/json"):
            return result
        payload = response.read(4097)
        if len(payload) <= 4096:
            try:
                data = json.loads(payload)
                if isinstance(data, dict) and data.get("status") == "ok":
                    result["health"] = "healthy"
            except (ValueError, UnicodeError):
                pass
        return result
    except ssl.SSLCertVerificationError:
        return {"tls": "certificate-invalid", "http": None, "health": "unverified"}
    except (OSError, http.client.HTTPException):
        return {"tls": "unverified", "http": None, "health": "unverified"}
    finally:
        if connection is not None:
            connection.close()


def assess(query=dns_query, health=https_health) -> dict:
    a, _ = query(DOMAIN, "A")
    aaaa, _ = query(DOMAIN, "AAAA")
    mx = mx_state(query(DOMAIN, "MX"))
    spf = policy_state(query(DOMAIN, "TXT"), "v=spf1")
    dmarc = policy_state(query("_dmarc." + DOMAIN, "TXT"), "v=DMARC1")
    return {
        "read_only": True,
        "canonical_dns_a": a,
        "canonical_dns_aaaa": aaaa,
        "canonical_https": health(DOMAIN),
        "technical_https": health(PREVIEW),
        "mail_mx": mx,
        "mail_spf": spf,
        "mail_dmarc": dmarc,
        "mail_dkim": "requires-confirmed-provider-selector",
        "mail_delivery": "not-tested",
        "production_db_backups": "not-tested",
        "production_mfa": "not-tested",
        "public_launch_approved": False,
    }


def main() -> int:
    report = assess()
    text = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)
    Path("prelaunch-public-diagnostics.json").write_text(text + "\n", encoding="utf-8")
    print(text)
    # Diagnostic only: a successful workflow means the report ran, not that
    # every check passed or that the legal/operational launch gates are closed.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
