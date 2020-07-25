import threading
import logging
import socket
import os
import time

from pxe_tools.tftp.proto import decode_tftp_datagram, ReadRequestPacket, WriteRequestPacket, \
    DataPacket, AcknowledgementPacket, OptionsAcknowledgementPacket, ErrorPacket, TFTPOption, \
    to_netascii, from_netascii
from pxe_tools.tftp.exceptions import TFTPException
from pxe_tools.tftp.reactor import ReactorMode, create_reactor


server_logger = logging.getLogger(__name__)

DEFAULT_BLOCK_SIZE = 512


class HandlerException(TFTPException):
    def __init__(self, msg, error_code, *args, **kwargs):
        self.error_code = error_code
        self.msg = msg
        super(HandlerException, self).__init__(msg, *args, **kwargs)


class AbstractReadHandler(object):
    def __init__(self, filename, mode):
        self.filename = filename
        self.mode = mode
        
    @property
    def length(self):
        return None
    
    def open(self):
        raise NotImplementedError

    def read(self, start, end):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError


class AbstractWriteHandler(object):
    def __init__(self, filename, mode):
        self.filename = filename
        self.mode = mode

    def open(self):
        raise NotImplementedError

    def write(self, data):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError


def disable_factory(*args, **kwargs):
    raise HandlerException("Transfer not allowed", ErrorPacket.ErrorCodes.ILLEGAL_OP)


class BasicReadHandler(AbstractReadHandler):
    def __init__(self, filename, mode, base_dir="/"):
        super(BasicReadHandler, self).__init__(filename, mode)
        self.base_dir = base_dir
        self._file_obj = None
        self._last_pos = None
        self._length = None

    @staticmethod
    def _to_bytes(s):
        if isinstance(s, str):
            return s.encode('ascii')
        elif isinstance(s, (bytearray, bytes)):
            return s
        else:
            raise TypeError("Can not convert {0} to bytes-like".format(s))

    def open(self):
        if self.mode.lower() not in {"octet", "netascii"}:
            raise TFTPException("Unsupported mode: {0}".format(self.mode))
        _file_mode = "rb"
        self._file_obj = open(os.path.join(self.base_dir, self.filename), _file_mode)
        self._last_pos = self._file_obj.tell()

    def read(self, start, end):
        if start != self._last_pos:
            self._file_obj.seek(start)
            self._last_pos = self._file_obj.tell()
        data = self._file_obj.read(end - start)
        self._last_pos = self._last_pos + (end - start)
        if self.mode.lower() == "octet":
            return self._to_bytes(data)
        elif self.mode.lower() == "netascii":
            return to_netascii(self._to_bytes(data))
        else:
            assert False, "Should not be here."

    def close(self):
        if self._file_obj:
            self._file_obj.close()

    @property
    def length(self):
        if self._length is None:
            self._length = os.stat(self._file_obj.fileno()).st_size
        return self._length

    @classmethod
    def factory(cls, filename, mode, remote_addr, base_dir="/"):
        return cls(filename, mode, base_dir=base_dir)


class TFTPServerSession(object):
    class Modes(object):
        READ = 'read'
        WRITE = 'write'

        VALID_MODES = {READ, WRITE}

    class KnownOptions(object):
        BLKSIZE = 'blksize'
        TIMEOUT = 'timeout'
        TSIZE = 'tsize'
        WINDOWSIZE = 'windowsize'

    def __init__(self, read_handler_factory, write_handler_factory, initial_request, remote_addr, host, port=0,
                 default_timeout=30, max_retries=3):
        self.read_handler_factory = read_handler_factory
        self.write_handler_factory = write_handler_factory
        self.initial_request = initial_request
        self.remote_addr = remote_addr
        self.host = host
        self.port = port
        self.max_retries = max_retries
        self._sock = None
        self._done = False
        self._mode = None
        self._handler = None
        self._block_size = DEFAULT_BLOCK_SIZE
        self._window_size = 1
        self._timeout = default_timeout
        self._last_packet_received = None
        self._last_block_num = None
        self._final_block_sent = False
        self._retries = 0

        self._last_seen = -1

    def setup(self):

        server_logger.debug("Setting up session..")
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._last_seen = time.time()
        try:
            self._sock.bind((self.host, self.port))
            server_logger.debug("Session for {0} bound to {1}".format(self.remote_addr, self._sock.getsockname()))
            self._sock.connect(self.remote_addr)
            self._sock.settimeout(int(1.2*self._timeout))
            decoded_request = decode_tftp_datagram(self.initial_request)
            if isinstance(decoded_request, ReadRequestPacket):
                server_logger.debug("Read Request Received from {0}.".format(self.remote_addr))
                server_logger.debug("Options: {0}".format(decoded_request.options))
                self._mode = self.Modes.READ
                try:
                    self._handler = self.read_handler_factory(
                        decoded_request.filename, decoded_request.mode, self.remote_addr
                    )
                    assert isinstance(self._handler, AbstractReadHandler)
                    self._handler.open()

                    if decoded_request.options:
                        usable_options = []
                        for option in decoded_request.options:
                            if option.name.lower() == self.KnownOptions.BLKSIZE:
                                requested_block_size = int(option.value)
                                if 8 <= requested_block_size <= 65464:
                                    self._block_size = requested_block_size
                                    usable_options.append(option)
                                else:
                                    self._send_error(
                                        ErrorPacket.ErrorCodes.ILLEGAL_OP,
                                        "Invalid requested block size: {0}".format(requested_block_size)
                                    )
                            elif option.name.lower() == self.KnownOptions.TIMEOUT:
                                requested_timeout = int(option.value)
                                if 1 <= requested_timeout <= 255:
                                    self._timeout = requested_timeout
                                    self._sock.settimeout(int(1.2 * self._timeout))
                                    usable_options.append(option)
                                else:
                                    self._send_error(
                                        ErrorPacket.ErrorCodes.ILLEGAL_OP,
                                        "Invalid timeout: {0}".format(requested_timeout)
                                    )
                            elif option.name.lower() == self.KnownOptions.TSIZE and self._handler.length is not None:
                                usable_options.append(TFTPOption(self.KnownOptions.TSIZE, str(self._handler.length)))
                            elif option.name.lower() == self.KnownOptions.WINDOWSIZE:
                                requested_window_size = int(option.value)
                                if 1 <= requested_window_size <= 65535:
                                    self._window_size = requested_window_size
                                    usable_options.append(option)
                                else:
                                    self._send_error(
                                        ErrorPacket.ErrorCodes.ILLEGAL_OP,
                                        "Invalid requested window size: {0}".format(requested_window_size)
                                    )
                        server_logger.debug("Sending options acknowledgement to {0}".format(self.remote_addr))
                        self._sock.send(
                            OptionsAcknowledgementPacket(usable_options).encode()
                        )
                    else:
                        server_logger.debug("Sending first data block to {0}".format(self.remote_addr))
                        self._send_read_data()
                except HandlerException as e:
                    server_logger.warning(
                        "Handler exception setting up for read request for {0} "
                        "(filename: {1}, mode: {2}, options: {3})..."
                        "".format(self.remote_addr, decoded_request.filename,
                                  decoded_request.mode, decoded_request.options),
                        exc_info=True
                    )
                    self._send_error(e.error_code, e.msg)
                except BaseException as e:
                    server_logger.exception(
                        "Unhandled exception setting up for read request for {0} "
                            "(filename: {1}, mode: {2}, options: {3})..."
                        "".format(self.remote_addr, decoded_request.filename,
                                  decoded_request.mode, decoded_request.options)
                    )
                    self._send_error(ErrorPacket.ErrorCodes.NOT_DEFINED, str(e))
            elif isinstance(decoded_request, WriteRequestPacket):
                self._mode = self.Modes.WRITE
                try:
                    self._handler = self.write_handler_factory(
                        decoded_request.filename, decoded_request.mode, self.remote_addr
                    )
                    assert isinstance(self._handler, AbstractWriteHandler)
                    self._handler.open()
                    if decoded_request.options:
                        usable_options = []
                        for option in decoded_request.options:
                            if option.name.lower() == self.KnownOptions.BLKSIZE:
                                requested_block_size = int(option.value)
                                if 8 <= requested_block_size <= 65464:
                                    self._block_size = requested_block_size
                                    usable_options.append(option)
                                else:
                                    self._send_error(
                                        ErrorPacket.ErrorCodes.ILLEGAL_OP,
                                        "Invalid requested block size: {0}".format(requested_block_size)
                                    )
                            elif option.name.lower() == self.KnownOptions.TIMEOUT:
                                requested_timeout = int(option.value)
                                if 1 <= requested_timeout <= 255:
                                    self._timeout = requested_timeout
                                    usable_options.append(option)
                                else:
                                    self._send_error(
                                        ErrorPacket.ErrorCodes.ILLEGAL_OP,
                                        "Invalid timeout: {0}".format(requested_timeout)
                                    )
                        server_logger.debug("Sending options acknowledgement to {0}".format(self.remote_addr))
                        self._sock.send(
                            OptionsAcknowledgementPacket(usable_options).encode()
                        )
                    else:
                        self._send_write_ack()
                    self._last_seen = time.time()
                except HandlerException as e:
                    self._send_error(e.error_code, e.msg)
                except BaseException as e:
                    self._send_error(ErrorPacket.ErrorCodes.NOT_DEFINED, str(e))
            else:
                self._send_error(
                    ErrorPacket.ErrorCodes.ILLEGAL_OP, "Session not started with RRQ or WRQ!"
                )
        except BaseException:
            self._sock.close()
            raise

    def _send_error(self, error_code, message):
        if self._sock:
            self._sock.send(ErrorPacket.init_from_error_code(error_code, message).encode())
        self._done = True

    def _send_read_data(self):
        if self._sock and self._mode == self.Modes.READ:
            if self._last_packet_received:
                last_block_acknowledged = self._last_packet_received.block_number
            else:
                last_block_acknowledged = 0
            for bn in range(last_block_acknowledged, last_block_acknowledged + self._window_size):

                data = self._handler.read(bn * self._block_size,
                                          (bn + 1) * self._block_size)
                self._sock.send(DataPacket(bn + 1, data).encode())
                self._last_block_num = bn + 1
                if len(data) < self._block_size:
                    self._final_block_sent = True
                    break

    def _send_write_ack(self):
        if self._sock and self._mode == self.Modes.WRITE:
            if self._last_packet_received:
                block_to_acknowledge = self._last_packet_received.block_number
            else:
                block_to_acknowledge = 0
            self._sock.send(AcknowledgementPacket(block_to_acknowledge).encode())
            self._last_block_num = block_to_acknowledge

    @property
    def fd(self):
        return self._sock.fileno()

    def step(self):
        if self.completed:
            return
        packet, address = self._sock.recvfrom(66000)

        assert address == self.remote_addr
        self._last_seen = time.time()
        self._retries = 0
        try:
            decoded_packet = decode_tftp_datagram(packet)
            if self._mode == self.Modes.READ:
                if isinstance(decoded_packet, AcknowledgementPacket):
                    self._last_packet_received = decoded_packet
                    if self._final_block_sent and decoded_packet.block_number == self._last_block_num:
                        server_logger.debug("Final Acknowledgement received from {0}.".format(self.remote_addr))
                        self._done = True
                    elif decoded_packet.block_number >= self._last_packet_received.block_number:
                        server_logger.debug("Acknowledgement received from {0}.".format(self.remote_addr))
                        server_logger.debug("Sending next data packet.")
                        self._send_read_data()
                    else:
                        self._send_error(ErrorPacket.ErrorCodes.ILLEGAL_OP, "Received invalid ACK packet.")
                else:
                    self._send_error(ErrorPacket.ErrorCodes.ILLEGAL_OP, "Did not receive expected ACK packet.")
            elif self._mode == self.Modes.WRITE:
                if isinstance(decoded_packet, DataPacket):
                    if decoded_packet.block_number == self._last_block_num + 1:
                        self._handler.write(decoded_packet.data)
                        self._send_write_ack()
                else:
                    self._send_error(ErrorPacket.ErrorCodes.ILLEGAL_OP, "Did not receive expected DATA packet.")
            else:
                assert False
        except HandlerException as e:
            self._send_error(e.error_code, e.msg)
        except BaseException as e:
            self._send_error(ErrorPacket.ErrorCodes.NOT_DEFINED, str(e))

    @property
    def completed(self):
        return self._done

    @property
    def timed_out(self):
        return (time.time() - self._last_seen) > self._timeout

    def close(self):
        if self._handler:
            self._handler.close()
            self._handler = None
        if self._sock:
            self._sock.close()
            self._sock = None

    def timeout_handler(self):
        try:
            if self._retries < self.max_retries:
                server_logger.debug(
                    "Retrying sending block {0} to {1}"
                    "".format(self._last_packet_received.block_number + 1, self.remote_addr)
                )
                self._retries += 1
                self._send_read_data()
            else:
                server_logger.warning(
                    "Session to {0} timed out..".format(self.remote_addr)
                )
                self._send_error(
                    ErrorPacket.ErrorCodes.NOT_DEFINED, "Session timed out."
                )
        except ConnectionRefusedError:
            server_logger.warning("Unable to send close timeout message.", exc_info=True)
            self._done = True


class TFTPServer(object):
    DEFAULT_PORT = 69

    def __init__(self, read_handler_factory, write_handler_factory, host, port=DEFAULT_PORT, select_poll=5, timeout=30):
        self.read_handler_factory = read_handler_factory
        self.write_handler_factory = write_handler_factory
        self.host = host
        self.port = port
        self.select_poll = select_poll
        self.timeout = timeout
        self.shutdown_event = threading.Event()
        self.server_socket = None
        self.session_map = {}
        self.reactor = None

    def serve_forever(self):
        if self.server_socket is not None:
            return

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            server_logger.debug("Binding to ({0}, {1})".format(self.host, self.port))
            self.server_socket.bind((self.host, self.port))
            server_socket_fd = self.server_socket.fileno()
            self.reactor = create_reactor()
            self.reactor.register(server_socket_fd, ReactorMode.READ)

            server_logger.debug("Starting server mainloop...")
            while not self.shutdown_event.is_set():
                server_logger.debug(
                    "Polling for active file descriptors. {0} open sessions..".format(len(self.session_map.keys()))
                )
                r_list, _, _ = self.reactor.poll(self.select_poll)
                if server_socket_fd in r_list:
                    data, address = self.server_socket.recvfrom(66000)
                    server_logger.debug("New session from {0}.".format(address))
                    new_session = TFTPServerSession(self.read_handler_factory, self.write_handler_factory,
                                                    data, address, self.host, default_timeout=self.timeout)
                    new_session.setup()
                    server_logger.debug("Session setup completed for: {0}.".format(address))
                    self.reactor.register(new_session.fd, ReactorMode.READ)
                    self.session_map[new_session.fd] = new_session
                for fd in r_list:
                    if fd in self.session_map:
                        server_logger.debug(
                            "Stepping session for: {0}.".format(self.session_map[fd].remote_addr)
                        )
                        self.session_map[fd].step()
                    elif fd not in self.session_map and fd != server_socket_fd:
                        server_logger.debug("Unexpected FD detected from reactor: {0}...".format(fd))

                session_fds = list(self.session_map.keys())

                for session_fd in session_fds:
                    if self.session_map[session_fd].timed_out:
                        server_logger.debug(
                            "Session {0} timed out. Cleaning up...".format(self.session_map[session_fd].remote_addr)
                        )
                        self.session_map[session_fd].timeout_handler()

                    if self.session_map[session_fd].completed:
                        server_logger.debug(
                            "Cleaning up session for: {0}.".format(self.session_map[session_fd].remote_addr)
                        )
                        self.reactor.unregister(session_fd)
                        self.session_map.pop(session_fd).close()
            self.server_socket.shutdown(socket.SOCK_DGRAM)

        finally:
            for session in self.session_map.values():
                session.close()

            self.server_socket.close()
            self.server_socket = None
            self.session_map = {}
            if self.reactor:
                self.reactor.close()
                self.reactor = None

    def shutdown(self):
        self.shutdown_event.set()


if __name__ == "__main__":
    root_logger = logging.getLogger('')
    root_logger.addHandler(logging.StreamHandler())
    root_logger.setLevel(logging.DEBUG)
    server = TFTPServer(BasicReadHandler.factory, disable_factory, "127.0.0.1", port=6969)
    server.serve_forever()