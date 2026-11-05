"""Evaluators import without network modules, so a browser simulator can run them."""

import subprocess
import sys


def test_evaluators_import_without_network_stack():
    code = (
        "import sys\n"
        "for m in ['urllib.request', 'socket', 'ssl', 'http.client']:\n"
        "    sys.modules[m] = None\n"
        "import egisops.findings, egisops.server, egisops.services, egisops.logs\n"
        "import egisops.portal, egisops.datastore\n"
        "from datetime import datetime, UTC\n"
        "s = egisops.server.ServerSnapshot('x', 200, True, '11.5.0', True)\n"
        "assert egisops.server.evaluate(s, datetime.now(UTC))\n"
        "assert egisops.portal.evaluate(egisops.portal.PortalSnapshot('x'), datetime.now(UTC))\n"
        "from egisops.datastore import DataStoreSnapshot, evaluate\n"
        "assert evaluate(DataStoreSnapshot('x'), datetime.now(UTC))\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
