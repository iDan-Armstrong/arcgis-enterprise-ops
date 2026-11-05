from datetime import UTC, datetime

import pytest

from egisops import incident
from egisops.findings import Severity

NOW = datetime(2026, 11, 5, 12, tzinfo=UTC)
SRV = "https://gis.example.com/server"
PTL = "https://gis.example.com/portal"


def pb(kind, **kw):
    return incident.playbook(
        incident.IncidentContext(kind=kind, server=SRV, portal=PTL, now=NOW, **kw)
    )


def index(steps, pred):
    return next(i for i, s in enumerate(steps) if pred(s))


@pytest.mark.parametrize("kind", sorted(incident.KINDS))
def test_every_playbook_has_shape(kind):
    p = pb(kind)
    phases = [s.phase for s in p.steps]
    assert phases[0] == "Triage" and phases[-1] == "Learn"
    assert set(phases) <= set(incident.PHASES)
    assert "Preserve" in phases and "Recover" in phases
    assert any("egisops security" in s.command for s in p.steps)


@pytest.mark.parametrize("kind", sorted(incident.KINDS))
def test_federal_notify_right_after_triage(kind):
    p = pb(kind, federal=True)
    first_non_triage = next(s for s in p.steps if s.phase != "Triage")
    assert first_non_triage.phase == "Notify" and "CISA" in first_non_triage.title
    assert any(f.code == "INC105" for f in p.findings)


# Steps that change what an investigator could still see. Cutting access (stopping an
# exposed service, disabling a compromised admin, changing the token key) is not here on
# purpose: that comes first, as in rdsops, because an attacker with admin can clear logs.
DESTROYS = (
    "rotate",
    "reset",
    "rebuild",
    "--import",
    "machines/",
    "remove what",
    "undo",
)


@pytest.mark.parametrize("kind", sorted(incident.KINDS))
def test_logs_saved_before_anything_destroys_evidence(kind):
    steps = pb(kind).steps
    logs = index(steps, lambda s: "logs/query" in s.command)
    destructive = [
        i for i, s in enumerate(steps) if any(w in (s.title + s.command).lower() for w in DESTROYS)
    ]
    assert all(i > logs for i in destructive)


def test_content_exports_before_import():
    steps = pb("content").steps
    assert index(steps, lambda s: "--export" in s.command) < index(
        steps, lambda s: "--import" in s.command
    )


def test_host_captures_disk_before_leaving_the_site():
    steps = pb("host", machine="GISSRV02").steps
    snap = index(steps, lambda s: "create-snapshot" in s.command)
    stop = index(steps, lambda s: "machines/GISSRV02/stop" in s.command)
    isolate = index(steps, lambda s: s.title.startswith("Isolate"))
    assert isolate < snap < stop


def test_no_secrets_in_any_step():
    for kind in incident.KINDS:
        for s in pb(kind, user="jdoe").steps:
            text = (s.command + s.why).lower()
            assert "token=" not in text and "password=" not in text and "sharedkey=" not in text


def test_admin_account_disables_not_deletes():
    p = pb("admin-account", user="jdoe", psa_enabled=True)
    assert any("community/users/jdoe/disable" in s.command for s in p.steps)
    assert not any("/delete" in s.command for s in p.steps)
    assert any("psa/disable" in s.command for s in p.steps)
    assert any(f.code == "INC102" for f in p.findings)


def test_standalone_server_has_no_portal_steps():
    p = incident.playbook(incident.IncidentContext(kind="exposed-service", server=SRV, now=NOW))
    assert not any("portaladmin" in s.command or "sharing/rest" in s.command for s in p.steps)


def test_backup_readiness():
    assert pb("content", backup_age_hours=40).findings[0].severity == Severity.WARN
    assert pb("content", backup_age_hours=6).findings[0].severity == Severity.OK
    assert pb("content").findings[0].severity == Severity.INFO


def test_unknown_kind():
    with pytest.raises(ValueError):
        pb("nope")


def test_commands_marked():
    assert incident.is_command("POST https://x/admin/logs/query")
    assert not incident.is_command("Disable the account")
