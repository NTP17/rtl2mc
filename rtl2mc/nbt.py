"""Minimal lossless tag tree reader/writer for vanilla level.dat metadata."""
import gzip
import io
import struct


def read_tag(stream, kind):
    def unpack(fmt):
        size = struct.calcsize(fmt)
        value = stream.read(size)
        if len(value) != size:
            raise ValueError("Truncated NBT")
        return struct.unpack(fmt, value)[0]
    def string():
        size = unpack(">H")
        value = stream.read(size)
        if len(value) != size:
            raise ValueError("Truncated NBT string")
        # Preserve modified UTF-8 bytes in unmodified strings.
        return value
    if kind in (1, 2, 3, 4, 5, 6):
        return unpack({1: ">b", 2: ">h", 3: ">i", 4: ">q", 5: ">f", 6: ">d"}[kind])
    if kind == 8:
        return string()
    if kind == 10:
        result = {}
        while True:
            tag = unpack(">B")
            if tag == 0:
                return result
            key = string()
            if key in result:
                raise ValueError("Duplicate NBT compound key")
            result[key] = (tag, read_tag(stream, tag))
    if kind in (7, 9, 11, 12):
        subtype = unpack(">B") if kind == 9 else {7: 1, 11: 3, 12: 4}[kind]
        count = unpack(">i")
        if not 0 <= count <= 16_000_000 or (subtype == 0 and count):
            raise ValueError("Invalid NBT array length")
        values = [read_tag(stream, subtype) for _ in range(count)]
        return (subtype, values) if kind == 9 else values
    raise ValueError("Unsupported NBT tag: " + str(kind))


def encode(kind, value):
    def string(data):
        return struct.pack(">H", len(data)) + data
    if kind in (1, 2, 3, 4, 5, 6):
        return struct.pack({1: ">b", 2: ">h", 3: ">i", 4: ">q", 5: ">f", 6: ">d"}[kind], value)
    if kind == 8:
        return string(value)
    if kind == 10:
        return b"".join(bytes([t]) + string(k) + encode(t, v) for k, (t, v) in value.items()) + b"\0"
    if kind in (7, 9, 11, 12):
        sub, vals = value if kind == 9 else ({7: 1, 11: 3, 12: 4}[kind], value)
        return (bytes([sub]) if kind == 9 else b"") + struct.pack(">i", len(vals)) + b"".join(encode(sub, v) for v in vals)
    raise ValueError("Unsupported NBT tag")


def unpack(data):
    stream = io.BytesIO(data)
    if stream.read(1) != b"\x0a":
        raise ValueError("level.dat root must be a compound")
    name = read_tag(stream, 8)
    root = read_tag(stream, 10)
    if stream.read():
        raise ValueError("Trailing data after NBT root")
    return name, root


def configure_world(path, name):
    root_name, root = unpack(gzip.decompress(path.read_bytes()))
    data = root[b"Data"][1]
    data[b"allowCommands"] = (1, 1)
    data[b"GameType"] = (3, 1)
    data[b"LevelName"] = (8, name.encode("utf-8"))
    path.write_bytes(gzip.compress(b"\x0a" + encode(8, root_name) + encode(10, root), mtime=0))
