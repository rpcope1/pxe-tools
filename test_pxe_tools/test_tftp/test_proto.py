import pytest
from unittest.mock import patch

from pxe_tools.tftp.proto import decode_tftp_datagram, encode_tftp_datagram, ReadRequestPacket, WriteRequestPacket, \
    DataPacket, AcknowledgementPacket, ErrorPacket, OptionsAcknowledgementPacket, TFTPOption, \
    to_netascii, from_netascii

def test_read_request_decode(raw_read_request, request_filename, request_mode):
    decoded = decode_tftp_datagram(raw_read_request)
    assert isinstance(decoded, ReadRequestPacket)
    assert decoded.filename == request_filename
    assert decoded.mode == request_mode
    assert raw_read_request == encode_tftp_datagram(decoded)


def test_write_request_decode(raw_write_request, request_filename, request_mode):
    decoded = decode_tftp_datagram(raw_write_request)
    assert isinstance(decoded, WriteRequestPacket)
    assert decoded.filename == request_filename
    assert decoded.mode == request_mode
    assert raw_write_request == encode_tftp_datagram(decoded)


def test_read_request_with_options(raw_read_request_with_options, request_filename, request_mode, option_map):
    decoded = decode_tftp_datagram(raw_read_request_with_options)
    assert isinstance(decoded, ReadRequestPacket)
    assert decoded.filename == request_filename
    assert decoded.mode == request_mode
    for opt in decoded.options:
        assert isinstance(opt, TFTPOption)
        assert option_map.get(opt.name) == opt.value
    assert raw_read_request_with_options == encode_tftp_datagram(decoded)


def test_write_request_with_options(raw_write_request_with_options, request_filename, request_mode, option_map):
    decoded = decode_tftp_datagram(raw_write_request_with_options)
    assert isinstance(decoded, WriteRequestPacket)
    assert decoded.filename == request_filename
    assert decoded.mode == request_mode
    for opt in decoded.options:
        assert isinstance(opt, TFTPOption)
        assert option_map.get(opt.name) == opt.value
    assert raw_write_request_with_options == encode_tftp_datagram(decoded)


def test_data_decode(raw_data_packet, block_number, data_payload):
    decoded = decode_tftp_datagram(raw_data_packet)
    assert isinstance(decoded, DataPacket)
    assert decoded.block_number == block_number
    assert decoded.data == data_payload
    assert raw_data_packet == encode_tftp_datagram(decoded)


def test_ack_decode(raw_ack_packet, block_number):
    decoded = decode_tftp_datagram(raw_ack_packet)
    assert isinstance(decoded, AcknowledgementPacket)
    assert decoded.block_number == block_number
    assert raw_ack_packet == encode_tftp_datagram(decoded)


def test_opt_ack_decode(raw_opt_ack_packet, option_map):
    decoded = decode_tftp_datagram(raw_opt_ack_packet)
    assert isinstance(decoded, OptionsAcknowledgementPacket)
    for opt in decoded.options:
        assert isinstance(opt, TFTPOption)
        assert option_map.get(opt.name) == opt.value
    assert raw_opt_ack_packet == encode_tftp_datagram(decoded)


def test_error_packet_decode(raw_error_packet, error_code, error_message):
    decoded = decode_tftp_datagram(raw_error_packet)
    assert isinstance(decoded, ErrorPacket)
    assert decoded.error_code == error_code
    assert decoded.error_message == error_message
    assert raw_error_packet == encode_tftp_datagram(decoded)


@pytest.mark.parametrize(
    "test_payload",
    [
        b""
        b"foobar"
        b"bar\nbaz\n",
        b"\r\n\r"
        b"\r",
        b"\rwat\n\n\nfoo\n"
    ]
)
@pytest.mark.parametrize(
    "sep",
    [b"\r\n", b"\n"]
)
def test_netascii_encode_decode(test_payload, sep):
    with patch("pxe_tools.tftp.proto._LINE_SEP", sep):
        assert test_payload == from_netascii(to_netascii(test_payload))
