from pxe_tools.exceptions import PXEToolsException
import select


class UnterminatedString(ValueError, PXEToolsException):
    pass


def unpack_c_str(s):
    try:
        null_terminator_index = s.index(b"\0")
        return s[:null_terminator_index].decode("ascii"), null_terminator_index
    except ValueError:
        raise UnterminatedString("Bytes-like: {0} is not a valid null terminated string!".format(s))


def unpack_c_strs(s):
    strings = []
    while s:
        substr, ind = unpack_c_str(s)
        strings.append(substr)
        s = s[ind+1:]
    return strings


def pack_c_str(s):
    return bytes(s, 'utf-8') + b"\0"


def pack_c_strs(strs):
    return b"".join(pack_c_str(s) for s in strs)
