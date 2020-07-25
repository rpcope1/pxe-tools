import pytest
import struct


@pytest.fixture
def request_filename():
    return "foobar"


@pytest.fixture
def request_mode():
    return "octet"


@pytest.fixture
def block_number():
    return 1


@pytest.fixture
def error_code():
    return 1


@pytest.fixture
def error_message():
    return "???"


@pytest.fixture
def options():
    return [
        ("foobar", "baz"),
        ("test", "test")
    ]


@pytest.fixture
def option_map(options):
    return {o[0]: o[1] for o in options}


@pytest.fixture
def encoded_options(options):
    return b"".join(n.encode("ascii") + b"\x00" + v.encode("ascii") + b"\x00" for n, v in options)


@pytest.fixture
def block_number_encoded(block_number):
    return struct.pack('!H', block_number)


@pytest.fixture()
def data_payload():
    return b"\x5E" * 512


@pytest.fixture
def raw_read_request(request_filename, request_mode):
    return b'\x00\x01' + request_filename.encode("ascii") + b"\x00" + request_mode.encode("ascii") + b"\x00"


@pytest.fixture
def raw_write_request(request_filename, request_mode):
    return b'\x00\x02' + request_filename.encode("ascii") + b"\x00" + request_mode.encode("ascii") + b"\x00"


@pytest.fixture
def raw_read_request_with_options(raw_read_request, encoded_options):
    return raw_read_request + encoded_options


@pytest.fixture
def raw_write_request_with_options(raw_write_request, encoded_options):
    return raw_write_request + encoded_options


@pytest.fixture
def raw_data_packet(block_number_encoded, data_payload):
    return b'\x00\x03' + block_number_encoded + data_payload


@pytest.fixture
def raw_ack_packet(block_number_encoded):
    return b'\x00\x04' + block_number_encoded


@pytest.fixture
def raw_error_packet(error_code, error_message):
    return b'\x00\x05' + struct.pack('!H', error_code) + error_message.encode('ascii') + b'\x00'


@pytest.fixture
def raw_opt_ack_packet(encoded_options):
    return b'\x00\x06' + encoded_options
