"""A tiny in-memory stand-in for a googleapiclient Drive `service`, just enough to
exercise our upload/dedup/appProperties logic without touching the network.

Emulates the fluent API we use: service.files().create(...).execute(),
.update(...).execute(), .list(...).execute(). appProperties merge on update, the
way Drive actually behaves, so the relevance round-trip is faithful."""
import itertools
import re


class _Req:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class _Files:
    def __init__(self, store, counter):
        self.store = store          # id -> file dict
        self._counter = counter

    def create(self, body=None, media_body=None, fields=None, supportsAllDrives=False):
        meta = body or {}

        def go():
            fid = "f%d" % next(self._counter)
            self.store[fid] = {
                "id": fid,
                "name": meta.get("name"),
                "parents": list(meta.get("parents") or []),
                "appProperties": dict(meta.get("appProperties") or {}),
                "modifiedTime": meta.get("modifiedTime", "2026-01-01T00:00:00.000Z"),
                "trashed": False,
            }
            return {"id": fid}

        return _Req(go)

    def update(self, fileId=None, media_body=None, body=None, fields=None,
               supportsAllDrives=False):
        meta = body or {}

        def go():
            f = self.store[fileId]
            props = meta.get("appProperties")
            if props:
                # Drive MERGES appProperties on update (a null value would delete a
                # key; we don't exercise deletes here).
                merged = dict(f.get("appProperties") or {})
                merged.update(props)
                f["appProperties"] = merged
            if meta.get("trashed") is not None:
                f["trashed"] = meta["trashed"]
            return {"id": fileId}

        return _Req(go)

    def list(self, q=None, fields=None, pageSize=None, orderBy=None,
             supportsAllDrives=False, includeItemsFromAllDrives=False):
        def go():
            name = parent = None
            m = re.search(r"name='([^']*)'", q or "")
            if m:
                name = m.group(1).replace("\\'", "'").replace("\\\\", "\\")
            m = re.search(r"'([^']*)' in parents", q or "")
            if m:
                parent = m.group(1)
            res = [
                f for f in self.store.values()
                if not f["trashed"]
                and (name is None or f["name"] == name)
                and (parent is None or parent in f["parents"])
            ]
            res.sort(key=lambda d: d.get("modifiedTime") or "", reverse=True)
            return {"files": [
                {"id": f["id"], "name": f["name"], "modifiedTime": f["modifiedTime"]}
                for f in res
            ]}

        return _Req(go)


class FakeDrive:
    def __init__(self):
        self.store = {}
        self._files = _Files(self.store, itertools.count(1))

    def files(self):
        return self._files

    def live_named(self, name):
        """Count of non-trashed files with this exact name (duplicate detector)."""
        return sum(1 for f in self.store.values()
                   if f["name"] == name and not f["trashed"])
