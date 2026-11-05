"""Incident playbooks for an ArcGIS Enterprise site, filled in for the site.

The same shape as ``rdsops incident``: ``playbook`` is pure, returns readiness findings
and ordered steps tagged with NIST SP 800-61 Rev. 3 phases, and never runs anything
(ADR 0008). Steps that are REST operations are written as ``POST <url> name=value``;
anything else is an instruction. No step contains a token, a password or a key: where a
new secret is needed, the step says so and the person running it supplies it.

Rules every playbook keeps, enforced by tests:
- Preserve before you change: logs and a webgisdr export come before resetting keys,
  restoring, deleting or rebuilding.
- With ``--federal`` the CISA notification comes right after triage.
- Every playbook ends with ``egisops security`` and a review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .findings import Finding, Severity

KINDS = {
    "admin-account": "An administrator account on the server or portal is in the wrong hands",
    "token": "Tokens or the token shared key leaked",
    "exposed-service": "A service or item was open to people who should not reach it",
    "content": "Items, services or data were deleted or changed by someone",
    "host": "A machine in the site is compromised (malware, an unknown process, a new account)",
}
PHASES = ("Triage", "Notify", "Contain", "Preserve", "Eradicate", "Recover", "Learn")


@dataclass
class IncidentContext:
    kind: str
    server: str = "https://<server>/arcgis"
    portal: str | None = None  # None for a standalone server
    federal: bool = False
    user: str | None = None  # the account involved
    service: str | None = None  # folder/name.Type, e.g. Utilities/Hydrants.MapServer
    item: str | None = None  # portal item id
    machine: str | None = None  # a site machine name
    since: datetime | None = None
    now: datetime | None = None
    backup_age_hours: float | None = None  # newest webgisdr backup, if known
    rpo_hours: float = 24
    psa_enabled: bool | None = None


@dataclass
class Step:
    phase: str
    title: str
    command: str = ""
    why: str = ""


COMMAND_STARTS = ("POST ", "GET ", "webgisdr ", "egisops ", "aws ")


def is_command(text: str) -> bool:
    return text.startswith(COMMAND_STARTS)


@dataclass
class Playbook:
    kind: str
    findings: list[Finding] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "findings": [f.to_dict() for f in self.findings],
            "steps": [s.__dict__ for s in self.steps],
        }


def _srv(c: IncidentContext, path: str) -> str:
    return f"{c.server.rstrip('/')}/admin/{path}"


def _ptl(c: IncidentContext, path: str) -> str:
    return f"{(c.portal or '').rstrip('/')}/{path}"


def _since(c: IncidentContext) -> str:
    if c.since:
        return str(int(c.since.timestamp() * 1000))
    return "<epoch ms of the last known good time>"


def _who(c: IncidentContext) -> str:
    return c.user or "<account>"


# --------------------------------------------------------------- shared steps


def _triage(c: IncidentContext) -> list[Step]:
    site = c.portal or c.server
    return [
        Step(
            "Triage",
            "Open an incident record and name one incident lead",
            "",
            "Start a timeline now (UTC). Every action from here on goes in it with who and when.",
        ),
        Step(
            "Triage",
            "Scope: which site, which machines, which data",
            f"Site {site}. List the federated servers, the registered data stores and the "
            "enterprise geodatabases behind them.",
            "A compromise of the site reaches every database registered with it.",
        ),
    ]


def _notify(c: IncidentContext) -> list[Step]:
    if c.federal:
        return [
            Step(
                "Notify",
                "Report to CISA within one hour of identification",
                "https://www.cisa.gov/report",
                "CISA's Federal Incident Notification Guidelines: federal Executive Branch "
                "civilian agencies notify CISA within one hour of the incident being identified "
                "by the agency's top-level CSIRT, SOC or IT department. Report what is known; "
                "update later. Contractors report through the agency and their contract terms.",
            ),
            Step(
                "Notify",
                "Tell the agency SOC and the system owner",
                "",
                "Follow the agency incident response plan, including privacy officials if "
                "personal data may be involved.",
            ),
        ]
    return [
        Step(
            "Notify",
            "Escalate under your incident response plan",
            "",
            "Security team, system owner, and legal or privacy if personal data may be involved.",
        )
    ]


def _logs(c: IncidentContext) -> list[Step]:
    steps = [
        Step(
            "Preserve",
            "Save the server logs before anything changes",
            f"POST {_srv(c, 'logs/query')} level=FINE startTime=<now ms> endTime={_since(c)} "
            "pageSize=10000 f=json",
            "Server logs roll over and the log level may be low; save them now, page by page, "
            "into the incident record. Raise the level to FINE for the duration.",
        )
    ]
    if c.portal:
        steps.append(
            Step(
                "Preserve",
                "Save the portal logs",
                f"POST {_ptl(c, 'portaladmin/logs/query')} level=FINE startTime=<now ms> "
                f"endTime={_since(c)} f=json",
                "Portal logs show sign-ins, sharing changes and administrative actions.",
            )
        )
    steps.append(
        Step(
            "Preserve",
            "Save the web server and load balancer access logs",
            "",
            "They hold source addresses that ArcGIS logs do not. Copy them off the machines.",
        )
    )
    return steps


def _export(c: IncidentContext, why: str) -> list[Step]:
    return [
        Step(
            "Preserve",
            "Export a webgisdr backup of the site as it is now",
            "webgisdr --export --file webgisdr.properties",
            why + " Keep it apart from the regular backups and mark it as incident evidence; "
            "`egisops backup-check` confirms the properties first.",
        )
    ]


def _learn(c: IncidentContext) -> list[Step]:
    steps = [
        Step(
            "Learn",
            "Check the server against Esri's security practices",
            f"egisops security --url {c.server}",
            "Fix what it finds before closing the incident.",
        )
    ]
    if c.portal:
        steps.append(
            Step(
                "Learn",
                "And the portal",
                f"egisops security --url {c.portal} --portal",
                "",
            )
        )
    steps.append(
        Step(
            "Learn",
            "Review: timeline, root cause, what to change",
            "",
            "Within two weeks. Update this playbook with what was missing.",
        )
    )
    return steps


# --------------------------------------------------------------- playbooks


def _admin_account(c: IncidentContext, pb: Playbook) -> None:
    who = _who(c)
    contain = []
    if c.portal:
        contain.append(
            Step(
                "Contain",
                f"Disable the portal account {who}",
                f"POST {_ptl(c, f'sharing/rest/community/users/{who}/disable')} f=json",
                "Disabling blocks new sign-ins and keeps the account and its content for the "
                "investigation. Do not delete it. Access is cut before the logs are saved "
                "because an administrator can clear them.",
            )
        )
    contain.append(
        Step(
            "Contain",
            "Invalidate tokens already issued",
            "Update the token shared key (server: security/tokens/update; portal: its token "
            "settings). You enter a new random key; it is never written here.",
            "A disabled account's tokens stay valid until they expire. Changing the key ends "
            "them all, so every user signs in again.",
        )
    )
    contain.append(
        Step(
            "Contain",
            "Limit admin access while you work",
            f"POST {_srv(c, 'security/config/update')} allowedAdminAccessIPs=<incident team "
            "addresses> f=json",
            "Keeps the admin API to the people responding. Undo at the end.",
        )
    )
    pb.steps += contain
    pb.steps += _logs(c)
    pb.steps += [
        Step(
            "Preserve",
            f"List what {who} did",
            "",
            "From the saved logs: sign-ins and addresses, services published, stopped or "
            "deleted, permissions changed, data stores registered, users or roles created.",
        ),
        Step(
            "Eradicate",
            "Remove what the attacker added",
            "",
            "Accounts, roles, API keys or app registrations created; services or data stores "
            "registered; permissions granted. Keep a record of each before removing it.",
        ),
        Step(
            "Eradicate",
            "Reset the credentials that account could read",
            "",
            "Data store and enterprise geodatabase passwords used by registered connections, "
            "the primary site administrator, and any service account. For RDS geodatabases, "
            "`rdsops incident --kind credentials`.",
        ),
    ]
    if c.psa_enabled is not False:
        pb.steps.append(
            Step(
                "Eradicate",
                "Disable the primary site administrator",
                f"POST {_srv(c, 'security/psa/disable')} f=json",
                "It cannot be locked out by the identity store. Re-enable it from the machine "
                "only when needed.",
            )
        )
    pb.steps += [
        Step(
            "Recover",
            f"Give {who} back to its owner with a new password and MFA",
            "",
            "Only after the review of what it did is done. If it was a shared admin account, "
            "replace it with named accounts.",
        ),
        Step(
            "Recover",
            "Lift the admin IP restriction set during containment",
            f"POST {_srv(c, 'security/config/update')} allowedAdminAccessIPs=<previous value> "
            "f=json",
            "",
        ),
    ]


def _token(c: IncidentContext, pb: Playbook) -> None:
    pb.steps += _logs(c)
    pb.steps += [
        Step(
            "Contain",
            "Change the token shared key",
            "Server: POST "
            + _srv(c, "security/tokens/update")
            + " with a new sharedKey you generate; portal: update its token key. Never paste "
            "the key into chat, tickets or this record.",
            "Every token issued with the old key stops working at once. Users sign in again; "
            "services and apps that store tokens need new ones.",
        ),
        Step(
            "Contain",
            "Turn off token requests that put credentials in URLs",
            f"POST {_srv(c, 'security/tokens/update')} allowHttpGet=false "
            "allowHttpPostQueryParams=false",
            "Leaked tokens often come from URLs in logs or browser history (Esri SS03/SS04).",
        ),
        Step(
            "Preserve",
            "Find where the token was used",
            "",
            "In the saved logs and access logs: requests carrying it, from which addresses, "
            "and which services. That decides whether data was read or changed.",
        ),
        Step(
            "Eradicate",
            "Find how it leaked",
            "",
            "Scripts, notebooks or app configs with tokens in them, URLs pasted in tickets or "
            "chat, a proxy logging query strings. Remove the token from each.",
        ),
        Step(
            "Recover",
            "Issue new credentials to the apps and scripts that need them",
            "",
            "Use short token lifetimes and keep them out of URLs and code.",
        ),
    ]


def _exposed_service(c: IncidentContext, pb: Playbook) -> None:
    svc = c.service or "<folder/name.Type>"
    pb.steps += [
        Step(
            "Contain",
            f"Stop {svc}",
            f"POST {_srv(c, f'services/{svc}/stop')} f=json",
            "Stopping closes it at once. If it must keep running for others, remove anonymous "
            "access instead.",
        ),
        Step(
            "Contain",
            "Remove anonymous access",
            f"POST {_srv(c, f'services/{svc}/permissions/add')} principal=esriEveryone "
            "isAllowed=false f=json",
            "",
        ),
    ]
    if c.portal:
        pb.steps.append(
            Step(
                "Contain",
                "Unshare the item from Everyone",
                f"Item {c.item or '<item id>'}: share with Everyone off, in the portal or with "
                "the sharing/rest share operation (everyone=false).",
                "On a federated server the item's sharing is what grants access.",
            )
        )
    pb.steps += _logs(c)
    pb.steps += [
        Step(
            "Preserve",
            "Measure what was reached",
            "",
            "Query, extract and edit requests to the service while it was open, by address. "
            "For a feature service with editing, also check edit tracking or the versioned "
            "history for changes.",
        ),
        Step(
            "Eradicate",
            "Undo unauthorized edits",
            "",
            "From edit tracking, versioning or the geodatabase backup. Keep the changed data "
            "first.",
        ),
        Step(
            "Eradicate",
            "Rotate anything the service exposed",
            "",
            "Credentials or keys in attributes or attachments; database credentials if the "
            "service allowed a dynamic workspace.",
        ),
        Step(
            "Recover",
            "Restart the service with the right sharing",
            f"POST {_srv(c, f'services/{svc}/start')} f=json",
            "Share it with the groups that need it, never Everyone for sensitive data, and turn "
            "off create, update and delete for anyone who should only read.",
        ),
    ]


def _content(c: IncidentContext, pb: Playbook) -> None:
    pb.steps += [
        Step(
            "Contain",
            "Stop the account or process making the changes",
            f"Disable {_who(c)}, or stop the script or service that is writing.",
            "Every minute of deletion makes recovery bigger.",
        ),
    ]
    pb.steps += _logs(c)
    pb.steps += _export(
        c,
        "A webgisdr import replaces the whole site. This export keeps what is there now, "
        "including anything created since the last good backup, and the evidence.",
    )
    pb.steps += [
        Step(
            "Eradicate",
            "Close the way in",
            "",
            "Use the admin-account or token playbook for the account that made the changes.",
        ),
        Step(
            "Recover",
            "Restore the smallest thing that fixes it",
            "",
            "One item: the recycle bin if your release has it turned on, or re-create it "
            "from the owner's copy. "
            "Hosted data: restore its data store backup. Registered data: the geodatabase "
            "backup (`rdsops incident --kind destruction` for RDS).",
        ),
        Step(
            "Recover",
            "Whole site only if the damage is that wide",
            "webgisdr --import --file webgisdr.properties",
            "Imports the last good backup over the site. Everything created since that "
            "backup is lost unless re-created from the incident export.",
        ),
    ]


def _host(c: IncidentContext, pb: Playbook) -> None:
    m = c.machine or "<machine>"
    pb.steps += [
        Step(
            "Contain",
            f"Isolate {m} at the network",
            "Security group, firewall or network ACL: no inbound, and outbound only to your "
            "evidence store.",
            "Isolating instead of shutting down keeps memory and running processes for the "
            "investigation. In a multi-machine site the others keep serving.",
        ),
        Step(
            "Preserve",
            f"Capture {m} before anything else",
            "aws ec2 create-snapshot --volume-id <volume> --description "
            f"'incident {m}'  (for each volume)",
            "And a memory capture if your team does them. On premises, use your hypervisor or "
            "disk imaging.",
        ),
    ]
    pb.steps += _logs(c)
    pb.steps += [
        Step(
            "Contain",
            f"Take {m} out of the site",
            f"POST {_srv(c, f'machines/{m}/stop')} f=json",
            "Then unregister it once evidence is captured. A single-machine site is down "
            "from here until it is rebuilt.",
        ),
        Step(
            "Eradicate",
            "Rotate every secret that machine held",
            "",
            "Token shared key, primary site administrator, the run-as account, data store and "
            "geodatabase passwords in .sde files and registered connections, webgisdr "
            "properties credentials, and any cloud keys on the machine.",
        ),
        Step(
            "Recover",
            "Rebuild, do not clean",
            "",
            "A new machine from a known image or your automation, patched, then joined to the "
            "site. Nothing copied from the old disk except reviewed configuration.",
        ),
        Step(
            "Recover",
            "Watch the site closely for two weeks",
            "egisops server-health --url " + c.server,
            "Plus the server logs at FINE and the access logs for the addresses found.",
        ),
    ]


BUILDERS = {
    "admin-account": _admin_account,
    "token": _token,
    "exposed-service": _exposed_service,
    "content": _content,
    "host": _host,
}


def readiness(c: IncidentContext) -> list[Finding]:
    out: list[Finding] = []
    if c.backup_age_hours is None:
        out.append(
            Finding(
                "INC101",
                Severity.INFO,
                "Age of the newest webgisdr backup not given",
                "Run egisops backup-check, or pass --backup-age-hours, to know what a full "
                "restore would lose.",
            )
        )
    elif c.backup_age_hours > c.rpo_hours:
        out.append(
            Finding(
                "INC101",
                Severity.WARN,
                f"Newest webgisdr backup is {c.backup_age_hours:.0f} hours old",
                f"Older than the {c.rpo_hours:g}-hour recovery point. A full restore loses more "
                "than you planned for; take the incident export before anything else changes.",
                {"backupAgeHours": c.backup_age_hours, "rpoHours": c.rpo_hours},
            )
        )
    else:
        out.append(
            Finding(
                "INC101",
                Severity.OK,
                f"Newest webgisdr backup is {c.backup_age_hours:.0f} hours old",
            )
        )
    if c.psa_enabled:
        out.append(
            Finding(
                "INC102",
                Severity.WARN,
                "The primary site administrator is enabled",
                "If its password is known to the attacker, they keep admin access through any "
                "identity store change. It is disabled in the playbook.",
            )
        )
    if c.federal:
        out.append(
            Finding(
                "INC105",
                Severity.WARN,
                "Federal system: CISA notification due within one hour of identification",
                "The clock starts when the agency's CSIRT, SOC or IT department identifies the "
                "incident, not when the investigation ends.",
            )
        )
    return out


def playbook(c: IncidentContext) -> Playbook:
    if c.kind not in BUILDERS:
        raise ValueError(f"unknown incident kind {c.kind!r}; one of {', '.join(BUILDERS)}")
    pb = Playbook(c.kind, readiness(c))
    pb.steps += _triage(c)
    pb.steps += _notify(c)
    BUILDERS[c.kind](c, pb)
    pb.steps += _learn(c)
    return pb
