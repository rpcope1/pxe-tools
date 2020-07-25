import select


class ReactorMode(object):
    READ = 'read'
    WRITE = 'write'
    EXCEPTION = 'exception'

    ALL = {READ, WRITE, EXCEPTION}


class Reactor(object):
    @staticmethod
    def _mode_check(modes):
        if not isinstance(modes, (list, set, tuple)):
            modes = [modes]
        for mode in modes:
            assert mode in ReactorMode.ALL
        return modes

    def register(self, fd, modes):
        raise NotImplementedError

    def modify(self, fd, modes):
        raise NotImplementedError

    def unregister(self, fd):
        raise NotImplementedError

    def poll(self, timeout=None):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError


class SelectReactor(Reactor):
    def __init__(self, *args, **kwargs):
        self.fds = {}

    @property
    def _read_fds(self):
        return [k for k, v in self.fds.items() if ReactorMode.READ in v]

    @property
    def _write_fds(self):
        return [k for k, v in self.fds.items() if ReactorMode.WRITE in v]

    @property
    def _exception_fds(self):
        return [k for k, v in self.fds.items() if ReactorMode.EXCEPTION in v]

    def register(self, fd, modes):
        self.fds[fd] = self._mode_check(modes)

    def modify(self, fd, modes):
        if fd not in self.fds:
            raise OSError("FD {0} not registered.".format(fd))
        self.fds[fd] = self._mode_check(modes)

    def unregister(self, fd):
        if fd in self.fds:
            self.fds.pop(fd)
        else:
            raise KeyError("No such fd {0} registered.".format(fd))

    def poll(self, timeout=None):
        return select.select(self._read_fds, self._write_fds, self._exception_fds, timeout)

    def close(self):
        pass


if hasattr(select, 'poll'):
    class PollReactor(Reactor):
        def __init__(self, *args, **kwargs):
            self.poll_object = select.poll()

        def _modes_to_mask(self, modes):
            modes = self._mode_check(modes)
            mask = 0x0
            if ReactorMode.READ in modes:
                mask |= select.POLLIN
            if ReactorMode.WRITE in modes:
                mask |= select.POLLOUT
            if ReactorMode.EXCEPTION in modes:
                mask |= select.POLLERR
            return mask

        @staticmethod
        def _poll_result_to_lists(result):
            rlist, wlist, xlist = [], [], []
            for fd, event in result:
                if event & select.POLLIN:
                    rlist.append(fd)
                if event & select.POLLOUT:
                    wlist.append(fd)
                if event & select.POLLERR:
                    xlist.append(fd)
            return rlist, wlist, xlist

        def register(self, fd, modes):
            self.poll_object.register(fd, self._modes_to_mask(modes))

        def modify(self, fd, modes):
            self.poll_object.modify(fd, self._modes_to_mask(modes))

        def unregister(self, fd):
            self.poll_object.unregister(fd)

        def poll(self, timeout=None):
            result = self.poll_object.poll(timeout)
            return self._poll_result_to_lists(result)

        def close(self):
            self.poll_object.close()

else:
    PollReactor = None

if hasattr(select, 'epoll'):
    class EpollReactor(Reactor):
        def __init__(self, *args, **kwargs):
            self.epoll_object = select.epoll()

        def _modes_to_mask(self, modes):
            modes = self._mode_check(modes)
            mask = 0x0
            if ReactorMode.READ in modes:
                mask |= select.EPOLLIN
            if ReactorMode.WRITE in modes:
                mask |= select.EPOLLOUT
            if ReactorMode.EXCEPTION in modes:
                mask |= select.EPOLLERR
            return mask

        @staticmethod
        def _poll_result_to_lists(result):
            rlist, wlist, xlist = [], [], []
            for fd, event in result:
                if event & select.EPOLLIN:
                    rlist.append(fd)
                if event & select.EPOLLOUT:
                    wlist.append(fd)
                if event & select.EPOLLERR:
                    xlist.append(fd)
            return rlist, wlist, xlist

        def register(self, fd, modes):
            self.epoll_object.register(fd, self._modes_to_mask(modes))

        def modify(self, fd, modes):
            self.epoll_object.modify(fd, self._modes_to_mask(modes))

        def unregister(self, fd):
            self.epoll_object.unregister(fd)

        def poll(self, timeout=None):
            result = self.epoll_object.poll(timeout)
            return self._poll_result_to_lists(result)

        def close(self):
            self.epoll_object.close()

else:
    EpollReactor = None


def create_reactor(*args, **kwargs):
    if EpollReactor is not None:
        return EpollReactor(*args, **kwargs)
    elif PollReactor is not None:
        return PollReactor(*args, **kwargs)
    else:
        return SelectReactor(*args, **kwargs)
