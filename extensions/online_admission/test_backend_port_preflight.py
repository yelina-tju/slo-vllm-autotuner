"""Linux loopback-only reproduction; no GPU/model/subprocess invocation."""
import socket
import errno
import sys
import unittest
from owned_backend import check_private_port


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux TCP reuse semantics')
class BackendPortPreflightTest(unittest.TestCase):
    def test_live_listener_is_still_rejected(self):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            with self.assertRaises(OSError) as raised:
                check_private_port(listener.getsockname()[1])
            self.assertEqual(raised.exception.errno, errno.EADDRINUSE)

    def test_time_wait_false_positive_reproduced_without_gpu(self):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
            listener.listen()
            with socket.create_connection(('127.0.0.1', port), timeout=2) as client:
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(2)
                    # Server actively closes first, so its port enters TIME_WAIT.
                    connection.shutdown(socket.SHUT_WR)
                    self.assertEqual(client.recv(1), b'')
                    client.shutdown(socket.SHUT_WR)
                    self.assertEqual(connection.recv(1), b'')
        with socket.socket() as old_probe:
            with self.assertRaises(OSError) as raised:
                old_probe.bind(('127.0.0.1', port))
            self.assertEqual(raised.exception.errno, errno.EADDRINUSE)
        check_private_port(port)


if __name__ == '__main__': unittest.main()
