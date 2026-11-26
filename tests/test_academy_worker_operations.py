from io import BytesIO
from pathlib import Path
import json
import subprocess

import pytest

from app.academy_local_converter import LocalConverter, IsolationFailure, FatalIsolationFailure
from scripts.academy_worker import process_batch


def adapter(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    monkeypatch.setattr("app.academy_local_converter.os.geteuid",lambda:12345)
    monkeypatch.setattr("app.academy_local_converter.os.getegid",lambda:12345)
    # Constructor validates actual ownership; build an isolated unit-level
    # adapter without changing ownership of CI files.
    instance=object.__new__(LocalConverter)
    instance.image_id="sha256:"+"a"*64
    instance.scratch_root=tmp_path
    instance.uid=tmp_path.stat().st_uid
    instance.gid=12345
    instance.env={"PATH":"/usr/bin:/bin"}
    return instance


def test_fixed_container_policy_and_manifest(tmp_path,monkeypatch):
    instance=adapter(tmp_path,monkeypatch)
    output=tmp_path/"out"
    output.mkdir(mode=0o700)
    calls=[]
    monkeypatch.setattr(instance,"check_runtime",lambda:None)
    def fake_command(*args,**kwargs):
        calls.append(args)
        if args[0]=="run":
            assert (tmp_path/"source.bin").read_bytes()==b"source"
            kwargs["stdout"].write(json.dumps({"renditions":[{"name":"audio.m4a",
                "content_type":"audio/mp4","byte_count":10,"sha256":"a"*64,
                "duration":1.0,"page":None}]}).encode())
        return subprocess.CompletedProcess(args,1 if args[:2]==("container","exists") else 0)
    monkeypatch.setattr(instance,"_command",fake_command)
    manifest=instance(BytesIO(b"source"),"audio/mpeg",output)
    assert manifest["renditions"][0]["name"]=="audio.m4a"
    command=calls[0]
    assert "--network=none" in command and "--read-only" in command
    assert "--cap-drop=ALL" in command and "--pull=never" in command
    assert "--security-opt=no-new-privileges" in command
    assert command.count("--volume")==2
    assert str(output)+":/output:rw,Z" in command
    assert calls[1][:3]==("rm","--force","--ignore")
    assert calls[2][:2]==("container","exists")
    assert not (tmp_path/"source.bin").exists()


def test_cleanup_failure_stops_worker(tmp_path,monkeypatch):
    instance=adapter(tmp_path,monkeypatch)
    output=tmp_path/"out"
    output.mkdir(mode=0o700)
    monkeypatch.setattr(instance,"check_runtime",lambda:None)
    def fake_command(*args,**kwargs):
        return subprocess.CompletedProcess(args,1)
    monkeypatch.setattr(instance,"_command",fake_command)
    with pytest.raises(FatalIsolationFailure):
        instance(BytesIO(b"source"),"video/mp4",output)


def test_timeout_still_attempts_cleanup(tmp_path,monkeypatch):
    instance=adapter(tmp_path,monkeypatch)
    output=tmp_path/"out"
    output.mkdir(mode=0o700)
    monkeypatch.setattr(instance,"check_runtime",lambda:None)
    calls=[]
    def fake_command(*args,**kwargs):
        calls.append(args)
        if args[0]=="run":
            raise subprocess.TimeoutExpired(args,1200)
        return subprocess.CompletedProcess(args,1 if args[:2]==("container","exists") else 0)
    monkeypatch.setattr(instance,"_command",fake_command)
    with pytest.raises(subprocess.TimeoutExpired):
        instance(BytesIO(b"source"),"video/mp4",output)
    assert calls[1][:3]==("rm","--force","--ignore")
    assert not (tmp_path/"source.bin").exists()


def test_worker_routes_bounded_image_and_rich_jobs(monkeypatch,tmp_path):
    seen=[]
    def scan(*args,**kwargs):
        seen.append(("images",kwargs["limit"]))
        return {"clean":1,"rejected":0,"failed":0,"skipped":0}
    def pending(path,limit):
        seen.append(("pending",limit))
        return ["a","b"]
    def convert(path,media_id,**kwargs):
        seen.append(("rich",media_id))
        assert kwargs["scratch_root"]==tmp_path
        return "clean" if media_id=="a" else "rejected"
    monkeypatch.setattr("scripts.academy_worker.scan_batch",scan)
    monkeypatch.setattr("scripts.academy_worker.rich_pending",pending)
    monkeypatch.setattr("scripts.academy_worker.process_conversion",convert)
    report=process_batch("db",storage=object(),bucket="private",scanner=object(),
                         converter=object(),scratch=tmp_path,mode="all",limit=2)
    assert report=={"clean":2,"rejected":1,"failed":0,"skipped":0}
    assert seen==[("images",2),("pending",2),("rich","a"),("rich","b")]
