from pxe_tools.exceptions import PXEToolsException


class TFTPException(PXEToolsException):
    pass


class TFTPInvalidProtocolException(TFTPException):
    pass
