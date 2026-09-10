"""Fakes shared by the tests. No network, no live herdr server."""

import json


def envelope(result):
    return json.dumps({"id": "test", "result": result})


class FakeRunner:
    """Stands in for subprocess. Maps an argv prefix to (rc, stdout, stderr)."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        for prefix, response in self.responses.items():
            if list(argv[: len(prefix)]) == list(prefix):
                return response
        return (0, envelope({"type": "ok"}), "")

    def calls_matching(self, *prefix):
        return [c for c in self.calls if c[: len(prefix)] == list(prefix)]


def agent(pane_id, kind="claude", **extra):
    row = {"pane_id": pane_id, "agent": kind, "agent_status": "idle"}
    row.update(extra)
    return row


def process(pid, name="claude", argv=None):
    return {"pid": pid, "name": name, "argv": argv or ["/usr/bin/claude"], "cmdline": "claude"}
