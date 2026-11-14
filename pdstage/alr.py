"""Reader for .alr containers.

Container layout follows the desert-breeze-dust notes for the original Xbox release; the
UWP release uses the same header (checked on every Map/stNN.alr).
"""
import struct

MAGIC = 0x11


def header(b):
    magic, header_size, flags, meta_size = struct.unpack_from('<4I', b, 0)
    if magic != MAGIC:
        raise ValueError('not an .alr file (magic %#x)' % magic)
    n_roots = struct.unpack_from('<H', b, 0x10)[0]
    data_size = struct.unpack_from('<I', b, 0x14)[0]
    roots = list(struct.unpack_from('<%dI' % n_roots, b, 0x20))
    return dict(header_size=header_size, flags=flags, meta_size=meta_size,
                n_roots=n_roots, data_size=data_size, roots=roots)


def chain(b, off, limit=100000):
    """Records starting at a root offset: list of (offset, type, size). Ends with type 0."""
    out = []
    while off + 8 <= len(b) and len(out) < limit:
        t, s = struct.unpack_from('<2I', b, off)
        out.append((off, t, s))
        if t == 0 or s == 0:
            break
        off += s
    return out


def skeleton(b, root_off):
    """Node list (record type 3) of one root: dicts with t, rot, scale, flags, id, parent.
    Entries are 64 bytes from record offset +16. Mesh records (type 2) name their node at +0x42."""
    c = chain(b, root_off)
    sk = [x for x in c if x[1] == 3]
    if not sk:
        return [], {}
    off, _, size = sk[0]
    nodes = []
    for i in range((size - 16) // 64):
        e = off + 16 + i * 64
        f = struct.unpack_from('<9f', b, e)
        flags, nid, _unk, parent = struct.unpack_from('<4H', b, e + 36)
        nodes.append(dict(t=f[0:3], rot=f[3:6], scale=f[6:9], flags=flags, id=nid,
                          parent=None if parent == 0xFFFF else parent))
    meshes_per_node = {}
    for o, t, _ in c:
        if t == 2:
            n = struct.unpack_from('<H', b, o + 0x42)[0]
            meshes_per_node[n] = meshes_per_node.get(n, 0) + 1
    return nodes, meshes_per_node
