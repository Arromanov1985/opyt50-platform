from fastapi import HTTPException
import pytest
from app.academy_rendition_delivery import byte_range


@pytest.mark.parametrize("header,expected",[
    (None,(0,99,200)),
    ("bytes=0-9",(0,9,206)),
    ("bytes=90-200",(90,99,206)),
    ("bytes=10-",(10,99,206)),
    ("bytes=-10",(90,99,206)),
    ("bytes=-200",(0,99,206)),
])
def test_single_byte_range(header,expected):
    assert byte_range(header,100)==expected


@pytest.mark.parametrize("header",[
    "bytes=100-","bytes=10-9","bytes=-0","bytes=-","bytes=0-1,3-4",
    "items=0-1","bytes=9999999999999-","bytes=+1-2",
])
def test_invalid_byte_range(header):
    with pytest.raises(HTTPException) as invalid:
        byte_range(header,100)
    assert invalid.value.status_code==416
    assert invalid.value.headers["Content-Range"]=="bytes */100"
