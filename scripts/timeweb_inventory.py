"""Read-only inventory for the known STAZHNO preview project.

Output is deliberately redacted: no resource IDs/names, addresses, environment
variables, API response bodies, credentials or raw exception messages.
No create/update/delete calls, storage writes or paid-resource provisioning.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import ssl


HOST = "api.timeweb.cloud"
APP = "opytno-production"
PROJECT = "Общий проект"
MAX_RESPONSE = 2 * 1024 * 1024


class InventoryError(ValueError):
    pass


def get_json(token, path):
    if not re.fullmatch(r"/api/v1/(?:apps|projects|projects/[1-9][0-9]{0,15}/resources/(?:buckets|servers))", path):
        raise InventoryError("Unsupported API path")
    connection = http.client.HTTPSConnection(HOST, timeout=15, context=ssl.create_default_context())
    try:
        connection.request("GET", path, headers={
            "Authorization": "Bearer " + token, "Accept": "application/json",
        })
        response = connection.getresponse()
        status = response.status
        if status != 200:
            return status, None
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            return status, None
        data = json.loads(raw)
        return status, data if isinstance(data, dict) else None
    except Exception:
        return None, None
    finally:
        connection.close()


def collection(payload, key):
    if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        raise InventoryError("Unknown API response structure")
    rows = payload[key]
    if not all(isinstance(row, dict) for row in rows):
        raise InventoryError("Invalid API collection")
    meta = payload.get("meta")
    total = meta.get("total") if isinstance(meta, dict) else None
    if type(total) is not int or total < len(rows):
        raise InventoryError("Unknown collection total")
    return rows, total


def project_id(rows, total, explicit):
    if explicit:
        if not re.fullmatch(r"[1-9][0-9]{0,15}", explicit):
            raise InventoryError("Invalid project ID")
        matches = [r for r in rows if str(r.get("id")) == explicit and r.get("name") == PROJECT]
    else:
        # Do not choose the default arbitrarily or inspect unrelated projects.
        if total != len(rows):
            raise InventoryError("Project list is incomplete")
        matches = [r for r in rows if r.get("name") == PROJECT]
    if len(matches) != 1:
        raise InventoryError("Expected project not uniquely identified")
    value = str(matches[0].get("id"))
    if not re.fullmatch(r"[1-9][0-9]{0,15}", value):
        raise InventoryError("Invalid project ID")
    return value


def inventory(fetch, explicit_project=""):
    result = {
        "projects_http": None, "project_selected": False,
        "apps_http": None, "target_app_found": False,
        "app_branch_main": None, "app_auto_deploy": None,
        "app_cpu_cores": None, "app_ram_mb": None,
        "s3_http": None, "s3_resources_present": None,
        "servers_http": None, "server_resources_present": None,
    }
    status, projects = fetch("/api/v1/projects")
    result["projects_http"] = status
    try:
        rows, total = collection(projects, "projects")
        selected = project_id(rows, total, explicit_project)
    except InventoryError:
        return result
    result["project_selected"] = True
    status, apps = fetch("/api/v1/apps")
    result["apps_http"] = status
    try:
        rows, total = collection(apps, "apps")
        matches = [row for row in rows if row.get("name") == APP]
        if len(matches) == 1 and total == len(rows):
            app = matches[0]
            result["target_app_found"] = True
            branch = app.get("branch_name")
            result["app_branch_main"] = branch == "main" if isinstance(branch, str) else None
            auto = app.get("is_auto_deploy")
            result["app_auto_deploy"] = auto if type(auto) is bool else None
            config = app.get("configuration")
            if isinstance(config, dict):
                for dest, field, maximum in (("app_cpu_cores", "cpu", 256), ("app_ram_mb", "ram", 1048576)):
                    value = config.get(field)
                    if type(value) is int and 1 <= value <= maximum:
                        result[dest] = value
    except InventoryError:
        pass
    # Project selection has already been validated. App lookup and project
    # resource permissions are independent; retain partial diagnostics.
    for label, suffix, key, presence in (
        ("s3_http", "buckets", "buckets", "s3_resources_present"),
        ("servers_http", "servers", "servers", "server_resources_present"),
    ):
        status, payload = fetch(f"/api/v1/projects/{selected}/resources/{suffix}")
        result[label] = status
        try:
            _, total = collection(payload, key)
            result[presence] = total > 0
        except InventoryError:
            pass
    return result


def complete(report):
    return (
        report["project_selected"] and report["target_app_found"]
        and all(report[key] == 200 for key in ("projects_http", "apps_http", "s3_http", "servers_http"))
        and all(report[key] is not None for key in ("s3_resources_present", "server_resources_present"))
    )


def main():
    token = os.environ.get("TIMEWEB_CLOUD_TOKEN", "").strip()
    if not token or any(ord(ch) < 33 or ord(ch) > 126 for ch in token):
        print('{"error":"missing_or_invalid_environment_secret"}')
        return 1
    try:
        report = inventory(lambda path: get_json(token, path), os.environ.get("PROJECT_ID", "").strip())
        # Values are booleans, bounded numeric configuration, HTTP codes or null.
        # Never serialize provider response objects, unknown strings, IDs or errors.
        print(json.dumps({"complete": complete(report), **report}, separators=(",", ":")))
        return 0 if complete(report) else 1
    except Exception:
        print('{"error":"inventory_failed"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
