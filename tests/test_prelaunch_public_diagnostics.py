import json

import pytest

from scripts import prelaunch_public_diagnostics as diag


def test_dns_distinguishes_absence_failure_and_unrelated_answers():
    header = ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 10\n"
    assert diag.parse_dns(header, diag.DOMAIN, "MX") == ("absent", [])
    assert diag.parse_dns(header.replace("NOERROR", "SERVFAIL"), diag.DOMAIN, "MX") == ("unverified", [])
    assert diag.parse_dns(header.replace("NOERROR", "NXDOMAIN"), diag.DOMAIN, "MX") == ("nxdomain", [])
    output = header + "other.invalid. 30 IN MX 10 mx.invalid.\n" + "stazhno.ru. 30 IN MX 10 mx.example.\n"
    assert diag.parse_dns(output, diag.DOMAIN, "MX") == ("present", ["10 mx.example."])
    assert diag.parse_dns("", diag.DOMAIN, "MX") == ("unverified", [])


@pytest.mark.parametrize("records,expected", [
    (["10 mx.example."], "present"),
    (["0 ."], "null-mx"),
    (["0 .", "10 mx.example."], "invalid"),
    (["bad"], "invalid"),
])
def test_mx_presence_is_not_null_mx(records, expected):
    assert diag.mx_state(("present", records)) == expected


def test_txt_chunks_and_duplicate_policies():
    assert diag.policy_state(("present", ['"v=spf1 " "-all"']), "v=spf1") == "single-record"
    assert diag.policy_state(("present", ['"unrelated"']), "v=spf1") == "absent"
    assert diag.policy_state(("present", ['"v=spf1 -all"', '"v=spf1 ~all"']), "v=spf1") == "multiple"
    assert diag.policy_state(("present", ['"v=DMARC1; " "p=none"']), "v=DMARC1") == "single-record"
    assert diag.policy_state(("unverified", []), "v=DMARC1") == "unverified"


def test_diagnostic_report_never_contains_raw_dns_or_claims_delivery():
    def query(host, rrtype):
        assert (host, rrtype) in diag.DNS_QUERIES
        return ("present", {"A":["192.0.2.99"], "AAAA":["2001:db8::99"],
                "MX":["10 hidden-mx.example."], "TXT":['"v=spf1 include:hidden.example -all"']}[rrtype])
    report = diag.assess(query, lambda host: {"tls":"verified","http":200,"health":"healthy"})
    payload = json.dumps(report)
    for raw in ("hidden", "192.0.2.99", "2001:db8"):
        assert raw not in payload
    assert report["mail_delivery"] == "not-tested"
    assert report["mail_dkim"] == "requires-confirmed-provider-selector"
    assert report["public_launch_approved"] is False
    assert report["production_db_backups"] == "not-tested"


def test_reject_unknown_dns_and_http_targets():
    with pytest.raises(ValueError):
        diag.dns_query("other.invalid", "MX")
    with pytest.raises(ValueError):
        diag.https_health("other.invalid")


def test_https_only_uses_fixed_get_with_bounded_json_and_no_auth(monkeypatch):
    calls = []
    class Response:
        status = 200
        headers = {"Content-Type": "application/json"}
        def read(self, limit):
            assert limit == 4097
            return b'{"status":"ok"}'
    class Connection:
        def __init__(self, host, timeout, context):
            assert host == diag.DOMAIN and timeout == 8
            assert context.check_hostname
        def request(self, method, path, headers):
            assert method == "GET" and path == "/api/health"
            assert "Authorization" not in headers and "Cookie" not in headers
            calls.append(path)
        def getresponse(self):
            return Response()
        def close(self):
            pass
    monkeypatch.setattr(diag.http.client, "HTTPSConnection", Connection)
    assert diag.https_health(diag.DOMAIN) == {"tls":"verified","http":200,"health":"healthy"}
    assert calls == ["/api/health"]
