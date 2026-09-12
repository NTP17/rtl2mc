"""Small RCON client for short, local Minecraft commands and responses."""
import socket
import struct


class RconError(RuntimeError):
    pass


def encode_packet(request_id, packet_type, body):
    data = body.encode("utf-8")
    if b"\0" in data or len(data) > 4000:
        raise RconError("Command contains NUL or exceeds this client's short-command limit")
    return struct.pack("<iii", len(data) + 10, request_id, packet_type) + data + b"\0\0"


def read_exact(connection, count):
    parts = bytearray()
    while len(parts) < count:
        chunk = connection.recv(count - len(parts))
        if not chunk:
            raise RconError("RCON connection closed in the middle of a packet")
        parts.extend(chunk)
    return bytes(parts)


def read_packet(connection):
    size = struct.unpack("<i", read_exact(connection, 4))[0]
    if not 10 <= size <= 4110:
        raise RconError(f"Unexpected RCON packet length: {size}")
    data = read_exact(connection, size)
    if data[-2:] != b"\0\0":
        raise RconError("Malformed RCON packet terminator")
    request_id, packet_type = struct.unpack("<ii", data[:8])
    return request_id, packet_type, data[8:-2].decode("utf-8")


class Rcon:
    def __init__(self, port, password, log=None):
        self.connection = socket.create_connection(("127.0.0.1", port), timeout=10)
        self.connection.settimeout(30)
        self.sequence = 1
        self.log = log
        try:
            self.connection.sendall(encode_packet(self.sequence, 3, password))
            # Some implementations send an empty value packet before auth.
            for _ in range(2):
                request_id, packet_type, _ = read_packet(self.connection)
                if request_id == -1:
                    raise RconError("RCON authentication failed")
                if request_id != self.sequence:
                    raise RconError("Unexpected RCON authentication request id")
                if packet_type == 2:
                    return
            raise RconError("No RCON authentication response")
        except BaseException:
            self.connection.close()
            raise

    def command(self, text):
        self.sequence += 1
        self.connection.sendall(encode_packet(self.sequence, 2, text))
        request_id, packet_type, response = read_packet(self.connection)
        if request_id != self.sequence or packet_type != 0:
            raise RconError("Unexpected RCON response; no further commands were sent")
        if self.log:
            self.log({"command": text, "response": response})
        return response

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

