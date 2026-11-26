from scripts.timeweb_inventory import inventory, complete


PROJECTS = {"projects": [{"name": "Общий проект", "id": 17, "description": "private"}],
            "meta": {"total": 1}}
APPS = {"apps": [{"name": "opytno-production", "branch_name": "main",
                  "is_auto_deploy": True, "configuration": {"cpu": 2, "ram": 2048},
                  "id": 84, "envs": {"DATABASE_URL": "sensitive-fixture"}, "ip": "private"}],
        "meta": {"total": 1}}


def run(overrides=None, explicit=""):
    responses = {
        "/api/v1/projects": (200, PROJECTS),
        "/api/v1/apps": (200, APPS),
        "/api/v1/projects/17/resources/buckets": (200, {"buckets": [], "meta": {"total": 0}}),
        "/api/v1/projects/17/resources/servers": (200, {"servers": [{"name": "private", "ip": "private"}],
                                                          "meta": {"total": 1}}),
    }
    responses.update(overrides or {})
    calls = []

    def fetch(path):
        calls.append(path)
        return responses[path]

    return inventory(fetch, explicit), calls


def test_scoped_inventory_does_not_emit_sensitive_fields():
    report, calls = run()
    assert complete(report)
    assert report["app_cpu_cores"] == 2 and report["app_ram_mb"] == 2048
    assert report["app_branch_main"] and report["app_auto_deploy"]
    assert report["s3_resources_present"] is False
    assert report["server_resources_present"] is True
    assert calls == ["/api/v1/projects", "/api/v1/apps",
                     "/api/v1/projects/17/resources/buckets",
                     "/api/v1/projects/17/resources/servers"]
    assert "private" not in str(report) and "sensitive-fixture" not in str(report)


def test_permission_denial_is_unknown_not_absence():
    report, _ = run({"/api/v1/projects/17/resources/buckets": (403, None)})
    assert not complete(report)
    assert report["s3_http"] == 403 and report["s3_resources_present"] is None
    assert report["server_resources_present"] is True


def test_unknown_project_does_not_probe_other_projects():
    report, calls = run(explicit="99")
    assert not complete(report)
    assert calls == ["/api/v1/projects"]


def test_incomplete_projects_or_duplicate_app_do_not_select_implicitly():
    report, calls = run({"/api/v1/projects": (200, {**PROJECTS, "meta": {"total": 2}})})
    assert not complete(report) and len(calls) == 1
    report, calls = run({"/api/v1/apps": (200, {"apps": APPS["apps"] * 2, "meta": {"total": 2}})})
    assert not complete(report) and len(calls) == 4
    assert report["s3_resources_present"] is False
    assert report["server_resources_present"] is True


def test_invalid_resource_schema_is_unknown():
    report, _ = run({"/api/v1/projects/17/resources/servers": (200, {"servers": []})})
    assert not complete(report)
    assert report["server_resources_present"] is None


def test_unsupported_app_fields_are_not_printed():
    app = {**APPS["apps"][0], "configuration": {"cpu": "private", "ram": True},
           "is_auto_deploy": "private", "branch_name": 42}
    report, _ = run({"/api/v1/apps": (200, {"apps": [app], "meta": {"total": 1}})})
    assert complete(report)
    assert all(report[key] is None for key in
               ("app_cpu_cores", "app_ram_mb", "app_auto_deploy", "app_branch_main"))


def test_app_access_denial_does_not_hide_project_inventory():
    report, calls = run({"/api/v1/apps": (403, None)})
    assert not complete(report)
    assert report["apps_http"] == 403
    assert report["target_app_found"] is False
    assert report["s3_http"] == report["servers_http"] == 200
    assert report["s3_resources_present"] is False
    assert report["server_resources_present"] is True
    assert len(calls) == 4
