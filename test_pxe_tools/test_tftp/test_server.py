from pxe_tools.tftp.server import TFTPServer, AbstractReadHandler, disable_factory, TFTPException
from pxe_tools.tftp.proto import ReadRequestPacket, AcknowledgementPacket, decode_tftp_datagram, DataPacket

import pytest
import socket
import time
import random
import threading

random.seed()


@pytest.fixture
def listen_port():
    return random.randint(32000, 60000)


@pytest.fixture
def file_map():
    return {
        "/foobar": "foobarbaz",
        "/foo/bar": "test" * 2000
    }


@pytest.fixture
def read_handler_factory(file_map):
    class FakeReadHandler(AbstractReadHandler):
        def __init__(self, filename, mode, remote_addr):
            super(FakeReadHandler, self).__init__(filename, mode, remote_addr)
            self._opened = False

        @property
        def length(self):
            if self.filename in file_map:
                return len(file_map[self.filename])

        def open(self):
            if self.filename in file_map:
                self._opened = True
            else:
                raise TFTPException("No such file: {0}".format(self.filename))

        def read(self, start, end):
            return file_map[self.filename][start:end].encode("utf-8")

        def close(self):
            self._opened = False

    return FakeReadHandler


@pytest.mark.parametrize(
    "target_file",
    ["/foobar", "/foo/bar"]
)
def test_server_get_file_no_options(read_handler_factory, listen_port, target_file, file_map):
    s = TFTPServer(
        read_handler_factory, disable_factory, "127.0.0.1", listen_port
    )
    t = threading.Thread(target=s.serve_forever)
    t.start()
    time.sleep(1)

    client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        client_sock.sendto(ReadRequestPacket(target_file, "octet").encode(), ("127.0.0.1", listen_port))
        has_data = True
        expected_block = 1
        reconstructed = bytearray()
        while has_data:
            raw, addr = client_sock.recvfrom(600)
            decoded = decode_tftp_datagram(raw)
            assert isinstance(decoded, DataPacket)
            assert decoded.block_number == expected_block
            reconstructed.extend(decoded.data)
            if len(decoded.data) < 512:
                has_data = False
            client_sock.sendto(AcknowledgementPacket(decoded.block_number).encode(), addr)
            expected_block += 1
        assert reconstructed.decode("utf-8") == file_map[target_file]
    finally:
        client_sock.close()
    s.shutdown()
    t.join(30)
