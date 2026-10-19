"""XiaoBaWang V0.1: safe routing core; no platform networking."""
from dataclasses import dataclass
from typing import Iterable

@dataclass(frozen=True)
class Rule:
    id: str
    tg_account: str
    tg_chat_id: str
    wa_account: str
    wa_group_id: str
    enabled: bool = False
    approval_required: bool = True

@dataclass(frozen=True)
class Event:
    tg_account: str
    tg_chat_id: str
    message_id: str
    text: str

class Router:
    def __init__(self, rules: Iterable[Rule], dry_run: bool = True):
        self.rules = tuple(rules)
        self.dry_run = dry_run
        self.seen: set[str] = set()

    def prepare(self, event: Event) -> list[dict]:
        """Select explicitly enabled routes and deduplicate per target."""
        deliveries = []
        for rule in self.rules:
            if not rule.enabled:
                continue
            if (event.tg_account, event.tg_chat_id) != (rule.tg_account, rule.tg_chat_id):
                continue
            if not event.text.strip():
                continue
            key = "|".join((event.tg_account, event.tg_chat_id, event.message_id,
                            rule.wa_account, rule.wa_group_id))
            if key in self.seen:
                continue
            self.seen.add(key)
            deliveries.append({
                "rule_id": rule.id,
                "wa_account": rule.wa_account,
                "wa_group_id": rule.wa_group_id,
                "text": event.text,
                "status": "pending_approval" if rule.approval_required else "dry_run",
                "dry_run": self.dry_run,
            })
        return deliveries

def can_send(*, dry_run: bool, backend_enabled: bool, bridge_enabled: bool,
             approved: bool, rule_enabled: bool) -> bool:
    """Explicit, independent safety gates. A successful result only authorizes dispatch."""
    return bool(not dry_run and backend_enabled and bridge_enabled
                and approved and rule_enabled)
