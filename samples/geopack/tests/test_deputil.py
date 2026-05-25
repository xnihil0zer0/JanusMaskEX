from geopack.deputil import camelize_label


def test_camelize_label():
    assert camelize_label("device_type") == "DeviceType"
    assert camelize_label("user") == "User"
