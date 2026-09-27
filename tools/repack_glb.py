"""Repack a glTF/GLB into a compact GLB, keeping only the animations named (and the meshes/skins).

    python tools/repack_glb.py in.gltf|in.glb out.glb [anim names…|--dedupe]

Used to trim the CC0 Quaternius assets in static/models: the human library ships 46 animations
(we keep ~20), the animals ship each clip twice ("Walk" and "AnimalArmature|Walk")."""
import json
import os
import struct
import sys


def load(path):
    b = open(path, "rb").read()
    if b[:4] == b"glTF":
        jl = struct.unpack("<I", b[12:16])[0]
        j = json.loads(b[20:20 + jl])
        off = 20 + jl
        bl = struct.unpack("<I", b[off:off + 4])[0]
        return j, b[off + 8:off + 8 + bl]
    j = json.load(open(path))
    bin_ = open(os.path.join(os.path.dirname(path), j["buffers"][0]["uri"]), "rb").read()
    return j, bin_


def repack(j, bin_, keep=None, dedupe=False):
    anims = j.get("animations", [])
    if dedupe:
        seen, out = set(), []
        for a in anims:
            short = a["name"].split("|")[-1]
            if short not in seen:
                seen.add(short)
                a["name"] = short
                out.append(a)
        anims = out
    if keep:
        anims = [a for a in anims if a["name"] in keep]
    j["animations"] = anims
    used = set()
    for m in j.get("meshes", []):
        for p in m["primitives"]:
            used.update(p["attributes"].values())
            if "indices" in p:
                used.add(p["indices"])
            for t in p.get("targets", []):
                used.update(t.values())
    for s in j.get("skins", []):
        if "inverseBindMatrices" in s:
            used.add(s["inverseBindMatrices"])
    for a in anims:
        for s in a["samplers"]:
            used.update((s["input"], s["output"]))
    acc_map, new_acc = {}, []
    for i, a in enumerate(j["accessors"]):
        if i in used:
            acc_map[i] = len(new_acc)
            new_acc.append(a)
    views_used = sorted({a["bufferView"] for a in new_acc if "bufferView" in a} |
                        {img["bufferView"] for img in j.get("images", []) if "bufferView" in img})
    view_map, new_views, blob = {}, [], bytearray()
    for vi in views_used:
        v = dict(j["bufferViews"][vi])
        data = bin_[v.get("byteOffset", 0): v.get("byteOffset", 0) + v["byteLength"]]
        while len(blob) % 4:
            blob.append(0)
        v["byteOffset"] = len(blob)
        v["buffer"] = 0
        blob.extend(data)
        view_map[vi] = len(new_views)
        new_views.append(v)
    for a in new_acc:
        if "bufferView" in a:
            a["bufferView"] = view_map[a["bufferView"]]
    for img in j.get("images", []):
        if "bufferView" in img:
            img["bufferView"] = view_map[img["bufferView"]]
    for m in j.get("meshes", []):
        for p in m["primitives"]:
            p["attributes"] = {k: acc_map[v] for k, v in p["attributes"].items()}
            if "indices" in p:
                p["indices"] = acc_map[p["indices"]]
            p["targets"] = [{k: acc_map[v] for k, v in t.items()} for t in p.get("targets", [])] or None
            if p["targets"] is None:
                del p["targets"]
    for s in j.get("skins", []):
        if "inverseBindMatrices" in s:
            s["inverseBindMatrices"] = acc_map[s["inverseBindMatrices"]]
    for a in anims:
        for s in a["samplers"]:
            s["input"], s["output"] = acc_map[s["input"]], acc_map[s["output"]]
    j["accessors"], j["bufferViews"] = new_acc, new_views
    while len(blob) % 4:
        blob.append(0)
    j["buffers"] = [{"byteLength": len(blob)}]
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    return (b"glTF" + struct.pack("<II", 2, total) + struct.pack("<I", len(js)) + b"JSON" + js
            + struct.pack("<I", len(blob)) + b"BIN\x00" + bytes(blob))


if __name__ == "__main__":
    src, dst, *rest = sys.argv[1:]
    j, b = load(src)
    out = repack(j, b, keep=set(rest) - {"--dedupe"} or None, dedupe="--dedupe" in rest)
    open(dst, "wb").write(out)
    print(dst, len(out) // 1024, "KB")
