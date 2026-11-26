from io import BytesIO
import pytest
from scripts.academy_media_preflight import check_storage, synthetic_image


class S3Error(Exception):
    def __init__(self, code):
        self.response={"Error":{"Code":code}}


class Storage:
    def __init__(self, *, versioning=None, conditional=True, cleanup=True):
        self.objects={}
        self.versioning=versioning
        self.conditional=conditional
        self.cleanup=cleanup
        self.writes=[]
        self.deletes=[]

    def get_bucket_versioning(self, **kwargs):
        return {} if self.versioning is None else {"Status":self.versioning}

    def put_object(self, **kwargs):
        key=kwargs["Key"]
        assert key.startswith("academy/preflight/")
        assert kwargs["IfNoneMatch"]=="*"
        self.writes.append(key)
        if self.conditional and key in self.objects:
            raise S3Error("PreconditionFailed")
        self.objects[key]=kwargs["Body"].read()

    def get_object(self, **kwargs):
        key=kwargs["Key"]
        if key not in self.objects:
            raise S3Error("NoSuchKey")
        data=self.objects[key]
        return {"Body":BytesIO(data),"ContentLength":len(data)}

    def delete_object(self, **kwargs):
        key=kwargs["Key"]
        self.deletes.append(key)
        if self.cleanup:
            self.objects.pop(key,None)

    def head_object(self, **kwargs):
        if kwargs["Key"] not in self.objects:
            raise S3Error("404")
        return {}


class Anonymous:
    def get_object(self, **kwargs):
        raise S3Error("AccessDenied")


def run(storage, anonymous=None):
    return check_storage(client=storage,anonymous=anonymous or Anonymous(),
                         bucket="private-test",payload=synthetic_image())


def test_probe_checks_privacy_and_removes_only_its_synthetic_object():
    storage=Storage()
    storage.objects["academy/quarantine/keep"]=b"do not touch"
    assert all(run(storage).values())
    assert storage.objects=={"academy/quarantine/keep":b"do not touch"}
    assert len(set(storage.writes))==1 and storage.deletes==storage.writes[:1]


@pytest.mark.parametrize("versioning",["Enabled","Suspended"])
def test_versioned_buckets_fail_before_writes(versioning):
    storage=Storage(versioning=versioning)
    assert not run(storage)["versioning_disabled"]
    assert not storage.writes and not storage.deletes


def test_unconditional_provider_and_public_bucket_fail():
    storage=Storage(conditional=False)
    result=run(storage,anonymous=storage)
    assert not result["conditional_write"]
    assert not result["anonymous_denied"]
    assert result["cleanup"]


def test_cleanup_failure_reports_only_synthetic_key():
    storage=Storage(cleanup=False)
    result=run(storage)
    assert not result["cleanup"]
    assert result["cleanup_key"]==storage.writes[0]
    assert result["cleanup_key"].startswith("academy/preflight/")


def test_anonymous_network_failure_is_not_a_privacy_pass():
    class Offline:
        def get_object(self, **kwargs):
            raise OSError("network unavailable")
    result=run(Storage(),anonymous=Offline())
    assert not result["anonymous_denied"] and result["cleanup"]
