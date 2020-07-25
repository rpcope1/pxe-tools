import struct
import os
import re
from collections import namedtuple

from pxe_tools.tftp.exceptions import TFTPInvalidProtocolException
from pxe_tools.utils import unpack_c_strs, pack_c_str, pack_c_strs, unpack_c_str


TFTPOpCode = namedtuple('TFTPOpCode', ('value', 'name', 'description', 'packet_class'))
TFTPErrorCode = namedtuple('TFTPErrorCode', ('value', 'name', 'meaning'))

SHORT_LEN = struct.calcsize("!H")

_LINE_SEP = os.linesep.encode("ascii")


def to_netascii(payload):
    def _fix(match):
        gd = match.groupdict()
        if gd["replace"] == _LINE_SEP:
            return b"\r\n"
        else:
            return b"\r\x00"
    return re.sub(b"(?P<replace>(" + _LINE_SEP + b"|\r))", _fix, payload)


def from_netascii(payload):
    def _fix(match):
        gd = match.groupdict()
        if gd["replace"] == b"\r\n":
            return _LINE_SEP
        else:
            return b"\r"
    return re.sub(b"(?P<replace>(\r\n|\r\x00))", _fix, payload)


class TFTPOption(object):
    def __init__(self, name, value):
        self.name = name
        self.value = value

    def __repr__(self):
        return "TFTPOption(name: {0}, value: {1})".format(self.name, self.value)

    def __str__(self):
        return self.__repr__()

    def encode(self):
        return pack_c_strs([self.name, self.value])

    @classmethod
    def build_from_strs(cls, s):
        return [cls(s[i], s[i+1]) for i in range(0, len(s), 2)]


class TFTPPacket(object):
    def encode(self):
        raise NotImplementedError

    @classmethod
    def decode(cls, raw_datagram):
        raise NotImplementedError


class ReadRequestPacket(TFTPPacket):
    OPCODE_VALUE = 1

    def __init__(self, filename, mode, options=None):
        self.filename = filename
        self.mode = mode
        self.options = options or []

    def __repr__(self):
        return "ReadRequestPacket(filename={0} mode={1} options={2})".format(
            self.filename, self.mode, "(" + ",".join(str(op) for op in self.options) + ")"
        )

    def __str__(self):
        return self.__repr__()

    def encode(self):
        return struct.pack('!H', self.OPCODE_VALUE) + pack_c_strs([self.filename, self.mode]) + b"".join([
            op.encode() for op in self.options
        ])

    @classmethod
    def decode(cls, raw_datagram):
        oc, = struct.unpack('!H', raw_datagram[:SHORT_LEN])
        assert oc == cls.OPCODE_VALUE, 'Incorrect opcode for read request packet.'
        params = unpack_c_strs(raw_datagram[SHORT_LEN:])
        if len(params) < 2 or len(params) % 2 != 0:
            raise TFTPInvalidProtocolException("Bad read request packet.")
        filename, mode = params[0], params[1]
        return cls(filename, mode, TFTPOption.build_from_strs(params[2:]))

    @property
    def option_map(self):
        return {op.name: op.value for op in self.options}


class WriteRequestPacket(TFTPPacket):
    OPCODE_VALUE = 2

    def __init__(self, filename, mode, options=None):
        self.filename = filename
        self.mode = mode
        self.options = options or []

    def __repr__(self):
        return "ReadRequestPacket(filename={0} mode={1} options={2})".format(
            self.filename, self.mode, "(" + ",".join(str(op) for op in self.options) + ")"
        )

    def __str__(self):
        return self.__repr__()

    def encode(self):
        return struct.pack('!H', self.OPCODE_VALUE) + pack_c_strs([self.filename, self.mode]) + b"".join([
            op.encode() for op in self.options
        ])

    @classmethod
    def decode(cls, raw_datagram):
        oc, = struct.unpack('!H', raw_datagram[:SHORT_LEN])
        assert oc == cls.OPCODE_VALUE, 'Incorrect opcode for write request packet.'
        params = unpack_c_strs(raw_datagram[SHORT_LEN:])
        if len(params) < 2 or len(params) % 2 != 0:
            raise TFTPInvalidProtocolException("Bad write request packet.")
        filename, mode = params[0], params[1]
        return cls(filename, mode, TFTPOption.build_from_strs(params[2:]))

    @property
    def option_map(self):
        return {op.name: op.value for op in self.options}


class DataPacket(TFTPPacket):
    OPCODE_VALUE = 3

    def __init__(self, block_number, data):
        self.block_number = block_number
        self.data = data

    def __repr__(self):
        return "DataPacket(block={0})".format(self.block_number)

    def __str__(self):
        return self.__repr__()

    def encode(self):
        return struct.pack('!HH', self.OPCODE_VALUE, self.block_number) + self.data

    @classmethod
    def decode(cls, raw_datagram):
        oc, block_number = struct.unpack('!HH', raw_datagram[:2*SHORT_LEN])
        assert oc == cls.OPCODE_VALUE, 'Incorrect opcode for data packet.'
        return cls(block_number, raw_datagram[2*SHORT_LEN:])


class AcknowledgementPacket(TFTPPacket):
    OPCODE_VALUE = 4

    def __init__(self, block_number):
        self.block_number = block_number

    def __repr__(self):
        return "AckPacket(block={0})".format(self.block_number)

    def __str__(self):
        return self.__repr__()

    def encode(self):
        return struct.pack('!HH', self.OPCODE_VALUE, self.block_number)

    @classmethod
    def decode(cls, raw_datagram):
        oc, block_number = struct.unpack('!HH', raw_datagram[:2*SHORT_LEN])
        assert oc == cls.OPCODE_VALUE, 'Incorrect opcode for acknowledgement packet.'
        return cls(block_number)


class ErrorPacket(TFTPPacket):
    OPCODE_VALUE = 5

    class ErrorCodes(object):
        NOT_DEFINED = TFTPErrorCode(0, "NOT_DEFINED", "Not defined, see error message (if any).")
        FILE_NOT_FOUND = TFTPErrorCode(
            1, "FILE_NOT_FOUND", "File not found."
        )
        ACCESS_VIOLATION = TFTPErrorCode(
            2, "ACCESS_VIOLATION", "Access violation."
        )
        DISK_FULL = TFTPErrorCode(
            3, "DISK_FULL", "Disk full or allocation exceeded."
        )
        ILLEGAL_OP = TFTPErrorCode(
            4, "ILLEGAL_OP", "Illegal TFTP operation."
        )
        UNKNOWN_TID = TFTPErrorCode(
            5, "UNKNOWN_TID", "Unknown Transfer ID."
        )
        FILE_ALREADY_EXISTS = TFTPErrorCode(
            6, "FILE_ALREADY_EXISTS", "File already exists."
        )
        NO_SUCH_USER = TFTPErrorCode(
            7, "NO_SUCH_USER", "No such user."
        )
        OPTION_NEGOTIOATION_ERROR = TFTPErrorCode(
            8, "OPTION_NEGOTIATION_ERROR", "Option negotiation error."
        )

        _ALL_ERROR_CODES = [
            NOT_DEFINED, FILE_NOT_FOUND, ACCESS_VIOLATION, DISK_FULL, ILLEGAL_OP,
            UNKNOWN_TID, FILE_ALREADY_EXISTS, NO_SUCH_USER, OPTION_NEGOTIOATION_ERROR
        ]

        ERROR_CODE_MAP = {
            ec.value: ec for ec in _ALL_ERROR_CODES
        }

    def __init__(self, error_code, error_message):
        self.error_code = error_code
        self.error_message = error_message

    def __repr__(self):
        ec = self.ErrorCodes.ERROR_CODE_MAP.get(self.error_code)
        if ec:
            name = ec.name
        else:
            name = "???"

        return "ErrorPacket(error_code={0}, name={1}, message={2})".format(
            self.error_code, name, self.error_message,
        )

    def __str__(self):
        return self.__repr__()

    @classmethod
    def init_from_error_code(cls, ec_obj, message):
        return cls(ec_obj.value, message)

    def encode(self):
        return struct.pack('!HH', self.OPCODE_VALUE, self.error_code) + pack_c_str(self.error_message)

    @classmethod
    def decode(cls, raw_datagram):
        oc, error_code = struct.unpack('!HH', raw_datagram[:SHORT_LEN*2])
        assert oc == cls.OPCODE_VALUE, 'Incorrect opcode for error packet.'
        error_message, _ = unpack_c_str(raw_datagram[SHORT_LEN*2:])
        return cls(error_code, error_message)

    @property
    def error_name(self):
        if self.error_code in self.ErrorCodes.ERROR_CODE_MAP:
            return self.ErrorCodes.ERROR_CODE_MAP[self.error_code].name
        else:
            return "???"

    @property
    def error_meaning(self):
        if self.error_code in self.ErrorCodes.ERROR_CODE_MAP:
            return self.ErrorCodes.ERROR_CODE_MAP[self.error_code].meaning
        else:
            return "???"


class OptionsAcknowledgementPacket(TFTPPacket):
    OPCODE_VALUE = 6

    def __init__(self, options):
        self.options = options or []

    def __repr__(self):
        return "OptionsAcknowledgementPacket(options={0})".format(
            "(" + ",".join(str(op) for op in self.options) + ")"
        )

    def __str__(self):
        return self.__repr__()

    def encode(self):
        return struct.pack('!H', self.OPCODE_VALUE) + b"".join([op.encode() for op in self.options])

    @classmethod
    def decode(cls, raw_datagram):
        oc, = struct.unpack('!H', raw_datagram[:SHORT_LEN])
        assert oc == cls.OPCODE_VALUE, 'Incorrect opcode for write request packet.'
        params = unpack_c_strs(raw_datagram[SHORT_LEN:])
        if len(params) % 2 != 0:
            raise TFTPInvalidProtocolException("Bad option acknowledgment packet.")
        return cls(TFTPOption.build_from_strs(params))

    @property
    def option_map(self):
        return {op.name: op.value for op in self.options}


class TFTPOpCodes(object):
    RRQ = TFTPOpCode(ReadRequestPacket.OPCODE_VALUE, 'RRQ', 'Read Request', ReadRequestPacket)
    WRQ = TFTPOpCode(WriteRequestPacket.OPCODE_VALUE, 'WRQ', 'Write Request', WriteRequestPacket)
    DATA = TFTPOpCode(DataPacket.OPCODE_VALUE, 'DATA', 'Data', DataPacket)
    ACK = TFTPOpCode(AcknowledgementPacket.OPCODE_VALUE, 'ACK', 'Acknowledgement', AcknowledgementPacket)
    ERROR = TFTPOpCode(ErrorPacket.OPCODE_VALUE, 'ERROR', 'Error', ErrorPacket)
    OACK = TFTPOpCode(
        OptionsAcknowledgementPacket.OPCODE_VALUE, 'OPACK', 'Options Acknowledgement', OptionsAcknowledgementPacket
    )

    _ALL_OPCODES = [
        RRQ, WRQ, DATA, ACK, ERROR, OACK
    ]

    OPCODE_MAP = {
        OC.value: OC for OC in _ALL_OPCODES
    }


def decode_tftp_datagram(raw_datagram):
    opcode_value, = struct.unpack('!H', raw_datagram[:SHORT_LEN])
    if opcode_value in TFTPOpCodes.OPCODE_MAP:
        return TFTPOpCodes.OPCODE_MAP[opcode_value].packet_class.decode(raw_datagram)
    else:
        raise TypeError('Unknown TFTP opcode: {0}'.format(opcode_value))


def encode_tftp_datagram(packet):
    assert isinstance(packet, TFTPPacket), "Can not encode data that is not a TFTPPacket instance."
    return packet.encode()
