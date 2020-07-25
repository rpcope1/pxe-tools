import logging
import argparse
import os

from pxe_tools.tftp.server import TFTPServer, disable_factory, BasicReadHandler


argument_parser = argparse.ArgumentParser()
argument_parser.add_argument("base_dir", type=str, help="Base directory to serve out of.")
argument_parser.add_argument("-l", "--log-file", type=str, default="-", help="The file to log to. Default: STDERR.")
argument_parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging.")
argument_parser.add_argument("-C", "--chroot", type=str, default=None, help="The chroot to run in.")
argument_parser.add_argument("-H", "--host", type=str, default="127.0.0.1", help="The host address to bind to.")
argument_parser.add_argument("-p", "--port", type=int, default=69, help="The port to bind to.")
argument_parser.add_argument(
    "-t", "--default-timeout", type=int, default=30, help="The default timeout for TFTP connections."
)

basic_server_logger = logging.getLogger(__name__)


def main(cmd_args=None):
    cmd_args = cmd_args or argument_parser.parse_args()

    root_logger = logging.getLogger('')
    if cmd_args.log_file == "-":
        handler = logging.StreamHandler()
    else:
        handler = logging.FileHandler(cmd_args.log_file)
    formatter = logging.Formatter(
        "[%(asctime)s] - %(levelname)s - %(message)s - "
        "(%(name)s : %(funcName)s : %(lineno)d : Thread/PID(%(thread)d/%(process)d))"
    )
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    if cmd_args.verbose:
        root_logger.setLevel(logging.DEBUG)
    else:
        root_logger.setLevel(logging.INFO)

    try:
        base_dir = os.path.abspath(cmd_args.base_dir)
        if cmd_args.chroot:
            chroot = os.path.abspath(cmd_args.chroot)
            if not base_dir.startswith(chroot):
                raise Exception("Base dir must be rooted in chosen chroot.")
            basic_server_logger.info("Changing root to: {0}".format(cmd_args.chroot))
            os.chroot(chroot)
            base_dir = base_dir[len(chroot):]

        server = TFTPServer(
            lambda *args, **kwargs: BasicReadHandler.factory(*args, **kwargs, base_dir=base_dir),
            disable_factory,
            cmd_args.host,
            cmd_args.port,
            timeout=cmd_args.default_timeout
        )
        basic_server_logger.info("Starting main loop...")
        server.serve_forever()
    except BaseException:
        basic_server_logger.exception("Unhandled exception caught!")
        raise
